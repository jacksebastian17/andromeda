"""Read-only, direction-blind checkpoint of the seven-day pilot."""

import json
import sqlite3
import time
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .e1 import require
from .e3 import ROOT as E3_ROOT
from .e3 import Row, participant
from .observer.records import fixed
from .observer.store import ROOT, connect, stamp


def schedule_status(
    db: sqlite3.Connection,
    event: str,
    history: list[sqlite3.Row],
    campaign: sqlite3.Row,
    now: float,
) -> str:
    if len({r["group_key"] for r in history}) != 1 or not history[0]["group_key"]:
        return "ambiguous_identity"
    if any(r["schedule_state"] == "ambiguous" for r in history):
        return "ambiguous_schedule"
    schedules = [r for r in history if r["schedule_state"] == "reported"]
    if not schedules or len({r["schedule"] for r in schedules}) != 1:
        return "missing_or_revised_schedule"
    decision = datetime.fromisoformat(schedules[0]["schedule"]).timestamp() - 3600
    if schedules[0]["receipt"] > decision:
        return "late_enrollment_or_schedule"
    if decision > now:
        return "pending_horizon"
    key = schedules[0]["group_key"]
    candidates = db.execute(
        """SELECT o.snapshot,r.slot FROM observations o
        JOIN requests r ON r.id=o.request_id WHERE o.event=? AND o.group_key=?
        AND o.status IN ('active','open') AND r.error IS NULL AND r.status=200
        AND r.receipt BETWEEN ? AND ? ORDER BY r.receipt DESC""",
        (event, key, decision - 360, decision),
    )
    for snapshot, slot in candidates:
        m = json.loads(snapshot)
        if participant(m) != key.split("/")[-2]:
            continue
        bid, ask, nominal, bs, az = [
            fixed(m.get(k))
            for k in (
                "yes_bid_dollars",
                "yes_ask_dollars",
                "notional_value_dollars",
                "yes_bid_size_fp",
                "yes_ask_size_fp",
            )
        ]
        if not (bid and ask and nominal and 0 < bid <= ask < nominal and bs and az):
            continue
        decision_slot = int((decision - campaign["started"]) // campaign["interval_s"])
        covered = db.execute(
            """SELECT count(*) FROM polls WHERE slot BETWEEN ? AND ?
            AND finished IS NOT NULL AND quality='ok'""",
            (slot, decision_slot),
        ).fetchone()[0]
        if covered != decision_slot - slot + 1:
            return "decision_gap"
        return "scheduled_quote_eligible"
    return "missing_eligible_quote"


def checkpoint(path: Path, now: float) -> Row:
    if not path.exists():
        return {
            "as_of": stamp(now),
            "state": "not started",
            "observations": 0,
            "observed_games": 0,
            "strict_eligible_games": 0,
        }
    with closing(connect(path, readonly=True)) as db:
        db.execute("BEGIN")
        campaign = db.execute("SELECT * FROM campaign").fetchone()
        state = campaign["state"]
        if state == "running" and (now - campaign["heartbeat"] > 60 or now >= campaign["deadline"]):
            state = "stale"
        n, games, batches = db.execute("""SELECT count(*),count(DISTINCT group_key),
            count(DISTINCT request_id) FROM observations WHERE status!='missing'""").fetchone()
        history: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in db.execute("""SELECT m.event,m.group_key,m.schedule,m.schedule_state,r.receipt
            FROM metadata m JOIN requests r ON r.id=m.request_id ORDER BY r.receipt,m.id"""):
            history[row["event"]].append(row)
        owners: dict[str, set[str]] = defaultdict(set)
        for event, records in history.items():
            for row in records:
                owners[row["group_key"]].add(event)
        counts: Counter[str] = Counter()
        for event, records in history.items():
            if any(len(owners[r["group_key"]]) > 1 for r in records):
                counts["ambiguous_identity"] += 1
            else:
                counts[schedule_status(db, event, records, campaign, now)] += 1
        # This feed records an explicit null for actual tip. Refuse to infer provenance
        # if a future observer supplies values in that field.
        actual = db.execute("""SELECT count(DISTINCT group_key) FROM observations
            WHERE json_extract(snapshot,'$.actual_game_start') IS NOT NULL""").fetchone()[0]
        require(actual == 0, "verify the new actual-tip source before counting strict eligibility")
        return {
            "as_of": stamp(now),
            "state": state,
            "deadline": stamp(campaign["deadline"]),
            "observations": n,
            "observed_games": games,
            "quote_batches": batches,
            "scheduled_status": dict(counts),
            "strict_eligible_games": actual,
            "settlement_sightings": db.execute("SELECT count(*) FROM settlements").fetchone()[0],
            "recorded_gap_slots": db.execute("SELECT coalesce(sum(slots),0) FROM gaps").fetchone()[
                0
            ],
            "request_errors": db.execute(
                "SELECT count(*) FROM requests WHERE error IS NOT NULL"
            ).fetchone()[0],
        }


if __name__ == "__main__":
    result = checkpoint(ROOT / "pilot.sqlite", time.time())
    try:
        with (E3_ROOT / "pilot-checkpoint.json").open("x", encoding="utf8") as output:
            json.dump(result, output)
    except FileExistsError:
        pass  # Preserve the checkpoint used in the published report.
    print(json.dumps(result))
