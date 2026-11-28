"""Outcome-blind offline comparison of the six frozen NBA development pairs."""

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode
from uuid import UUID

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "var/research/kalshi/a3_0"
PROTOCOL = REPO / "docs/research/e1-protocol.md"
SERIES = "KXNBAGAME"
ONE = Decimal(1)
CENT = Decimal("0.01")
FEES = tuple(map(Decimal, ("0", "0.035", "0.07", "0.14")))
Row = dict[str, Any]
Interval = tuple[Decimal, Decimal]


class AuditError(Exception):
    """An input failed a check. Messages must contain no market data."""


def require(condition: object, reason: str) -> None:
    if not condition:
        raise AuditError(reason)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def development(root: Path) -> tuple[str, list[list[Row]]]:
    body = (root / "normalized/development/features.jsonl").read_bytes()
    selected: dict[str, list[Row]] = defaultdict(list)
    for line in body.splitlines():
        row = json.loads(line)
        require(row["partition"] == "development", "unexpected partition")
        if row["series"] == SERIES and row["cohort"] == "nba" and row["proxy_eligible"] is True:
            require(row["underlying_event"], "missing development game identity")
            selected[row["underlying_event"]].append(row)
    pairs = [
        sorted(group, key=lambda row: row["contract"])
        for _, group in sorted(selected.items())
        if len(group) == 2
    ]
    tickers = {row["contract"] for pair in pairs for row in pair}
    require(len(pairs) == 6 and len(tickers) == 12, "unexpected development whitelist")
    return digest(body), pairs


def archived(db: sqlite3.Connection, path: str, **query: int | str) -> Row:
    records = db.execute(
        """SELECT body,sha256 FROM attempts
           WHERE path=? AND query=? AND status=200 AND outcome='ok'""",
        (path, urlencode(sorted(query.items()))),
    ).fetchall()
    require(len(records) == 1, "missing or ambiguous archived response")
    body, sha = records[0]
    require(digest(body) == sha, "archive hash mismatch")
    return cast(Row, json.loads(body))


def decimal(value: object) -> Decimal | None:
    if type(value) in (str, int):
        try:
            result = Decimal(str(value))
            if result.is_finite():
                return result
        except InvalidOperation:
            pass
    return None


def price(value: object) -> Decimal | None:
    result = decimal(value)
    return result if result is not None and 0 <= result <= ONE else None


def epoch(value: str) -> int:
    stamp = datetime.fromisoformat(value)
    require(stamp.tzinfo is not None and stamp.microsecond == 0, "invalid window clock")
    return int(stamp.timestamp())


def verify_rules(event: Row, features: list[Row], markets: list[Row]) -> bool:
    event_id = features[0]["exchange_event"]
    require(
        event["event_ticker"] == event_id
        and event["series_ticker"] == SERIES
        and event["mutually_exclusive"] is True
        and event.get("settlement_sources"),
        "invalid event rules",
    )
    teams, predicates, names, codes = [], [], [], []
    for feature, market in zip(features, markets, strict=True):
        name = market["yes_sub_title"].casefold()
        ticker = market["ticker"]
        code = ticker.removeprefix(event_id + "-")
        day = datetime.fromisoformat(feature["day"])
        rule = " ".join(market["rules_primary"].casefold().split())
        prefix = f"if {name} wins "
        require(
            name
            and feature["exchange_event"] == market["event_ticker"] == event_id
            and feature["contract"] == ticker
            and ticker.startswith(event_id + "-")
            and re.fullmatch(r"[A-Z0-9]+", code)
            and market["market_type"] == "binary"
            and not market.get("mve_collection_ticker")
            and not market.get("mve_selected_legs")
            and decimal(market["notional_value_dollars"])
            == decimal(feature["notional_dollars"])
            == ONE
            and feature["open"] == market["open_time"]
            and rule.startswith(prefix)
            and "basketball" in rule
            and "originally scheduled" in rule
            and not re.search(r"\b(?:unless|except|not|half|quarter)\b", rule)
            and re.search(r"\b(?:resolves?|settles?|pays?) (?:to |as )?yes\.?$", rule)
            and re.search(
                rf"\b(?:{day:%b}|{day:%B})\.? 0?{day.day}(?:st|nd|rd|th)?,? {day.year}\b",
                rule,
                re.IGNORECASE,
            ),
            "unverified winner predicate or notional",
        )
        strike = market["custom_strike"]
        require(isinstance(strike, dict), "missing participant identity")
        uuids = []
        for value in strike.values():
            if isinstance(value, str):
                try:
                    uuids.append(str(UUID(value)))
                except ValueError:
                    pass
        require(len(uuids) == 1, "ambiguous participant identity")
        teams.extend(uuids)
        predicates.append(rule.removeprefix(prefix))
        names.append(name)
        codes.append(code)
    a, b = codes
    feature = features[0]
    expected = "/".join([SERIES, feature["day"], *sorted(teams)])
    secondary = [(market.get("rules_secondary") or "").casefold() for market in markets]
    require(
        event_id.startswith(
            SERIES + datetime.fromisoformat(feature["day"]).strftime("-%y%b%d").upper()
        )
        and event_id.endswith((a + b, b + a))
        and len(set(teams)) == len(set(names)) == len(set(codes)) == 2
        and predicates[0] == predicates[1]
        and secondary[0] == secondary[1]
        and all(row["underlying_event"] == expected for row in features),
        "mismatched complementary rules or game identity",
    )
    return all(word in secondary[0] for word in ("cancel", "postpon", "fair price"))


