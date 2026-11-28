import json
import sqlite3
from contextlib import closing
from decimal import Decimal as D

import pytest

from research.e1 import (
    AuditError,
    Bar,
    Series,
    archived,
    classify,
    compare_game,
    digest,
    gap_after_fees,
    grid,
    parse,
    signed_gap,
    summarize,
    verify_rules,
)


def test_fee_rounding_applies_per_side_and_at_equality():
    a = (D("0.46"), D("0.49"))
    b = (D("0.45"), D("0.49"))
    assert signed_gap(a, b) == D("-0.02")
    assert gap_after_fees(a, b, D("0")) == D("0.02")
    assert gap_after_fees(a, b, D("0.035")) == 0
    c = (D("0.55"), D("0.60"))
    assert signed_gap(c, c) == D("0.10")
    assert gap_after_fees(c, c, D("0.07")) == D("0.06")
    assert signed_gap(a, (D("0.48"), D("0.51"))) == 0


def test_trade_anchors_invalid_quotes_and_conflicting_candles():
    row = {
        "end_period_ts": 120,
        "yes_bid": {"close": "0.4000", "low": "0.3500"},
        "yes_ask": {"close_dollars": "0.6000", "high_dollars": "0.6500"},
        "price": {"close_dollars": "0.5001", "previous_dollars": "0.4900"},
        "volume_fp": "3.50",
    }
    body = {
        "ticker": "TEST",
        "candlesticks": [
            row,
            row,
            {**row, "end_period_ts": 180, "volume_fp": "0.00"},
            {**row, "end_period_ts": 240, "yes_bid": {"close": "0.70"}},
            {**row, "end_period_ts": 300},
            {**row, "end_period_ts": 300, "price": {"close": "0.42"}},
        ],
    }
    bars, conflicts = parse(body, "TEST")
    assert conflicts == {300}
    assert bars[120] == Bar((D(".4"), D(".6")), (D(".35"), D(".65")), D(".5001"))
    assert bars[180].interval == bars[120].interval and bars[180].trade is None
    assert bars[240].interval is None
    assert 300 not in bars
    assert list(grid(1, 181, 60)) == [120]


def test_alignment_picks_observed_bars_without_carrying_prices_forward():
    window = {"open": "1970-01-01T00:00:00Z", "cutoff": "1970-01-01T01:00:00Z"}
    feature = {
        **window,
        "price_dollars": ".30",
        "bid_candle_close_dollars": ".25",
        "ask_candle_close_dollars": ".40",
    }
    a = Bar((D(".25"), D(".40")), (D(".20"), D(".50")), D(".30"))
    b = Bar((D(".59"), D(".73")), (D(".57"), D(".75")), D(".62"))
    left = {60: a, 120: a}
    right = {60: b, 180: a}
    missing, stats = compare_game(
        [{**feature, "source_end_ts": 120}, {**feature, "source_end_ts": 180}],
        [left, right],
        [set(), {240}],
    )
    assert missing["absent_side_minutes"] == 113
    assert missing["conflicting_side_minutes"] == 1
    assert missing["unchanged_quote_side_minutes"] == 1
    assert missing["common_bar_minutes"] == 1
    assert stats["aligned"].counts["interval_nonzero"] == 0
    assert stats["aligned"].counts["trade_nonzero"] == 1
    assert stats["latest_individual"].counts["interval_low"] == 1
    assert stats["shift_+1"].counts["interval_low"] == 1


def test_wider_intervals_remove_small_disagreements_and_require_both_trades():
    closed = Bar((D(".51"), D(".55")), (D(".45"), D(".58")), None)
    active = Bar(closed.interval, closed.envelope, D(".50"))
    series = Series()
    series.compare(active, closed, full=True)
    assert series.counts["interval_high"] == series.counts["gross_gaps_with_envelope"] == 1
    assert series.counts["envelope_nonzero"] == series.counts["active_interval_n"] == 0
    assert classify(summarize([series]), 0).startswith("INCONCLUSIVE")
    consistent = Series()
    for _ in range(8):
        consistent.compare(active, Bar((D(".45"), D(".50")), None, None))
    assert classify(summarize([consistent] * 3), 0).startswith("INCONCLUSIVE")
    assert classify(summarize([consistent] * 4), 0) == "NO SUPPORT IN SAMPLE"


@pytest.mark.parametrize(
    "damage", [None, "different_condition", "different_rule", "different_notional"]
)
def test_rules_require_same_game_and_distinct_complementary_predicates(damage):
    game = "KXNBAGAME-30JAN06ALPBET"
    teams = [f"00000000-0000-0000-0000-00000000000{i}" for i in (1, 2)]
    event = {
        "event_ticker": game,
        "series_ticker": "KXNBAGAME",
        "mutually_exclusive": True,
        "settlement_sources": [{"name": "Synthetic league"}],
    }
    markets = []
    features = []
    for code, name, team in zip(("ALP", "BET"), ("Alpha", "Beta"), teams, strict=True):
        ticker = f"{game}-{code}"
        markets.append(
            {
                "ticker": ticker,
                "event_ticker": game,
                "market_type": "binary",
                "yes_sub_title": name,
                "custom_strike": {"team": team},
                "open_time": "2030-01-05T00:00:00Z",
                "notional_value_dollars": "1.0000",
                "rules_primary": (
                    f"If {name} wins the Alpha vs Beta basketball game originally scheduled "
                    "for Jan 6, 2030, this market resolves to Yes."
                ),
                "rules_secondary": "If postponed or cancelled, the exchange may settle at a fair price.",
            }
        )
        features.append(
            {
                "exchange_event": game,
                "contract": ticker,
                "open": "2030-01-05T00:00:00Z",
                "day": "2030-01-06",
                "underlying_event": "/".join(["KXNBAGAME", "2030-01-06", *teams]),
                "notional_dollars": "1",
            }
        )
    if damage is None:
        assert verify_rules(event, features, markets)
    else:
        key, value = {
            "different_condition": ("rules_secondary", "Always resolves at a fair price."),
            "different_rule": (
                "rules_primary",
                markets[1]["rules_primary"].replace("wins", "loses"),
            ),
            "different_notional": ("notional_value_dollars", "0.5000"),
        }[damage]
        markets[1][key] = value
        with pytest.raises(AuditError):
            verify_rules(event, features, markets)


def test_archive_requires_exact_query_and_verified_digest():
    body = json.dumps({"candlesticks": []}).encode()
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("CREATE TABLE attempts(path,query,status,outcome,body,sha256)")
        db.execute(
            "INSERT INTO attempts VALUES('/test','period_interval=1',200,'ok',?,?)",
            (body, digest(body)),
        )
        assert archived(db, "/test", period_interval=1) == {"candlesticks": []}
        with pytest.raises(AuditError, match="missing"):
            archived(db, "/test", period_interval=60)
        db.execute("UPDATE attempts SET sha256='wrong'")
        with pytest.raises(AuditError, match="hash mismatch"):
            archived(db, "/test", period_interval=1)
