"""Frozen cohort frame, provenance-aware routes and deterministic acquisition/replay."""

import calendar
import json
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .a3_transport import TOKEN, Stop, pages

PLAN = json.loads(Path(__file__).with_name("a3_plan.json").read_text(encoding="utf-8"))


def instant(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, OverflowError):
        return None


def number(value):
    if (
        not isinstance(value, str)
        or len(value) > 32
        or not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value)
    ):
        return None
    try:
        d = Decimal(value)
        return d if d.is_finite() else None
    except InvalidOperation:
        return None


def settlement(m):
    status, result = m.get("status"), m.get("result")
    if status in ("voided", "canceled", "cancelled") or result in ("void", "voided", "cancelled"):
        return "void", None
    if result == "scalar" or m.get("market_type") == "scalar":
        return "nonbinary", None
    if status not in ("settled", "finalized"):
        return (
            "unresolved"
            if status
            in ("active", "open", "inactive", "closed", "determined", "initialized", "unopened")
            else "ambiguous"
        ), None
    value, nominal = (
        number(m.get("settlement_value_dollars")),
        number(m.get("notional_value_dollars")),
    )
    if (
        m.get("market_type") != "binary"
        or result not in ("yes", "no")
        or nominal is None
        or nominal <= 0
        or instant(m.get("settlement_ts")) is None
    ):
        return "ambiguous", None
    if value != (nominal if result == "yes" else Decimal(0)):
        return "inconsistent", None
    return "final_binary", int(result == "yes")


def event_day(series, event):
    if not isinstance(event, str):
        return None
    match = re.fullmatch(re.escape(series) + r"-(\d{2})([A-Z]{3})(\d{2})[A-Z0-9]*", event)
    if match:
        try:
            return date(
                2000 + int(match[1]),
                list(calendar.month_abbr).index(match[2].title()),
                int(match[3]),
            )
        except ValueError:
            pass
    return None


def deduplicate(records, key):
    unique, conflicts, duplicates, missing = {}, set(), 0, 0
    for row in records:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity:
            missing += 1
        elif identity in unique:
            if row == unique[identity]:
                duplicates += 1
            else:
                conflicts.add(identity)
        else:
            unique[identity] = row
    for identity in conflicts:
        del unique[identity]
    return unique, conflicts, duplicates, missing


