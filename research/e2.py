"""One E1 closeout and a local feasibility audit for NOAA temperature guidance."""

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from itertools import groupby, pairwise
from pathlib import Path
from typing import Any

from research.e1 import (
    REPO,
    ROOT,
    AuditError,
    Interval,
    archived,
    digest,
    price,
    require,
    signed_gap,
)

PRIVATE = REPO / "var/research/e2"
CUTOFF = datetime(2026, 11, 28, 6, 44, tzinfo=UTC)
Row = dict[str, Any]


def population() -> tuple[Row, list[Row]]:
    data = (ROOT / "normalized/development/features.jsonl").read_bytes()
    rows = [json.loads(line) for line in data.splitlines()]
    require(all(r["partition"] == "development" for r in rows), "unexpected partition")
    weather = [r for r in rows if r["series"] == "KXHIGHNY" and r["cohort"] == "weather"]
    groups: dict[str, list[str]] = defaultdict(list)
    for r in weather:
        groups[r["day"]].append(r["contract"])
    require(
        len(groups) == 6 and all(len(set(v)) == len(v) == 6 for v in groups.values()),
        "unexpected development population",
    )
    return {
        "feature_sha256": digest(data),
        "days": {k: sorted(v) for k, v in groups.items()},
        "nba_receipt_cutoff": CUTOFF.isoformat(),
    }, weather


def readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def interval_pair(rows: list[sqlite3.Row], receipt: float) -> list[Interval] | None:
    """Both active records in one successful response, under matching winner rules."""
    if len(rows) != 2 or rows[0]["ticker"] == rows[1]["ticker"]:
        return None
    intervals, rules = [], []
    for row in rows:
        if row["status"] != "active" or row["quality"] != "ok":
            return None
        m = json.loads(row["snapshot"])
        if not (
            datetime.fromisoformat(m["open_time"]).timestamp()
            <= receipt
            < datetime.fromisoformat(m["close_time"]).timestamp()
        ):
            return None
        bid, ask, bid_size, ask_size, nominal = (
            Decimal(m[k])
            for k in (
                "yes_bid_dollars",
                "yes_ask_dollars",
                "yes_bid_size_fp",
                "yes_ask_size_fp",
                "notional_value_dollars",
            )
        )
        if not (0 < bid <= ask < nominal == 1 and min(bid_size, ask_size) > 0):
            return None
        side = m["yes_sub_title"].casefold()
        rule = " ".join(m["rules_primary"].casefold().split())
        match = re.match(r"(?:if |resolves yes if )" + re.escape(side) + r" wins (.+)", rule)
        if not match or "basketball" not in rule:
            return None
        rules.append((match[1], m.get("rules_secondary") or ""))
        intervals.append((bid, ask))
    return intervals if rules[0] == rules[1] else None


