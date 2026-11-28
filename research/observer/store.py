"""Private campaign storage and the aggregate-only status shared with the terminal."""

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[2] / "var/research/kalshi/a3_1"
Mode = Literal["smoke", "pilot"]


@dataclass(frozen=True)
class Limits:
    seconds: int
    requests: int
    bytes: int
    interval: int
    slots: int


LIMITS = {
    "smoke": Limits(900, 30, 20 << 20, 30, 4),
    "pilot": Limits(168 * 3600, 3500, 512 << 20, 300, 2016),
}


class Halt(Exception):
    """Only operator-safe fixed reason codes."""


def stamp(t: float | None) -> str | None:
    return None if t is None else datetime.fromtimestamp(t, UTC).isoformat()


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    db = sqlite3.connect(
        path.resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rwc"), uri=True, timeout=5
    )
    db.row_factory = sqlite3.Row
    return db


@contextmanager
def owner(root: Path, mode: Mode) -> Iterator[None]:
    """A separate SQLite writer lock is released by the OS on process death."""
    root.mkdir(parents=True, exist_ok=True)
    lock = sqlite3.connect(root / (mode + ".lock"), timeout=0)
    try:
        try:
            lock.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            raise Halt("worker already active") from None
        yield
    finally:
        lock.close()


def initialize(db: sqlite3.Connection, mode: Mode, now: float) -> None:
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS campaign(
            id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT, started REAL, deadline REAL,
            interval_s INTEGER, max_slots INTEGER, max_requests INTEGER, max_bytes INTEGER,
            next_slot INTEGER DEFAULT 0, state TEXT, reason TEXT, heartbeat REAL,
            stop_requested INTEGER DEFAULT 0, not_before REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS polls(slot INTEGER PRIMARY KEY, started REAL, finished REAL,
            quality TEXT);
        CREATE TABLE IF NOT EXISTS gaps(first_slot INTEGER, slots INTEGER, reason TEXT);
        CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY, slot INTEGER, path TEXT,
            query TEXT, sent REAL, receipt REAL, duration REAL, status INTEGER,
            charged INTEGER, received INTEGER, sha TEXT, body BLOB, error TEXT);
        CREATE TABLE IF NOT EXISTS targets(event TEXT PRIMARY KEY, day TEXT, first_request INTEGER);
        CREATE TABLE IF NOT EXISTS roster(ticker TEXT PRIMARY KEY,event TEXT);
        CREATE TABLE IF NOT EXISTS metadata(id INTEGER PRIMARY KEY, request_id INTEGER,
            event TEXT, group_key TEXT, schedule TEXT, schedule_state TEXT, rules TEXT);
        CREATE INDEX IF NOT EXISTS metadata_event ON metadata(event,id);
        CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY, request_id INTEGER,
            event TEXT, ticker TEXT, metadata_id INTEGER, group_key TEXT, status TEXT,
            snapshot TEXT, quality TEXT);
        CREATE INDEX IF NOT EXISTS observation_request ON observations(request_id);
        CREATE INDEX IF NOT EXISTS observation_ticker ON observations(ticker,id);
        CREATE TABLE IF NOT EXISTS settlements(request_id INTEGER,event TEXT,ticker TEXT,
            group_key TEXT, receipt REAL, source_settlement TEXT, value TEXT, result TEXT,
            quality TEXT, PRIMARY KEY(request_id,ticker));
    """)
    lim = LIMITS[mode]
    with db:
        db.execute(
            """INSERT INTO campaign(id,mode,started,deadline,interval_s,max_slots,
                   max_requests,max_bytes,state,reason,heartbeat) VALUES(1,?,?,?,?,?,?,?,'stopped','',?)""",
            (mode, now, now + lim.seconds, lim.interval, lim.slots, lim.requests, lim.bytes, now),
        )


@dataclass
class Health:
    mode: str
    state: str
    reason: str
    deadline: str | None
    last_observation: str | None
    observations: int
    groups: int
    resolved: int
    attempts: int
    max_requests: int
    charged_bytes: int
    max_bytes: int
    storage_bytes: int
    gap_slots: int
    errors: int
    last_error: str | None


def health(root: Path, mode: Mode, now: float | None = None) -> Health:
    now = time.time() if now is None else now
    path = root / (mode + ".sqlite")
    lim = LIMITS[mode]
    h = Health(
        mode,
        "stopped",
        "not started",
        None,
        None,
        0,
        0,
        0,
        0,
        lim.requests,
        0,
        lim.bytes,
        0,
        0,
        0,
        None,
    )
    if not path.exists():
        return h
    db = connect(path, readonly=True)
    try:
        db.execute("BEGIN")
        c = db.execute("SELECT * FROM campaign").fetchone()
        if c is None:
            raise sqlite3.DatabaseError("campaign unavailable")
        h.state, h.reason, h.deadline = c["state"], c["reason"], stamp(c["deadline"])
        if h.state == "running" and (now - c["heartbeat"] > 60 or now >= c["deadline"]):
            h.state, h.reason = "stale", "worker heartbeat overdue"
        h.attempts, h.charged_bytes = db.execute(
            "SELECT count(*),coalesce(sum(charged),0) FROM requests"
        ).fetchone()
        h.errors = db.execute("SELECT count(*) FROM requests WHERE error IS NOT NULL").fetchone()[0]
        err = db.execute(
            "SELECT error FROM requests WHERE error IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        h.last_error = err[0] if err else None
        h.observations, h.groups = db.execute(
            """SELECT count(*),count(DISTINCT group_key) FROM observations WHERE status!='missing'"""
        ).fetchone()
        last = db.execute("""SELECT receipt FROM requests WHERE id=(
            SELECT max(request_id) FROM observations WHERE status!='missing')""").fetchone()
        h.last_observation = stamp(last[0]) if last else None
        # Require both complementary final labels from the same fresh response.
        h.resolved = db.execute("""SELECT count(DISTINCT group_key) FROM (
            SELECT s.group_key FROM settlements s WHERE quality='binary' AND group_key IS NOT NULL
            AND s.request_id=(SELECT o.request_id FROM observations o WHERE o.ticker=s.ticker
                              AND o.status!='missing' ORDER BY o.id DESC LIMIT 1)
            GROUP BY s.group_key,s.request_id HAVING count(DISTINCT ticker)=2 AND
            count(DISTINCT result)=2)""").fetchone()[0]
        h.gap_slots = db.execute("SELECT coalesce(sum(slots),0) FROM gaps").fetchone()[0]
        # Include scheduled slots missed since a crash/stop before resume books them.
        if h.state != "running":
            elapsed_slots = min(
                c["max_slots"], int((min(now, c["deadline"]) - c["started"]) // c["interval_s"]) + 1
            )
            h.gap_slots += max(0, elapsed_slots - c["next_slot"])
        h.storage_bytes = sum(p.stat().st_size for p in root.glob(path.name + "*") if p.is_file())
    finally:
        db.close()
    return h
