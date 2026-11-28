"""Normalize only contemporaneously received data. Raw documents remain in requests."""

import json
import re
import sqlite3
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from .transport import SERIES, SYMBOL, FetchError

Row = dict[str, Any]


def rows(value: object) -> list[Row]:
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise FetchError("invalid rows")
    return value


def timestamp(value: object) -> str | None:
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            return dt.astimezone(UTC).isoformat() if dt.tzinfo else None
        except (ValueError, OverflowError):
            pass
    return None


def event_day(event: object) -> date | None:
    if not isinstance(event, str) or not re.fullmatch(
        SERIES + r"-\d{2}[A-Z]{3}\d{2}[A-Z0-9]+", event
    ):
        return None
    try:
        return datetime.strptime(event[len(SERIES) + 1 : len(SERIES) + 8], "%y%b%d").date()
    except ValueError:
        return None


def group(event: str, ms: list[Row]) -> str | None:
    day = event_day(event)
    if day is None or len(ms) != 2:
        return None
    ids, sides = [], []
    for m in ms:
        ticker = m.get("ticker")
        rules = m.get("rules_primary")
        side = m.get("yes_sub_title")
        strike = m.get("custom_strike")
        if (
            not isinstance(ticker, str)
            or not SYMBOL.fullmatch(ticker)
            or not ticker.startswith(event + "-")
            or m.get("event_ticker") != event
            or m.get("market_type") != "binary"
            or m.get("mve_selected_legs")
            or not isinstance(strike, dict)
            or not isinstance(rules, str)
            or not isinstance(side, str)
            or not side
        ):
            return None
        rules = rules.lower()
        if not all(x in rules for x in ("basketball", "win", side.lower())):
            return None
        month = day.strftime("%B").lower()
        if not re.search(
            rf"\b(?:{month}|{month[:3]})\.?\s+0?{day.day}(?:st|nd|rd|th)?,?\s+{day.year}\b", rules
        ):
            return None
        team = []
        for v in strike.values():
            if isinstance(v, str):
                try:
                    team.append(str(UUID(v)))
                except ValueError:
                    continue
        if len(team) != 1:
            return None
        ids.extend(team)
        sides.append(ticker.split("-")[-1])
    if (
        len(set(ids)) != 2
        or sides[0] == sides[1]
        or not event.endswith((sides[0] + sides[1], sides[1] + sides[0]))
    ):
        return None
    return "/".join([SERIES, day.isoformat(), *sorted(ids)])


def discover(db: sqlite3.Connection, rid: int, receipt: float, obj: Row) -> bool:
    events = rows(obj.get("events"))
    milestones = rows(obj.get("milestones", []))
    today = datetime.fromtimestamp(receipt, UTC).date()
    by_day: dict[date, list[str]] = defaultdict(list)
    by_event: dict[str, Row] = {}
    for e in events:
        symbol = e.get("event_ticker")
        day = event_day(symbol)
        if day and e.get("series_ticker") == SERIES and isinstance(symbol, str):
            by_event[symbol] = e
            if today <= day <= today + timedelta(days=1):
                by_day[day].append(symbol)
    for day, candidates in by_day.items():
        selected = {
            r[0] for r in db.execute("SELECT event FROM targets WHERE day=?", (day.isoformat(),))
        }
        for symbol in sorted(set(candidates) - selected)[: max(0, 2 - len(selected))]:
            db.execute("INSERT INTO targets VALUES(?,?,?)", (symbol, day.isoformat(), rid))
    for row in db.execute("SELECT event FROM targets"):
        event = row[0]
        if event not in by_event:
            continue
        e = by_event[event]
        markets = rows(e.get("markets") or [])
        key = group(event, markets) if e.get("mutually_exclusive") is True else None
        dates = set()
        for m in milestones:
            refs = [
                i
                for field in ("related_event_tickers", "primary_event_tickers")
                if isinstance(m.get(field), list)
                for i in m[field]
            ]
            if (
                m.get("type") == "basketball_game"
                and event in refs
                and (d := timestamp(m.get("start_date")))
            ):
                dates.add(d)
        schedule = next(iter(dates)) if len(dates) == 1 else None
        db.execute(
            """INSERT INTO metadata(request_id,event,group_key,schedule,schedule_state,rules)
                      VALUES(?,?,?,?,?,?)""",
            (
                rid,
                event,
                key,
                schedule,
                "reported" if schedule else "ambiguous" if dates else "missing",
                json.dumps(
                    {
                        "mutually_exclusive": e.get("mutually_exclusive"),
                        "settlement_sources": e.get("settlement_sources"),
                    }
                ),
            ),
        )
        for m in markets:
            ticker = m.get("ticker")
            if (
                isinstance(ticker, str)
                and SYMBOL.fullmatch(ticker)
                and ticker.startswith(event + "-")
            ):
                db.execute("INSERT OR IGNORE INTO roster VALUES(?,?)", (ticker, event))
    return bool(obj.get("cursor"))


