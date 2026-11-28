"""Fresh anonymous REST reads. No redirects, credential discovery or response cache."""

import hashlib
import http.client
import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode

from .store import Halt

HOST = "api.elections.kalshi.com"
SERIES = "KXNBAGAME"
SYMBOL = re.compile(r"KXNBAGAME-[A-Z0-9]{1,64}-[A-Z0-9]{1,20}")


def resource(method: str, host: str, path: str, params: dict[str, str]) -> str:
    valid = method == "GET" and host == HOST
    if path == "/series/" + SERIES:
        valid &= not params
    elif path == "/events":
        valid &= (
            set(params)
            == {"series_ticker", "limit", "min_close_ts", "with_nested_markets", "with_milestones"}
            and params["series_ticker"] == SERIES
            and params["limit"] == "100"
            and params["min_close_ts"].isdigit()
            and params["with_nested_markets"] == params["with_milestones"] == "true"
        )
    elif path == "/markets":
        ids = params.get("tickers", "").split(",")
        valid &= (
            set(params) == {"tickers"} and len(ids) <= 64 and all(SYMBOL.fullmatch(s) for s in ids)
        )
    else:
        valid = False
    if not valid:
        raise Halt("destination rejected")
    return "/trade-api/v2" + path + ("?" + urlencode(params) if params else "")


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes
    retry: str = ""
    error: str = ""


def https_get(path: str, params: dict[str, str], cap: int, timeout: float) -> Reply:
    uri = resource("GET", HOST, path, params)
    limit = time.monotonic() + timeout
    conn = http.client.HTTPSConnection(HOST, timeout=timeout)
    try:
        conn.request(
            "GET",
            uri,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
                "User-Agent": "Andromeda-local-observer/1",
            },
        )
        with conn.getresponse() as r:
            retry = r.getheader("Retry-After", "") or ""
            if r.getheader("Content-Encoding", "identity") != "identity":
                return Reply(r.status, b"", retry, "unexpected encoding")
            size = r.getheader("Content-Length")
            if size and (not size.isdigit() or int(size) > cap):
                return Reply(r.status, b"", retry, "response exceeds allowance")
            body = bytearray()
            while len(body) < cap:
                remaining = limit - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                if conn.sock is not None:
                    conn.sock.settimeout(min(timeout, remaining))
                chunk = r.read1(min(cap - len(body), 65536))
                if not chunk:
                    break
                body.extend(chunk)
            if (size and len(body) != int(size)) or (not size and len(body) == cap):
                return Reply(r.status, bytes(body), retry, "incomplete response")
            return Reply(r.status, bytes(body), retry)
    finally:
        conn.close()


class FetchError(Exception):
    pass


class Client:
    def __init__(
        self,
        db: sqlite3.Connection,
        send: Callable[[str, dict[str, str], int, float], Reply] = https_get,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.db, self.send, self.clock, self.monotonic, self.sleep = (
            db,
            send,
            clock,
            monotonic,
            sleep,
        )
        self.last_end = float("-inf")

    def get(self, slot: int, path: str, **params: str) -> tuple[int, float, dict[str, Any]]:
        resource("GET", HOST, path, params)
        c = self.db.execute("SELECT * FROM campaign").fetchone()
        count, used, last = self.db.execute(
            "SELECT count(*),coalesce(sum(charged),0),max(coalesce(receipt,sent)) FROM requests"
        ).fetchone()
        room = min(2 << 20, c["max_bytes"] - used)
        if count >= c["max_requests"] or room <= 0:
            raise Halt("request budget" if count >= c["max_requests"] else "byte budget")
        now = self.clock()
        if c["not_before"] > now:
            raise FetchError("provider backoff")
        wait = max(0.0, (last or 0) + 1.05 - now, self.last_end + 1.05 - self.monotonic())
        if now + wait >= c["deadline"]:
            raise Halt("deadline")
        if wait:
            self.sleep(wait)
        sent = self.clock()
        if (
            sent >= c["deadline"]
            or self.db.execute("SELECT stop_requested FROM campaign").fetchone()[0]
        ):
            raise Halt("deadline" if sent >= c["deadline"] else "operator stop")
        with self.db:
            insert = self.db.execute(
                """INSERT INTO requests(slot,path,query,sent,charged)
                 VALUES(?,?,?,?,?)""",
                (slot, path, urlencode(params), sent, room),
            )
        assert insert.lastrowid is not None
        rid = insert.lastrowid
        sent = self.clock()
        if sent >= c["deadline"]:
            with self.db:
                self.db.execute(
                    "UPDATE requests SET charged=0, error='deadline before dispatch' WHERE id=?",
                    (rid,),
                )
            raise Halt("deadline")
        begin = self.monotonic()
        try:
            reply = self.send(path, params, room, min(15.0, c["deadline"] - sent))
            charge = len(reply.body)
        except (OSError, http.client.HTTPException):
            reply, charge = Reply(0, b"", error="transport error"), room
        self.last_end = self.monotonic()
        received = self.clock()
        err = reply.error or ("" if reply.status == 200 else f"HTTP {reply.status}")
        if received < sent:
            err = "UTC clock moved backward"
        data: Any = None
        if not err:
            try:
                data = json.loads(reply.body)
                if not isinstance(data, dict):
                    err = "invalid object"
            except (ValueError, UnicodeError, RecursionError):
                err = "invalid JSON"
        with self.db:
            self.db.execute(
                """UPDATE requests SET sent=?,receipt=?,duration=?,status=?,charged=?,received=?,
              sha=?,body=?,error=? WHERE id=?""",
                (
                    sent,
                    received,
                    self.last_end - begin,
                    reply.status,
                    charge,
                    len(reply.body),
                    hashlib.sha256(reply.body).hexdigest(),
                    reply.body,
                    err or None,
                    rid,
                ),
            )
            if reply.status in (429, 503):
                try:
                    delay = (
                        float(int(reply.retry))
                        if reply.retry.isdigit()
                        else (parsedate_to_datetime(reply.retry).timestamp() - received)
                    )
                except (TypeError, ValueError, OverflowError):
                    delay = 60.0
                self.db.execute("UPDATE campaign SET not_before=?", (received + max(60.0, delay),))
        if reply.status in (401, 403) or 300 <= reply.status < 400:
            raise Halt(f"HTTP {reply.status}")
        if err:
            raise FetchError(err)
        return rid, received, data
