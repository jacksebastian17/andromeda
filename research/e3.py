"""Bounded E3 acquisition and outcome-blind feature preparation."""

import argparse
import hashlib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from .a3_data import candle_path, event_day, instant, number, scan, settlement
from .a3_transport import ROOT as A3
from .a3_transport import Archive, Stop, exclusive
from .e1 import REPO, digest, require
from .e1 import parse as parse_candles
from .observer.records import group

Row = dict[str, Any]

ROOT = REPO / "var/research/e3"
PROTOCOL = REPO / "docs/research/e3-protocol.md"
SERIES = "KXNBAGAME"
START, VALID, TEST, END = (
    date.fromisoformat(s) for s in ("2026-10-28", "2026-11-13", "2026-11-19", "2026-11-27")
)
CAPS = {"development": 108, "validation": 40, "test": 52}


def horizon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 10, tzinfo=UTC)


def partition(day: date) -> str:
    return "development" if day < VALID else "validation" if day < TEST else "test"


def previous_events(path: Path) -> set[str]:
    # Project only event identities; never load prior directional outcomes.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        return {
            r[0]
            for r in db.execute("""SELECT DISTINCT json_extract(m.value,'$.event_ticker')
            FROM attempts a, json_each(a.body,'$.markets') m
            WHERE a.outcome='ok' AND a.path IN ('/markets','/historical/markets')
            AND json_extract(m.value,'$.event_ticker') LIKE 'KXNBAGAME-%'
            UNION SELECT substr(path,9) FROM attempts WHERE path LIKE '/events/KXNBAGAME-%'""")
        }


def write(name: str, data: object) -> None:
    path = ROOT / name
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def frame(
    api: Archive,
) -> tuple[dict[str, dict[str, Row]], dict[str, list[str]], set[str], set[str], datetime, Row]:
    cutoff = instant(api.get("/historical/cutoff")["market_settled_ts"])
    require(cutoff, "missing tier boundary")
    params = {"series_ticker": SERIES, "limit": 100}
    early = int((horizon(START) - timedelta(days=7, hours=10)).timestamp())
    late = int((horizon(END) + timedelta(days=7, hours=-10)).timestamp())
    requests = [
        ("current", "/markets", params, 16),
        ("close_window", "/markets", {**params, "min_close_ts": early, "max_close_ts": late}, 12),
    ]
    if early <= cutoff.timestamp():
        requests.append(("archive", "/historical/markets", params, 12))
    pool: dict[str, dict[str, Row]] = defaultdict(dict)
    previous = previous_events(A3 / "acquisition.sqlite")
    excluded, clashes, historical = set(), set(), set()
    counts: Counter[str] = Counter()
    scans = {}
    for name, path, args, limit in requests:
        markets, status = scan(api, path, "markets", args, limit)
        scans[name] = {"pagination": status, "listed_contracts": len(markets)}
        for m in markets:
            event = m.get("event_ticker")
            day = event_day(SERIES, event)
            if day is None:
                counts["undated_rows"] += 1
                continue
            if not START <= day < END:
                continue
            if event in previous:
                excluded.add(event)
                continue
            ticker = m.get("ticker")
            sibling = pool[event]
            if not isinstance(ticker, str):
                clashes.add(event)
                continue
            if ticker in sibling:
                counts["duplicate_rows"] += 1
                # Listing snapshots may change. Quarantine material identity or rule changes.
                fields = (
                    "event_ticker",
                    "yes_sub_title",
                    "custom_strike",
                    "rules_primary",
                    "rules_secondary",
                    "open_time",
                    "notional_value_dollars",
                    "market_type",
                )
                if any(sibling[ticker].get(k) != m.get(k) for k in fields):
                    clashes.add(event)
            else:
                sibling[ticker] = m
            if name == "archive":
                historical.add(ticker)
    roster = {}
    for split, cap in CAPS.items():
        candidates = [e for e in pool if partition(event_day(SERIES, e)) == split]
        counts[split + "_frame"] = len(candidates)
        roster[split] = sorted(candidates, key=lambda e: hashlib.sha256(e.encode()).digest())[:cap]
    api.bind("roster", roster)
    return (
        pool,
        roster,
        clashes,
        historical,
        cutoff,
        {**counts, "a3_overlap_excluded": len(excluded), "scans": scans},
    )


def participant(market: Row) -> str:
    candidates = []
    for v in market["custom_strike"].values():
        if isinstance(v, str):
            try:
                candidates.append(str(UUID(v)))
            except ValueError:
                pass
    require(len(candidates) == 1, "ambiguous participant")
    return candidates[0]


def winner_identity(event: str, markets: list[Row]) -> str | None:
    key = group(event, markets)
    if not key:
        return None
    rules = []
    for m in markets:
        rule = " ".join(m["rules_primary"].casefold().split())
        side = m["yes_sub_title"].casefold()
        if (
            "basketball" not in rule
            or "game" not in rule
            or re.search(r"\b(?:quarter|half|unless|except|not)\b", rule)
        ):
            return None
        if not (
            rule.startswith("resolves yes if ")
            or re.search(r"\b(?:resolves?|settles?|pays?) (?:to |as )?yes\.?$", rule)
        ):
            return None
        for prefix in (f"if {side} wins ", f"resolves yes if {side} wins "):
            if rule.startswith(prefix):
                rules.append((rule[len(prefix) :], m.get("rules_secondary") or ""))
                break
    if len(rules) == 2 and rules[0] == rules[1]:
        return key
    return None