PRICES = (
    "yes_bid_dollars",
    "yes_ask_dollars",
    "no_bid_dollars",
    "no_ask_dollars",
    "last_price_dollars",
)
COUNTS = ("yes_bid_size_fp", "yes_ask_size_fp", "volume_fp", "volume_24h_fp", "open_interest_fp")


def fixed(value: object) -> Decimal | None:
    if isinstance(value, str) and len(value) <= 32 and re.fullmatch(r"\d+(?:\.\d+)?", value):
        return Decimal(value)
    return None


def snapshot(m: Row) -> tuple[Row, str]:
    data: Row = {
        k: m.get(k)
        for k in (
            *PRICES,
            *COUNTS,
            "notional_value_dollars",
            "open_time",
            "close_time",
            "expected_expiration_time",
            "latest_expiration_time",
            "occurrence_datetime",
            "can_close_early",
            "rules_primary",
            "rules_secondary",
            "updated_time",
            "yes_sub_title",
            "custom_strike",
        )
    }
    flags = []
    nominal = fixed(data["notional_value_dollars"])
    for k in (*PRICES, *COUNTS):
        v = fixed(data[k])
        if data[k] is None:
            flags.append("missing_" + k)
        elif v is None or (k in PRICES and (not nominal or v > nominal)):
            flags.append("invalid_" + k)
    for side in ("yes", "no"):
        bid, ask = (fixed(data[f"{side}_{k}_dollars"]) for k in ("bid", "ask"))
        if bid is not None and ask is not None and bid > ask:
            flags.append("crossed_" + side)
    for k in ("yes_bid_size_fp", "yes_ask_size_fp"):
        if fixed(data[k]) == 0:
            flags.append("empty_" + k)
    data["actual_game_start"] = None
    return data, ",".join(flags) or "ok"


def observe(db: sqlite3.Connection, rid: int, receipt: float, obj: Row, tickers: list[str]) -> bool:
    batch = rows(obj.get("markets"))
    indexed: dict[str, list[Row]] = defaultdict(list)
    for m in batch:
        if isinstance(m.get("ticker"), str):
            indexed[m["ticker"]].append(m)
    owners = dict(db.execute("SELECT ticker,event FROM roster"))
    by_event: dict[str, list[str]] = defaultdict(list)
    for ticker in tickers:
        by_event[owners[ticker]].append(ticker)
    partial = bool(obj.get("cursor"))
    for event, expected in by_event.items():
        meta = db.execute(
            "SELECT id,group_key FROM metadata WHERE event=? ORDER BY id DESC LIMIT 1", (event,)
        ).fetchone()
        key = group(event, [m for t in expected for m in indexed[t]])
        if not meta or key != meta["group_key"]:
            key = None
        for ticker in expected:
            matches = indexed[ticker]
            if len(matches) != 1 or matches[0].get("event_ticker") != event:
                partial = True
                values: Row = {}
                status, quality = "missing", "absent" if not matches else "ambiguous identity"
            else:
                m = matches[0]
                values, quality = snapshot(m)
                raw_status = m.get("status")
                status = raw_status if isinstance(raw_status, str) else "unknown"
                if status in (
                    "settled",
                    "finalized",
                    "voided",
                    "cancelled",
                    "canceled",
                    "determined",
                ):
                    payout = fixed(m.get("settlement_value_dollars"))
                    nominal = fixed(m.get("notional_value_dollars"))
                    result = m.get("result")
                    settled_at = timestamp(m.get("settlement_ts"))
                    final = (
                        status in ("settled", "finalized")
                        and m.get("market_type") == "binary"
                        and result in ("yes", "no")
                        and nominal is not None
                        and nominal > 0
                        and settled_at is not None
                        and datetime.fromisoformat(settled_at).timestamp() <= receipt
                        and payout == (nominal if result == "yes" else Decimal(0))
                    )
                    db.execute(
                        "INSERT INTO settlements VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            rid,
                            event,
                            ticker,
                            key,
                            receipt,
                            settled_at,
                            str(payout) if payout is not None else None,
                            result if isinstance(result, str) else None,
                            "binary" if final else "unconfirmed",
                        ),
                    )
            db.execute(
                """INSERT INTO observations(request_id,event,ticker,metadata_id,group_key,status,snapshot,quality)
                          VALUES(?,?,?,?,?,?,?,?)""",
                (
                    rid,
                    event,
                    ticker,
                    meta["id"] if meta else None,
                    key,
                    status,
                    json.dumps(values),
                    quality,
                ),
            )
    return partial