@dataclass(frozen=True)
class Bar:
    interval: Interval | None
    envelope: Interval | None
    trade: Decimal | None


def quotes(bid: Decimal | None, ask: Decimal | None) -> Interval | None:
    if bid is not None and ask is not None and 0 < bid <= ask < ONE:
        return bid, ask
    return None


def value(row: Row, key: str, point: str) -> Decimal | None:
    series = row.get(key)
    if isinstance(series, dict):
        return price(series.get(point + "_dollars", series.get(point)))
    return None


def parse(body: Row, ticker: str) -> tuple[dict[int, Bar], set[int]]:
    require(
        body.get("ticker") == ticker and isinstance(body.get("candlesticks"), list),
        "invalid candle response",
    )
    rows: dict[int, Row] = {}
    conflicts = set()
    for row in body["candlesticks"]:
        end = row.get("end_period_ts")
        require(type(end) is int and end % 60 == 0, "invalid UTC minute end")
        if end in rows and rows[end] != row:
            conflicts.add(end)
        rows[end] = row
    bars = {}
    for end in rows.keys() - conflicts:
        row = rows[end]
        interval = quotes(value(row, "yes_bid", "close"), value(row, "yes_ask", "close"))
        envelope = quotes(value(row, "yes_bid", "low"), value(row, "yes_ask", "high"))
        if not (interval and envelope and envelope[0] <= interval[0] <= interval[1] <= envelope[1]):
            envelope = None
        volume = decimal(row.get("volume_fp", row.get("volume")))
        trade = value(row, "price", "close") if volume is not None and volume > 0 else None
        bars[end] = Bar(interval, envelope, trade)
    return bars, conflicts