def quote(body: Row, ticker: str, decision: int, opened: float) -> tuple[Row | None, str]:
    bars, conflicts = parse_candles(body, ticker)
    if conflicts:
        return None, "conflicting_candle_end"
    window = [
        (end, bar)
        for end, bar in sorted(bars.items())
        if decision - 3600 <= end <= decision - 120 and end - 60 >= opened
    ]
    intervals = [(end, bar.interval) for end, bar in window if bar.interval is not None]
    if not intervals:
        return None, "no_valid_quote" if window else "no_completed_recent_bar"
    end, (bid, ask) = intervals[-1]
    trades = [(t, float(b.trade)) for t, b in window if b.trade is not None]
    return {
        "p": float((bid + ask) / 2),
        "spread": float(ask - bid),
        "age": decision - end,
        "trade": trades[-1][1] if trades else None,
        "trade_age": decision - trades[-1][0] if trades else None,
    }, "ok"


def binary_pair(markets: list[Row]) -> bool:
    # Discard participant order. Emit only whether the pair offers a usable binary label.
    return len(markets) == 2 and {settlement(m) for m in markets} == {
        ("final_binary", 0),
        ("final_binary", 1),
    }


def prepare(api: Archive) -> None:
    api.bind("protocol_sha256", digest(PROTOCOL.read_bytes().replace(b"\r\n", b"\n")))
    pool, roster, clashes, historical, cutoff, report = frame(api)
    keys = {
        event: winner_identity(event, list(pool[event].values()))
        for events in roster.values()
        for event in events
    }
    frequencies = Counter(keys.values())
    report["partitions"] = {}
    for split, events in roster.items():
        features, labels = [], {}
        exclusions: Counter[str] = Counter()
        statuses: Counter[str] = Counter()
        for event in sorted(events):
            markets = list(pool[event].values())
            statuses.update(m.get("status", "unknown") for m in markets)
            if event in clashes or not keys[event] or frequencies[keys[event]] != 1:
                exclusions["identity_or_rules"] += 1
                continue
            chosen, sibling = sorted(markets, key=participant)
            ticker = chosen["ticker"]
            day = event_day(SERIES, event)
            decision = horizon(day)
            opened, closed, settled, occurs = (
                instant(chosen.get(k))
                for k in ("open_time", "close_time", "settlement_ts", "occurrence_datetime")
            )
            if (
                not opened
                or not closed
                or not opened < decision < closed
                or any(
                    t is not None and t <= decision
                    for t in (
                        settled,
                        occurs,
                        instant(sibling.get("settlement_ts")),
                        instant(sibling.get("occurrence_datetime")),
                    )
                )
            ):
                exclusions["market_clock"] += 1
                continue
            if any(number(m.get("notional_value_dollars")) != 1 for m in markets):
                exclusions["notional"] += 1
                continue
            ts = int(decision.timestamp())
            path = candle_path(SERIES, ticker, settled, cutoff, ticker in historical)
            try:
                body = api.get(path, start_ts=ts - 3600, end_ts=ts - 120, period_interval=1)
            except Stop as exc:
                if str(exc) in (
                    "campaign_budget",
                    "provider_cooldown",
                    "authorization_required",
                    "not_archived",
                ):
                    raise
                exclusions["candle_" + str(exc)] += 1
                continue
            obs, reason = quote(body, ticker, ts, opened.timestamp())
            if obs is None:
                exclusions[reason] += 1
                continue
            if not binary_pair(markets):
                exclusions["unconfirmed_label"] += 1
                continue
            final_at = max(instant(m["settlement_ts"]) for m in markets)
            if split != "test" and final_at >= horizon(
                VALID if split == "development" else TEST
            ) - timedelta(hours=1):
                exclusions["boundary_purge"] += 1
                continue
            features.append({**obs, "day": day.isoformat(), "event": event})
            # Opaque label packets by partition. Only the scoring stage interprets direction.
            fields = (
                "market_type",
                "status",
                "result",
                "settlement_value_dollars",
                "notional_value_dollars",
                "settlement_ts",
            )
            labels[event] = [{k: m.get(k) for k in fields} for m in (chosen, sibling)]
        write(split + "-features.json", features)
        write(split + "-labels.json", labels)
        report["partitions"][split] = {
            "selected": len(events),
            "eligible_features": len(features),
            "days": len({r["day"] for r in features}),
            "exclusions": dict(exclusions),
            "sibling_status": dict(statuses),
        }
    report["requests"] = api.stats()
    write("coverage.json", report)
    print(json.dumps(report))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("collect", "replay"))
    action = parser.parse_args().action
    if os.environ.get("GITHUB_ACTIONS") == "true":
        raise Stop("local_campaign_only")
    with exclusive(ROOT):
        api = Archive(ROOT, offline=action == "replay")
        try:
            prepare(api)
        finally:
            api.db.close()


if __name__ == "__main__":
    main()
