"""Local-only A3.0 response archive and finite, anonymous GET transport."""

import hashlib
import http.client
import json
import os
import re
import sqlite3
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

HOST = "api.elections.kalshi.com"
BASE = "/trade-api/v2"
ROOT = Path(__file__).resolve().parents[1] / "var/research/kalshi/a3_0"
REQUEST_LIMIT = 500
BYTE_LIMIT = 50 * 1024**2
RESPONSE_LIMIT = 2 * 1024**2
TOKEN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}"
ROUTES = {
    "/historical/cutoff": set(),
    "/historical/markets": {"limit", "cursor", "series_ticker", "event_ticker"},
    "/markets": {
        "limit",
        "cursor",
        "event_ticker",
        "series_ticker",
        "min_close_ts",
        "max_close_ts",
    },
    "/historical/trades": {"limit", "cursor", "ticker", "min_ts", "max_ts"},
    "/markets/trades": {"limit", "cursor", "ticker", "min_ts", "max_ts"},
    "/series/{id}": set(),
    "/events/{id}": set(),
    "/historical/markets/{id}/candlesticks": {"start_ts", "end_ts", "period_interval"},
    "/series/{id}/markets/{id}/candlesticks": {"start_ts", "end_ts", "period_interval"},
}


class Stop(Exception):
    """Only fixed diagnostic codes may cross the CLI output boundary."""


def endpoint(method, host, path, params):
    if method != "GET" or host != HOST:
        raise Stop("destination_or_method")
    for route, keys in ROUTES.items():
        if re.fullmatch(route.replace("{id}", TOKEN), path) and params.keys() <= keys:
            for key, value in params.items():
                pattern = (
                    r"[0-9]+"
                    if key
                    in {
                        "limit",
                        "min_close_ts",
                        "max_close_ts",
                        "min_ts",
                        "max_ts",
                        "start_ts",
                        "end_ts",
                        "period_interval",
                    }
                    else TOKEN
                )
                if key == "cursor":
                    if not isinstance(value, str) or not 0 < len(value) <= 4096:
                        raise Stop("invalid_cursor")
                elif not re.fullmatch(pattern, str(value)):
                    raise Stop("invalid_parameter")
            return route
    raise Stop("endpoint_not_allowed")


@contextmanager
def exchange(path, query):
    endpoint("GET", HOST, path, dict(parse_qsl(query, keep_blank_values=True)))
    conn = http.client.HTTPSConnection(HOST, timeout=20)
    try:
        conn.request(
            "GET",
            BASE + path + ("?" + query if query else ""),
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "Andromeda-A3.0-personal-research/1",
            },
        )
        with conn.getresponse() as response:
            yield response
    finally:
        conn.close()