def grid(opened: int, cutoff: int, lag: int) -> range:
    return range(((opened + 119) // 60) * 60, cutoff - lag + 1, 60)


def signed_gap(a: Interval, b: Interval) -> Decimal:
    low, high = a[0] + b[0], a[1] + b[1]
    return low - ONE if low > ONE else min(high - ONE, Decimal(0))


def gap_after_fees(a: Interval, b: Interval, rate: Decimal) -> Decimal:
    gap = signed_gap(a, b)
    if not gap:
        return Decimal(0)
    prices = (a[0], b[0]) if gap > 0 else (a[1], b[1])
    costs = sum((rate * p * (ONE - p)).quantize(CENT, rounding=ROUND_CEILING) for p in prices)
    return max(Decimal(0), abs(gap) - costs)


@dataclass
class Series:
    counts: Counter[str] = field(default_factory=Counter)
    absolute: dict[str, list[Decimal]] = field(default_factory=lambda: defaultdict(list))
    stable: bool = False

    def compare(self, a: Bar, b: Bar, *, full: bool = False) -> None:
        if a.trade is not None and b.trade is not None:
            self.record("trade", a.trade + b.trade - ONE)
        if a.interval is None or b.interval is None:
            return
        gap = signed_gap(a.interval, b.interval)
        self.record("interval", gap)
        self.record("midpoint", sum(a.interval + b.interval, Decimal(0)) / 2 - ONE)
        if full:
            self.absolute["combined_spread"].append(
                a.interval[1] - a.interval[0] + b.interval[1] - b.interval[0]
            )
            active = a.trade is not None and b.trade is not None
            if active:
                self.record("active_interval", gap)
            if a.envelope and b.envelope:
                envelope_gap = signed_gap(a.envelope, b.envelope)
                self.record("envelope", envelope_gap)
                self.counts["gross_gaps_with_envelope"] += gap != 0
                self.stable |= (
                    active
                    and envelope_gap != 0
                    and gap_after_fees(a.interval, b.interval, FEES[2]) > 0
                )
            for rate in FEES:
                residual = gap_after_fees(a.interval, b.interval, rate)
                self.counts[f"above_cost_{rate}"] += residual > 0
                self.absolute[f"cost_residual_{rate}"].append(residual)

    def record(self, kind: str, delta: Decimal) -> None:
        self.counts[f"{kind}_n"] += 1
        self.counts[f"{kind}_nonzero"] += delta != 0
        self.counts[f"{kind}_low"] += delta < 0
        self.counts[f"{kind}_high"] += delta > 0
        self.absolute[kind].append(abs(delta))


def summarize(series: list[Series]) -> Row:
    counts: Counter[str] = Counter()
    for s in series:
        counts.update(s.counts)
    kinds = {kind for s in series for kind in s.absolute}
    magnitudes = {}
    for kind in sorted(kinds):
        values = [s.absolute[kind] for s in series if s.absolute[kind]]
        means = [sum(xs, Decimal(0)) / len(xs) for xs in values]
        magnitudes[kind] = {
            "games": len(values),
            "games_nonzero": sum(any(xs) for xs in values),
            "game_weighted_mean_cents": round(float(sum(means) / len(means) * 100), 4),
            "max_absolute_cents": float(max(map(max, values)) * 100),
        }
    return {"counts": dict(sorted(counts.items())), "magnitudes": magnitudes}


def classify(aligned: Row, stable_games: int) -> str:
    counts, magnitudes = aligned["counts"], aligned["magnitudes"]
    if stable_games >= 2:
        return "PROMISING DIAGNOSTIC — requires prospective confirmation"
    if (
        magnitudes.get("interval", {}).get("games", 0) >= 4
        and counts.get("interval_n", 0) >= 30
        and not counts.get("interval_nonzero")
    ):
        return "NO SUPPORT IN SAMPLE"
    return "INCONCLUSIVE — insufficient or ambiguous evidence"


def compare_game(
    features: list[Row], markets: list[dict[int, Bar]], conflicts: list[set[int]]
) -> tuple[Counter[str], dict[str, Series]]:
    a, b = features
    left, right = markets
    opened, cutoff = epoch(a["open"]), epoch(a["cutoff"])
    require(
        a["open"] == b["open"] and a["cutoff"] == b["cutoff"] and cutoff - opened == 3600,
        "different or invalid first-hour windows",
    )
    ends = grid(opened, cutoff, 60)
    missing: Counter[str] = Counter(expected_game_minutes=len(ends))
    for bars, rejected in zip(markets, conflicts, strict=True):
        for end in ends:
            bar = bars.get(end)
            missing["absent_side_minutes"] += bar is None and end not in rejected
            missing["conflicting_side_minutes"] += end in rejected
            missing["unusable_quote_side_minutes"] += bar is not None and bar.interval is None
            missing["no_fresh_trade_side_minutes"] += bar is not None and bar.trade is None
            previous = bars.get(end - 60) if end - 60 in ends else None
            if previous and previous.interval and bar and bar.interval:
                missing["consecutive_quote_side_minutes"] += 1
                missing["unchanged_quote_side_minutes"] += previous.interval == bar.interval
    stats: dict[str, Series] = defaultdict(Series)
    clocks = [row["source_end_ts"] for row in features]
    require(all(type(end) is int and end in ends for end in clocks), "invalid baseline bar clocks")
    baseline = [bars.get(end) for bars, end in zip(markets, clocks, strict=True)]
    for row, bar in zip(features, baseline, strict=True):
        require(
            bar
            and bar.trade is not None
            and bar.interval is not None
            and bar.trade == price(row["price_dollars"])
            and bar.interval
            == quotes(
                price(row["bid_candle_close_dollars"]), price(row["ask_candle_close_dollars"])
            ),
            "baseline differs from frozen features",
        )
    if baseline[0] is None or baseline[1] is None:
        raise AuditError("missing baseline bars")
    stats["latest_individual"].compare(baseline[0], baseline[1])
    missing["games_unaligned_baseline"] += clocks[0] != clocks[1]
    missing["sum_baseline_gap_minutes"] += abs(clocks[0] - clocks[1]) // 60
    latest_quote = latest_trade = None
    for end in ends:
        if end in left and end in right:
            missing["common_bar_minutes"] += 1
            lbar, rbar = left[end], right[end]
            stats["aligned"].compare(lbar, rbar, full=True)
            if lbar.interval and rbar.interval:
                latest_quote = lbar, rbar
            if lbar.trade is not None and rbar.trade is not None:
                latest_trade = lbar, rbar
        for offset in (-60, 60):
            shifted = end + offset
            if shifted in ends and end in left and shifted in right:
                stats[f"shift_{offset // 60:+}"].compare(left[end], right[shifted])
    if latest_quote:
        stats["latest_common_quote"].compare(*latest_quote)
    if latest_trade:
        stats["latest_common_trade"].compare(*latest_trade)
    for lag in (0, 120):
        for end in grid(opened, cutoff, lag):
            if end in left and end in right:
                stats[f"lag_{lag}"].compare(left[end], right[end])
    return missing, stats


def evaluate(db: sqlite3.Connection, pairs: list[list[Row]]) -> Row:
    results: dict[str, list[Series]] = defaultdict(list)
    coverage: Counter[str] = Counter()
    clock_gaps = []
    for pair in pairs:
        event_id = pair[0]["exchange_event"]
        event = archived(db, "/events/" + event_id)["event"]
        roster: dict[str, Row] = {}
        for endpoint in ("/historical/markets", "/markets"):
            page = archived(db, endpoint, event_ticker=event_id, limit=100)
            require(page.get("cursor") == "", "incomplete sibling enumeration")
            for market in page["markets"]:
                # Whitelist the metadata fields. Settlement direction and payout are unused.
                keys = (
                    "ticker",
                    "event_ticker",
                    "market_type",
                    "yes_sub_title",
                    "custom_strike",
                    "rules_primary",
                    "rules_secondary",
                    "notional_value_dollars",
                    "open_time",
                    "mve_collection_ticker",
                    "mve_selected_legs",
                )
                projected = {key: market.get(key) for key in keys}
                require(
                    roster.get(market["ticker"], projected) == projected,
                    "conflicting sibling metadata",
                )
                roster[market["ticker"]] = projected
        require(
            set(roster) == {row["contract"] for row in pair},
            "archive roster differs from whitelist",
        )
        coverage["games_with_documented_exception"] += verify_rules(
            event, pair, [roster[row["contract"]] for row in pair]
        )
        coverage["archived_event_fee_overrides"] += any(
            event.get(key) is not None for key in ("fee_type_override", "fee_multiplier_override")
        )
        bars, conflicts = [], []
        for row in pair:
            ticker = row["contract"]
            path = row["source_path"]
            require(
                path
                in (
                    f"/historical/markets/{ticker}/candlesticks",
                    f"/series/{SERIES}/markets/{ticker}/candlesticks",
                ),
                "invalid candle archive path",
            )
            parsed, rejected = parse(
                archived(
                    db,
                    path,
                    start_ts=epoch(row["open"]),
                    end_ts=epoch(row["cutoff"]),
                    period_interval=1,
                ),
                ticker,
            )
            bars.append(parsed)
            conflicts.append(rejected)
        missing, stats = compare_game(pair, bars, conflicts)
        coverage.update(missing)
        clock_gaps.append(abs(pair[0]["source_end_ts"] - pair[1]["source_end_ts"]) // 60)
        for name, series in stats.items():
            results[name].append(series)
    report = {key: summarize(vals) for key, vals in sorted(results.items())}
    stable = sum(s.stable for s in results["aligned"])
    return {
        "classification": classify(report.get("aligned", {"counts": {}, "magnitudes": {}}), stable),
        "games_examined": len(pairs),
        "coverage": dict(sorted(coverage.items())),
        "baseline_end_gap_minutes_range": [min(clock_gaps), max(clock_gaps)],
        "stable_games": stable,
        "comparisons": report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "analyze"))
    args = parser.parse_args()
    try:
        sha, pairs = development(ROOT)
        freeze = {
            "feature_sha256": sha,
            "protocol_sha256": digest(PROTOCOL.read_bytes().replace(b"\r\n", b"\n")),
            "pairs": [[row["contract"] for row in group] for group in pairs],
        }
        path = ROOT / "e1-whitelist.json"
        if args.action == "freeze":
            with path.open("x", encoding="utf-8") as f:
                json.dump(freeze, f, indent=2)
            print("Six development pairs frozen locally.")
        else:
            require(json.loads(path.read_text(encoding="utf-8")) == freeze, "frozen inputs changed")
            with closing(
                sqlite3.connect((ROOT / "acquisition.sqlite").as_uri() + "?mode=ro", uri=True)
            ) as db:
                print(json.dumps(evaluate(db, pairs), indent=2))
    except AuditError as exc:
        print(exc)
        return 1
    except (
        OSError,
        sqlite3.Error,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        InvalidOperation,
    ):
        print("E1 local input or storage error")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