def closeout(paths: list[Path]) -> Row:
    schedules: dict[str, list[tuple[float, str | None]]] = defaultdict(list)
    batches = []
    for path in paths:
        if not path.exists():
            continue
        with closing(readonly(path)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            for r in db.execute(
                """SELECT event,schedule,r.receipt FROM metadata m
                JOIN requests r ON r.id=m.request_id WHERE r.receipt<=? ORDER BY r.receipt""",
                (CUTOFF.timestamp(),),
            ):
                schedules[r["event"]].append((r["receipt"], r["schedule"]))
            data = db.execute(
                """SELECT o.*, r.receipt FROM observations o JOIN requests r
                ON r.id=o.request_id WHERE r.receipt<=? AND r.status=200 AND r.error IS NULL
                ORDER BY o.request_id,o.event""",
                (CUTOFF.timestamp(),),
            )
            for (_, event), records in groupby(data, lambda r: (r["request_id"], r["event"])):
                rows = list(records)
                batches.append((event, rows[0]["receipt"], rows))
    counts = Counter(same_response_event_batches=len(batches))
    games, gaps = set(), []
    for event, receipt, rows in batches:
        key = rows[0]["group_key"]
        if not key or any(r["group_key"] != key for r in rows):
            continue
        known = [s for t, s in sorted(schedules[event], key=lambda x: x[0]) if t <= receipt]
        if not known or known[0] is None or len(set(known)) != 1:
            continue
        decision = datetime.fromisoformat(known[0]).timestamp() - 3600
        if receipt > decision:
            continue
        counts["before_decision"] += 1
        intervals = interval_pair(rows, receipt)
        if intervals:
            games.add(key)
            gaps.append(intervals)
            counts["within_six_minutes"] += receipt >= decision - 360
    qualified = len(gaps) >= 30 and len(games) >= 4
    return {
        **counts,
        "eligible_pairs": len(gaps),
        "eligible_games": len(games),
        "gross_gaps": sum(signed_gap(*p) != 0 for p in gaps) if qualified else None,
    }


def bracket(m: Row) -> tuple[int | None, int | None]:
    kind, lo, hi = m["strike_type"], m.get("floor_strike"), m.get("cap_strike")
    if kind == "less" and lo is None and type(hi) is int:
        return None, hi - 1
    if kind == "greater" and hi is None and type(lo) is int:
        return lo + 1, None
    if kind == "between" and type(lo) is type(hi) is int and lo <= hi:
        return lo, hi
    raise AuditError("unrecognized settlement bracket")


def settlement(rows: list[Row]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    with closing(readonly(ROOT / "acquisition.sqlite")) as db:
        series = archived(db, "/series/KXHIGHNY")["series"]
        require(
            series["ticker"] == "KXHIGHNY"
            and series["contract_terms_url"].endswith("/contract_terms/GLOBALTEMPERATURE.pdf"),
            "unrecognized settlement terms",
        )
        for event, members in groupby(
            sorted(rows, key=lambda r: r["exchange_event"]), lambda r: r["exchange_event"]
        ):
            group = list(members)
            allowed = {r["contract"] for r in group}
            metadata = archived(db, "/events/" + event)["event"]
            require(
                metadata["series_ticker"] == "KXHIGHNY" and metadata["event_ticker"] == event,
                "weather event mismatch",
            )
            require(
                any(s["name"] == "The Weather Company" for s in metadata["settlement_sources"]),
                "unexpected weather source",
            )
            bins: dict[str, tuple[tuple[int | None, int | None], str]] = {}
            for endpoint in ("/historical/markets", "/markets"):
                response = archived(db, endpoint, event_ticker=event, limit=100)
                require(not response["cursor"], "incomplete weather event")
                for m in response["markets"]:
                    require(
                        m["ticker"] in allowed and m["event_ticker"] == event, "unexpected sibling"
                    )
                    rules = m["rules_primary"].lower()
                    require(
                        all(
                            word in rules
                            for word in (
                                "new york city (clinyc)",
                                "maximum",
                                "fahrenheit",
                                "according to the weather company",
                            )
                        ),
                        "different station, target or source",
                    )
                    operator = {
                        "less": "less than",
                        "greater": "greater than",
                        "between": "between",
                    }[m["strike_type"]]
                    bounds = [
                        str(n)
                        for n in (m.get("floor_strike"), m.get("cap_strike"))
                        if n is not None
                    ]
                    require(
                        operator in rules
                        and re.findall(r"\d+", rules.split(operator)[-1].split("fahrenheit")[0])
                        == bounds,
                        "published predicate differs from strike",
                    )
                    item = (bracket(m), rules)
                    require(bins.get(m["ticker"], item) == item, "conflicting weather terms")
                    bins[m["ticker"]] = item
            require(set(bins) == allowed, "missing weather bracket")
            ordered = sorted(
                (bounds for bounds, _ in bins.values()), key=lambda b: (b[0] is not None, b[0] or 0)
            )
            require(
                ordered[0][0] is None
                and ordered[-1][1] is None
                and all(
                    left[1] is not None and right[0] == left[1] + 1
                    for left, right in pairwise(ordered)
                ),
                "incomplete integer partition",
            )
            counts["complete_days"] += 1
            counts["verified_clinyc_predicates"] += len(bins)
            for r in group:
                if r["proxy_eligible"]:
                    counts["eligible_market_closes"] += price(r["price_dollars"]) is not None
                    bid, ask = (
                        price(r["bid_candle_close_dollars"]),
                        price(r["ask_candle_close_dollars"]),
                    )
                    counts["eligible_two_sided"] += (
                        bid is not None and ask is not None and bid <= ask
                    )
    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "closeout", "audit"))
    action = parser.parse_args().action
    frozen, rows = population()
    path = PRIVATE / "population.json"
    if action == "freeze":
        PRIVATE.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf8") as f:
            json.dump(frozen, f, indent=2)
        print("Six development days frozen.")
        return
    require(json.loads(path.read_text()) == frozen, "frozen inputs changed")
    if action == "closeout":
        # Exclusive creation also prevents a later run from re-examining market prices.
        with (PRIVATE / "closeout.json").open("x", encoding="utf8") as f:
            result = closeout([ROOT.parent / "a3_1" / (m + ".sqlite") for m in ("smoke", "pilot")])
            json.dump(result, f)
    else:
        result = {
            "e1": json.loads((PRIVATE / "closeout.json").read_text()),
            "weather": settlement(rows),
        }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