@contextmanager
def exclusive(root):
    """OS releases the single-writer lock even if an acquisition is interrupted."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / "campaign.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Stop("campaign_in_use") from None
        yield


def utc(ts):
    return datetime.fromtimestamp(ts, UTC).isoformat()


def retry_delay(value, now):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            return 0


class Archive:
    def __init__(self, root, *, offline=False, send=exchange, clock=time.time, sleep=time.sleep):
        self.db = sqlite3.connect(root / "acquisition.sqlite")
        self.db.row_factory = sqlite3.Row
        self.offline, self.send, self.clock, self.sleep = offline, send, clock, sleep
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS attempts(
                id INTEGER PRIMARY KEY, route TEXT, path TEXT, query TEXT, phase TEXT,
                started REAL, ended REAL, wait_until REAL, status INTEGER, outcome TEXT,
                charged INTEGER, received INTEGER, sha256 TEXT, body BLOB);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        """)
        self.phase = "discovery"

    def bind(self, key, value):
        value = json.dumps(value, sort_keys=True)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, value))
        if self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()[0] != value:
            raise Stop("campaign_definition_changed")

    def get(self, path, **params):
        route = endpoint("GET", HOST, path, params)
        query = urlencode(sorted(params.items()))
        prior = self.db.execute(
            "SELECT * FROM attempts WHERE path=? AND query=? ORDER BY id", (path, query)
        ).fetchall()
        for row in prior:
            if row["outcome"] == "ok":
                if hashlib.sha256(row["body"]).hexdigest() != row["sha256"]:
                    raise Stop("archive_hash_mismatch")
                return json.loads(row["body"])
        if prior and prior[-1]["outcome"] not in ("pending", "transient"):
            raise Stop(prior[-1]["outcome"])
        if len(prior) >= 3:
            raise Stop("retry_exhausted")
        if self.offline:
            raise Stop("not_archived")
        if self.db.execute(
            "SELECT 1 FROM attempts WHERE route=? AND status IN (401,403)", (route,)
        ).fetchone():
            raise Stop("authorization_required")
        for retry in range(len(prior), 3):
            latest = self.db.execute(
                "SELECT max(max(coalesce(ended, started)+1.1, coalesce(wait_until,0))) FROM attempts"
            ).fetchone()[0]
            delay = max(0, (latest or 0) - self.clock())
            if delay > 60:
                raise Stop("provider_cooldown")
            if delay:
                self.sleep(delay)
            with self.db:
                count, used = self.db.execute(
                    "SELECT count(*),coalesce(sum(charged),0) FROM attempts"
                ).fetchone()
                room = min(BYTE_LIMIT - used, RESPONSE_LIMIT)
                if count >= REQUEST_LIMIT or room <= 0:
                    raise Stop("campaign_budget")
                attempt = self.db.execute(
                    """INSERT INTO attempts(route,path,query,phase,started,outcome,charged)
                       VALUES(?,?,?,?,?,'pending',?)""",
                    (route, path, query, self.phase, self.clock(), room),
                ).lastrowid
            # Reserve before I/O. A crash leaves the full reservation charged on resume.
            body = bytearray()
            status, cooldown, outcome = 0, 0.0, "transient"
            try:
                with self.send(path, query) as response:
                    status = response.status
                    if status == 429 or 500 <= status < 600:
                        cooldown = self.clock() + max(
                            2 ** (retry + 1),
                            retry_delay(response.getheader("Retry-After"), self.clock()),
                        )
                    length = response.getheader("Content-Length")
                    if response.getheader("Content-Encoding") not in (None, "", "identity"):
                        outcome = "unsupported_encoding"
                    elif length is not None and (not length.isdigit() or int(length) > room):
                        outcome = "size_or_length"
                    else:
                        while len(body) < room:
                            part = response.read(min(65536, room - len(body)))
                            if not part:
                                break
                            body.extend(part)
                        if length is not None and len(body) != int(length):
                            outcome = "transient"
                        elif len(body) == room and length is None:
                            outcome = "size_or_length"
                        elif status == 200:
                            try:
                                data = json.loads(body)
                                outcome = "ok" if isinstance(data, dict) else "malformed_object"
                            except (ValueError, UnicodeError, RecursionError):
                                outcome = "malformed_json"
                        elif 300 <= status < 400:
                            outcome = "redirect_rejected"
                        elif status in (401, 403):
                            outcome = "authorization_required"
                        elif status != 429 and not 500 <= status < 600:
                            outcome = "http_error"
            except (OSError, http.client.HTTPException):
                # Interrupted reads may have consumed unreported bytes.
                outcome = "transient"
                room_charge = room
                cooldown = max(cooldown, self.clock() + 2 ** (retry + 1))
            else:
                room_charge = len(body)
            with self.db:
                self.db.execute(
                    """UPDATE attempts SET ended=?,wait_until=?,status=?,outcome=?,charged=?,
                       received=?,sha256=?,body=? WHERE id=?""",
                    (
                        self.clock(),
                        cooldown,
                        status,
                        outcome,
                        room_charge,
                        len(body),
                        hashlib.sha256(body).hexdigest(),
                        bytes(body),
                        attempt,
                    ),
                )
            if outcome == "ok":
                return data
            if outcome != "transient":
                raise Stop(outcome)
        raise Stop("retry_exhausted")

    def receipts(self):
        receipts = []
        for row in self.db.execute(
            "SELECT id,route,query,phase,started,ended,received,charged,status,outcome,sha256 "
            "FROM attempts ORDER BY id"
        ):
            r = dict(row)
            r["parameters"] = {
                k: v
                if k not in ("cursor", "ticker", "event_ticker")
                else hashlib.sha256(v.encode()).hexdigest()
                for k, v in parse_qsl(r.pop("query"))
            }
            r["retrieved_utc"] = utc(r["ended"]) if r["ended"] else None
            receipts.append(r)
        return receipts

    def stats(self):
        rows = self.db.execute(
            "SELECT route,status,outcome,charged,received,started FROM attempts ORDER BY id"
        ).fetchall()
        return {
            "attempts": len(rows),
            "min_start_interval_seconds": round(
                min(
                    (b["started"] - a["started"] for a, b in zip(rows, rows[1:], strict=False)),
                    default=0,
                ),
                3,
            ),
            "received_bytes": sum(r["received"] or 0 for r in rows),
            "charged_bytes": sum(r["charged"] for r in rows),
            "http_status": dict(Counter(str(r["status"]) for r in rows)),
            "endpoints": dict(Counter(r["route"] for r in rows if r["outcome"] == "ok")),
            "errors": dict(Counter(r["outcome"] for r in rows if r["outcome"] != "ok")),
            "errors_by_endpoint": dict(
                Counter(
                    f"{r['route']} HTTP {r['status']} {r['outcome']}"
                    for r in rows
                    if r["outcome"] != "ok"
                )
            ),
        }


def pages(fetch: Callable, path, field, params, max_pages) -> Iterator[list]:
    seen = set()
    for _ in range(max_pages):
        obj = fetch(path, **params)
        rows = obj.get(field)
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise Stop("malformed_list")
        yield rows
        cursor = obj.get("cursor")
        if cursor == "":
            return
        if not isinstance(cursor, str) or not cursor:
            raise Stop("missing_cursor")
        if cursor in seen:
            raise Stop("repeated_cursor")
        seen.add(cursor)
        params = {**params, "cursor": cursor}
    raise Stop("page_cap")
