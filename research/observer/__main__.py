"""python -m research.observer {start,resume,stop,status} {smoke,pilot}"""

import argparse
import json
import os
import sqlite3
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .records import discover, observe
from .store import ROOT, Halt, Mode, connect, health, initialize, owner
from .transport import SERIES, Client, FetchError


@contextmanager
def ingest_response(db: sqlite3.Connection, rid: int) -> Iterator[None]:
    try:
        with db:
            yield
    except FetchError as exc:
        with db:
            db.execute("UPDATE requests SET error=? WHERE id=?", (str(exc), rid))
        raise


def poll(client: Client, slot: int) -> str:
    db = client.db
    if not db.execute(
        "SELECT 1 FROM requests WHERE path=? AND error IS NULL AND receipt IS NOT NULL",
        ("/series/" + SERIES,),
    ).fetchone():
        rid, _, obj = client.get(slot, "/series/" + SERIES)
        if not isinstance(obj.get("series"), dict) or obj["series"].get("ticker") != SERIES:
            with db:
                db.execute("UPDATE requests SET error='series mismatch' WHERE id=?", (rid,))
            raise Halt("series mismatch")
    last = db.execute(
        """SELECT max(receipt) FROM requests r JOIN metadata m ON r.id=m.request_id"""
    ).fetchone()[0]
    partial = False
    has_roster = db.execute("SELECT 1 FROM roster LIMIT 1").fetchone() is not None
    if last is None or client.clock() - last >= 3600 or not has_roster:
        rid, receipt, obj = client.get(
            slot,
            "/events",
            series_ticker=SERIES,
            min_close_ts=str(int(client.clock()) - 86400),
            with_nested_markets="true",
            with_milestones="true",
            limit="100",
        )
        with ingest_response(db, rid):
            partial = discover(db, rid, receipt, obj)
    tickers = [r[0] for r in db.execute("SELECT ticker FROM roster ORDER BY ticker")]
    if not tickers:
        return "no observed roster"
    for offset in range(0, len(tickers), 64):
        subset = tickers[offset : offset + 64]
        rid, receipt, obj = client.get(slot, "/markets", tickers=",".join(subset))
        with ingest_response(db, rid):
            partial = observe(db, rid, receipt, obj, subset) or partial
    unlisted = db.execute(
        "SELECT 1 FROM targets t WHERE NOT EXISTS(SELECT 1 FROM roster r WHERE r.event=t.event)"
    ).fetchone()
    return "partial coverage" if partial or unlisted else "ok"


def finish_slot(db: sqlite3.Connection, slot: int, end: float, quality: str) -> None:
    with db:
        updated = db.execute(
            "UPDATE polls SET finished=?,quality=? WHERE slot=? AND finished IS NULL",
            (end, quality, slot),
        )
        if updated.rowcount and quality != "ok":
            db.execute("INSERT INTO gaps VALUES(?,1,?)", (slot, quality))


def run(db: sqlite3.Connection, client: Client, pause: Callable[[float], None] = time.sleep) -> str:
    with db:
        for r in db.execute("SELECT slot FROM polls WHERE finished IS NULL").fetchall():
            finish_slot(db, r[0], client.clock(), "interrupted poll")
        db.execute(
            """UPDATE requests SET error='interrupted request' WHERE receipt IS NULL AND error IS NULL"""
        )
        db.execute(
            "UPDATE campaign SET state='running',reason='',stop_requested=0,heartbeat=?",
            (client.clock(),),
        )
    reason = "worker error"
    slot: int | None = None
    try:
        while True:
            c = db.execute("SELECT * FROM campaign").fetchone()
            now = client.clock()
            if c["stop_requested"]:
                raise Halt("operator stop")
            if now >= c["deadline"]:
                raise Halt("deadline")
            if c["next_slot"] >= c["max_slots"]:
                raise Halt("campaign complete")
            due = int((now - c["started"]) // c["interval_s"])
            if now - c["heartbeat"] >= 15:
                with db:
                    db.execute("UPDATE campaign SET heartbeat=?", (now,))
            if due < c["next_slot"]:
                pause(
                    min(
                        5.0,
                        c["started"] + c["next_slot"] * c["interval_s"] - now,
                        c["deadline"] - now,
                    )
                )
                continue
            with db:
                if due > c["next_slot"]:
                    db.execute(
                        "INSERT INTO gaps VALUES(?,?,'downtime or overrun')",
                        (c["next_slot"], min(due, c["max_slots"]) - c["next_slot"]),
                    )
                if due >= c["max_slots"]:
                    db.execute("UPDATE campaign SET next_slot=max_slots")
                else:
                    db.execute("INSERT INTO polls(slot,started) VALUES(?,?)", (due, now))
                    db.execute("UPDATE campaign SET next_slot=?", (due + 1,))
            if due >= c["max_slots"]:
                raise Halt("campaign complete")
            slot = due
            try:
                quality = poll(client, slot)
            except FetchError as exc:
                quality = str(exc)
            finish_slot(db, slot, client.clock(), quality)
            slot = None
    except Halt as exc:
        reason = str(exc)
    except KeyboardInterrupt:
        reason = "operator interrupt"
    finally:
        if slot is not None:
            finish_slot(db, slot, client.clock(), reason)
        with db:
            db.execute(
                "UPDATE requests SET error='interrupted request' WHERE receipt IS NULL AND error IS NULL"
            )
            db.execute(
                "UPDATE campaign SET state='stopped',reason=?,heartbeat=?", (reason, client.clock())
            )
    return reason


def command(action: str, mode: Mode, root: Path = ROOT) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true" and action != "status":
        raise Halt("local campaign only")
    path = root / (mode + ".sqlite")
    if action == "status":
        print(json.dumps(asdict(health(root, mode)), indent=2))
        return
    if action == "stop":
        if not path.exists():
            raise Halt("not started")
        db = connect(path)
        try:
            with db:
                db.execute("UPDATE campaign SET stop_requested=1")
        finally:
            db.close()
        return
    with owner(root, mode):
        if path.exists() != (action == "resume"):
            raise Halt("use resume for an existing campaign" if path.exists() else "not started")
        db = connect(path)
        try:
            if action == "start":
                initialize(db, mode, time.time())
            else:
                row = db.execute("SELECT * FROM campaign").fetchone()
                if row["state"] == "stopped" and row["reason"] in ("deadline", "campaign complete"):
                    raise Halt("campaign has ended")
                if row["reason"] in (
                    "request budget",
                    "byte budget",
                    "series mismatch",
                    "HTTP 401",
                    "HTTP 403",
                ) or row["reason"].startswith("HTTP 3"):
                    raise Halt("campaign has ended")
            print(f"{mode} observer started", flush=True)
            print(run(db, Client(db)), flush=True)
        finally:
            db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Local NBA research observer")
    parser.add_argument("action", choices=("start", "resume", "stop", "status"))
    parser.add_argument("mode", choices=("smoke", "pilot"))
    args = parser.parse_args()
    try:
        command(args.action, args.mode)
        return 0
    except Halt as exc:
        print(str(exc))
        return 2
    except (sqlite3.Error, OSError, ValueError, TypeError):
        print("observer storage or data error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