def spread(values, n):
    if len(values) <= n:
        return values
    return [values[i * (len(values) - 1) // (n - 1)] for i in range(n)] if n > 1 else values[:1]


def candle_path(series, ticker, settle, boundary, archived):
    old = settle < boundary if settle is not None else archived
    return (
        f"/historical/markets/{ticker}/candlesticks"
        if old
        else f"/series/{series}/markets/{ticker}/candlesticks"
    )


def trade_routes(start, end, boundary):
    pivot = int(boundary.timestamp())
    routes = []
    if start <= pivot:
        routes.append(("/historical/trades", start, min(end, pivot)))
    if end >= pivot:
        routes.append(("/markets/trades", max(start, pivot), end))
    return routes


def scan(api, path, field, params, max_pages):
    rows = []
    try:
        for batch in pages(api.get, path, field, params, max_pages):
            rows.extend(batch)
    except Stop as exc:
        return rows, str(exc)
    return rows, "terminal_cursor"


def census(api, cfg):
    series = cfg["series"]
    first = datetime.fromisoformat(cfg["start"]).replace(tzinfo=UTC)
    end = datetime.fromisoformat(cfg["end"]).replace(tzinfo=UTC)
    params = {"series_ticker": series, "limit": 100}
    old, old_status = scan(api, "/historical/markets", "markets", params, 3)
    live, live_status = scan(
        api,
        "/markets",
        "markets",
        {
            **params,
            "min_close_ts": int((first - timedelta(days=14)).timestamp()),
            "max_close_ts": int((end + timedelta(days=14)).timestamp()),
        },
        3,
    )
    records, clashes, duplicates, missing = deduplicate(old + live, "ticker")
    window_pairs = set()
    for row in old + live:
        event, ticker = row.get("event_ticker"), row.get("ticker")
        day = event_day(series, event)
        if day and first.date() <= day < end.date() and isinstance(ticker, str):
            window_pairs.add((event, ticker))
    groups = {}
    invalid = 0
    for ticker, row in records.items():
        event = row.get("event_ticker")
        day = event_day(series, event)
        if not day or not re.fullmatch(TOKEN, ticker) or not ticker.startswith(event + "-"):
            invalid += 1
        elif first.date() <= day < end.date():
            groups.setdefault(event, []).append(row)
    diag = {
        "frame_settlement_classes": dict(
            Counter(settlement(m)[0] for siblings in groups.values() for m in siblings)
        ),
        "archive_pagination": old_status,
        "live_pagination": live_status,
        "archive_rows_scanned": len(old),
        "live_rows_scanned": len(live),
        "window_events_before_quarantine": len({e for e, _ in window_pairs}),
        "window_tickers_before_quarantine": len({t for _, t in window_pairs}),
        "discovered_exchange_events": len(groups),
        "discovered_contracts": sum(map(len, groups.values())),
        "frame_duplicates": duplicates,
        "frame_conflicts": len(clashes),
        "frame_missing_id": missing,
        "frame_unrecognized_identity": invalid,
    }
    return groups, {r.get("ticker") for r in old}, diag


def attempt(api, path, **params):
    try:
        return api.get(path, **params), "ok"
    except Stop as exc:
        return {}, str(exc)


def collect(api):
    configs = list(PLAN["cohorts"].values())
    if (
        not 1 <= len(configs) <= 3
        or any(
            type(c[k]) is not int or c[k] < 1
            for c in configs
            for k in ("groups", "contracts_per_group")
        )
        or sum(c["groups"] for c in configs) > min(150, PLAN["max_target_events"])
        or sum(c["groups"] * c["contracts_per_group"] for c in configs)
        > min(300, PLAN["max_target_contracts"])
    ):
        raise Stop("invalid_target_budget")
    api.bind("frozen_plan", PLAN)
    api.phase = "campaign"
    cutoff = api.get("/historical/cutoff")
    market_boundary = instant(cutoff.get("market_settled_ts"))
    trade_boundary = instant(cutoff.get("trades_created_ts"))
    if market_boundary is None or trade_boundary is None:
        raise Stop("missing_archive_cutoffs")
    packets, diagnostics = [], {}
    for cohort, cfg in PLAN["cohorts"].items():
        series = cfg["series"]
        series_obj, series_status = attempt(api, f"/series/{series}")
        frame, archived, diag = census(api, cfg)
        diagnostics[cohort] = diag
        diag["series_metadata"] = series_status
        order = sorted(frame, key=lambda e: (event_day(series, e), e))
        for event in spread(order, cfg["groups"]):
            meta, meta_status = attempt(api, f"/events/{event}")
            pool = sorted(frame[event], key=lambda r: r["ticker"])
            # Exact-event lists also test the boundary and sibling completeness.
            siblings = []
            enumeration = []
            for path in ("/historical/markets", "/markets"):
                rows, status = scan(api, path, "markets", {"event_ticker": event, "limit": 100}, 1)
                siblings.extend(rows)
                enumeration.append(status)
            roster, conflicts, duplicates, missing = deduplicate(pool + siblings, "ticker")
            event_packet = {
                "cohort": cohort,
                "series": series,
                "event": event,
                "day": event_day(series, event).isoformat(),
                "event_obj": meta.get("event"),
                "series_obj": series_obj.get("series"),
                "event_status": meta_status,
                "roster": list(roster),
                "enumeration": enumeration,
                "roster_conflicts": len(conflicts),
                "roster_duplicates": duplicates,
                "roster_missing": missing,
                "markets": [],
            }
            for i, m in enumerate(pool[: cfg["contracts_per_group"]]):
                symbol = m["ticker"]
                packet = {
                    "market": m,
                    "candles": {},
                    "candle_status": "missing_open",
                    "trades": [],
                    "trade_scan": [],
                    "trade_target": i == 0,
                }
                event_packet["markets"].append(packet)
                opened = instant(m.get("open_time"))
                if not opened:
                    continue
                start = int(opened.timestamp())
                end = int(
                    (opened + timedelta(minutes=PLAN["horizon_minutes_after_open"])).timestamp()
                )
                path = candle_path(
                    series,
                    symbol,
                    instant(m.get("settlement_ts")),
                    market_boundary,
                    symbol in archived,
                )
                packet["candles"], packet["candle_status"] = attempt(
                    api,
                    path,
                    start_ts=start,
                    end_ts=end,
                    period_interval=1,
                )
                packet["candle_path"] = path
                if i == 0:
                    for route, lo, hi in trade_routes(start, end, trade_boundary):
                        rows, status = scan(
                            api,
                            route,
                            "trades",
                            {
                                "ticker": symbol,
                                "min_ts": lo,
                                "max_ts": hi,
                                "limit": 100,
                            },
                            2,
                        )
                        packet["trades"].extend(rows)
                        packet["trade_scan"].append(status)
            packets.append(event_packet)
    return packets, diagnostics
