"""Independent synthetic fixtures. Never open the operator's campaign directory."""

import io
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from research import a3_transport as net
from research.a3_campaign import main
from research.a3_data import candle_path, deduplicate, event_day, scan, spread, trade_routes
from research.a3_quality import (
    candles,
    identity,
    partitions,
    probability,
    settlement,
    summarize,
    trade_check,
    write_outputs,
)

T = datetime(2025, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_external_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("unexpected network access")

    monkeypatch.setattr(net.http.client, "HTTPSConnection", forbidden)


class Reply(io.BytesIO):
    def __init__(self, status, body, **headers):
        super().__init__(body)
        self.status = status
        self.headers = headers

    def getheader(self, name):
        return self.headers.get(name)


def test_campaign_entrypoint_rejects_ci_before_opening_any_storage(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr("sys.argv", ["a3_campaign", "discover"])
    with pytest.raises(net.Stop, match="local_campaign_only"):
        main()


def archive(path, replies):
    now = [1000.0]
    calls = []

    @contextmanager
    def send(resource, query):
        calls.append((resource, query, now[0]))
        yield replies.pop(0)

    def sleep(delay):
        now[0] += delay

    return net.Archive(path, send=send, clock=lambda: now[0], sleep=sleep), calls


@pytest.mark.parametrize(
    ("method", "host", "path", "params"),
    [
        ("POST", net.HOST, "/historical/cutoff", {}),
        ("GET", "elsewhere.invalid", "/markets", {}),
        ("GET", net.HOST, "/portfolio/balance", {}),
        ("GET", net.HOST, "//elsewhere.invalid/markets", {}),
        ("GET", net.HOST, "/series/../portfolio", {}),
        ("GET", net.HOST, "/series/%2fsecret", {}),
        ("GET", net.HOST, "/markets", {"token": "private"}),
    ],
)
def test_allowlist(method, host, path, params):
    with pytest.raises(net.Stop):
        net.endpoint(method, host, path, params)
    assert (
        net.endpoint("GET", net.HOST, "/historical/markets/X/candlesticks", {"period_interval": 1})
        == "/historical/markets/{id}/candlesticks"
    )


def test_redirect_and_raw_logging(tmp_path, capsys):
    a, calls = archive(tmp_path, [Reply(302, b"private-fixture", Location="https://other.invalid")])
    with pytest.raises(net.Stop, match="redirect_rejected"):
        a.get("/historical/cutoff")
    assert len(calls) == 1
    assert a.stats()["received_bytes"] == 15
    assert "private-fixture" not in str(a.stats()) + str(a.receipts())
    assert capsys.readouterr() == ("", "")


def test_retry_resume_limits_and_cache(tmp_path, monkeypatch):
    a, calls = archive(
        tmp_path, [Reply(429, b"{}", **{"Retry-After": "8"}), Reply(200, b'{"x":2}')]
    )
    assert a.get("/historical/cutoff") == {"x": 2}
    assert calls[1][2] - calls[0][2] >= 8
    assert a.stats()["received_bytes"] == 9
    a.db.close()
    a, calls = archive(tmp_path, [])
    assert a.get("/historical/cutoff") == {"x": 2}
    monkeypatch.setattr(net, "REQUEST_LIMIT", 2)
    with pytest.raises(net.Stop, match="campaign_budget"):
        a.get("/markets")
    assert not calls


def test_receipt_hash_and_inflight_reservation(tmp_path, monkeypatch):
    a, _ = archive(tmp_path, [Reply(200, b"{}")])
    a.get("/markets")
    a.db.execute("UPDATE attempts SET body=x'7b207d'")
    with pytest.raises(net.Stop, match="archive_hash_mismatch"):
        a.get("/markets")
    monkeypatch.setattr(net, "BYTE_LIMIT", 10)
    a.db.execute("INSERT INTO attempts(outcome,charged,started) VALUES('pending',8,1)")
    a.db.commit()
    with pytest.raises(net.Stop, match="campaign_budget"):
        a.get("/historical/cutoff")


def test_transient_failures_exhaust_attempts_across_restart(tmp_path):
    a, calls = archive(tmp_path, [Reply(503, b"{}") for _ in range(3)])
    with pytest.raises(net.Stop, match="retry_exhausted"):
        a.get("/markets")
    assert len(calls) == 3 and a.stats()["received_bytes"] == 6
    a.db.close()
    resumed, calls = archive(tmp_path, [])
    with pytest.raises(net.Stop, match="retry_exhausted"):
        resumed.get("/markets")
    assert not calls


def test_byte_cap_compression_and_authentication(tmp_path, monkeypatch):
    a, calls = archive(
        tmp_path,
        [Reply(200, b"a" * 100), Reply(200, b"z", **{"Content-Encoding": "gzip"}), Reply(401, b"")],
    )
    monkeypatch.setattr(net, "RESPONSE_LIMIT", 5)
    with pytest.raises(net.Stop, match="size_or_length"):
        a.get("/markets")
    with pytest.raises(net.Stop, match="unsupported_encoding"):
        a.get("/historical/cutoff")
    with pytest.raises(net.Stop, match="authorization_required"):
        a.get("/events/A")
    with pytest.raises(net.Stop, match="authorization_required"):
        a.get("/events/B")
    assert len(calls) == 3 and a.stats()["received_bytes"] == 5


@pytest.mark.parametrize(
    ("reply", "reason"),
    [(Reply(200, b"["), "malformed_json"), (Reply(200, b"[]"), "malformed_object")],
)
def test_invalid_json_is_local_only(tmp_path, reply, reason):
    a, _ = archive(tmp_path, [reply])
    with pytest.raises(net.Stop, match=reason):
        a.get("/markets")


def test_cursor_and_duplicate_conflicts(tmp_path):
    doc = b'{"markets":[{"ticker":"FAKE"}],"cursor":"repeats"}'
    a, _ = archive(tmp_path, [Reply(200, doc), Reply(200, doc)])
    rows, why = scan(a, "/markets", "markets", {}, 4)
    keep, conflicts, duplicates, missing = deduplicate(
        [*rows, {"ticker": "FAKE", "changed": True}, {}, {"ticker": "B"}], "ticker"
    )
    assert why == "repeated_cursor" and len(rows) == 2
    assert set(keep) == {"B"} and conflicts == {"FAKE"} and duplicates == missing == 1


def test_independent_archive_boundaries():
    ts = int(T.timestamp())
    assert candle_path("S", "M", T, T, True).startswith("/series/")
    assert candle_path("S", "M", T - timedelta(days=1), T, False).startswith("/historical/")
    assert trade_routes(ts - 2, ts + 1, T) == [
        ("/historical/trades", ts - 2, ts),
        ("/markets/trades", ts, ts + 1),
    ]
    assert event_day("S", "S-25FEB31XY") is None
    assert spread(list(range(6)), 3) == [0, 2, 5]


@pytest.mark.parametrize("value", [None, "", "NaN", "Infinity", "1.0001", "-0.01", "3e-100000", 12])
def test_invalid_probabilities(value):
    assert probability(value, Decimal(1)) is None
    assert probability("0.0137", Decimal(1)) == Decimal("0.0137")


def group(day=3):
    e = f"S-25JAN{day:02}AB"
    packets = []
    for i, side in enumerate(("A", "B")):
        ticker = e + "-" + side
        obj = {
            "ticker": ticker,
            "event_ticker": e,
            "market_type": "binary",
            "status": "finalized",
            "result": ["yes", "no"][i],
            "notional_value_dollars": "1.0000",
            "settlement_value_dollars": ["1.0000", "0.0000"][i],
            "settlement_ts": f"2025-01-{day:02}T23:00:00Z",
            "open_time": T.isoformat(),
            "close_time": f"2025-01-{day:02}T22:00:00Z",
            "yes_sub_title": side,
            "rules_primary": f"If {side} wins the basketball game on January {day}, 2025.",
            "custom_strike": {"team": f"00000000-0000-1111-2222-00000000000{i}"},
        }
        bar = {
            "end_period_ts": int(T.timestamp()) + 600,
            "volume": "0.31",
            "price": {"close": "0.0137"},
            "yes_bid": {"close": "0.0200"},
            "yes_ask": {"close": "0.0100"},
        }
        packets.append(
            {
                "market": obj,
                "candles": {"ticker": ticker, "candlesticks": [bar]},
                "candle_status": "ok",
                "trades": [],
                "trade_target": False,
                "trade_scan": [],
            }
        )
    return {
        "series": "S",
        "event": e,
        "cohort": "nba",
        "day": f"2025-01-{day:02}",
        "event_obj": {"series_ticker": "S", "event_ticker": e, "mutually_exclusive": True},
        "series_obj": {"ticker": "S"},
        "event_status": "ok",
        "roster": [p["market"]["ticker"] for p in packets],
        "enumeration": ["terminal_cursor"] * 2,
        "roster_missing": 0,
        "roster_conflicts": 0,
        "roster_duplicates": 2,
        "markets": packets,
    }


@pytest.mark.parametrize(
    ("changes", "state"),
    [
        ({"result": None}, "ambiguous"),
        ({"result": "scalar"}, "nonbinary"),
        ({"status": "voided"}, "void"),
        ({"status": "active"}, "unresolved"),
        ({"settlement_value_dollars": "0.99"}, "inconsistent"),
        ({"settlement_ts": None}, "ambiguous"),
    ],
)
def test_settlement(changes, state):
    m = group()["markets"][0]["market"]
    assert settlement(m) == ("final_binary", 1)
    assert settlement({**m, **changes}) == (state, None)


def test_grouping_complements_and_unknown_schedule():
    g = group()
    assert identity(g)
    features, _, report = summarize([g], {"nba": {}})
    assert report["nba"]["proxy_eligible_groups"] == 1 and len(features) == 2
    assert all(not f["strict_eligible"] for f in features)
    g["markets"][1]["market"].update(result="yes", settlement_value_dollars="1")
    assert summarize([g], {"nba": {}})[2]["nba"]["inconsistent_complement_groups"] == 1
    g["markets"][1]["market"]["custom_strike"] = g["markets"][0]["market"]["custom_strike"]
    assert identity(g) is None


def test_station_day_group_and_duplicate_bounds():
    g = group()
    g["cohort"] = "weather"
    g["event_obj"]["settlement_sources"] = [{"name": "synthetic station oracle"}]
    for i, p in enumerate(g["markets"]):
        p["market"].update(
            rules_primary="Maximum in New York City on January 3, 2025",
            strike_type="less" if i == 0 else "greater",
            floor_strike=i,
        )
    assert identity(g)
    g["markets"][1]["market"].update(strike_type="less", floor_strike=0)
    assert identity(g) is None


def test_candle_leakage_invalid_rows_and_trade_comparison():
    from collections import Counter

    p = group()["markets"][0]
    c = Counter()
    rows = p["candles"]["candlesticks"]
    rows.extend(
        [
            {**rows[0], "end_period_ts": int(T.timestamp()) + 3600},
            {**rows[0], "end_period_ts": int(T.timestamp()) + 4000},
            {
                **rows[0],
                "end_period_ts": int(T.timestamp()) + 1,
                "volume": "0",
                "price": {"previous": "0.8"},
            },
        ]
    )
    bar = candles(p, T, T + timedelta(hours=1), Decimal(1), c)
    assert bar[1] == Decimal("0.0137")
    assert (
        c["too_late_under_delay"]
        == c["incomplete_or_outside_window"]
        == c["empty_or_anchor_candles"]
        == 1
    )
    assert c["crossed_candle_quotes"] > 0
    p.update(
        trade_target=True,
        trade_scan=["terminal_cursor"],
        trades=[
            {
                "trade_id": "synthetic",
                "ticker": p["market"]["ticker"],
                "count_fp": "0.31",
                "yes_price_dollars": "0.0137",
                "is_block_trade": False,
                "created_time": (T + timedelta(seconds=590)).isoformat(),
            }
        ],
    )
    trade_check(p, bar, Decimal(1), c)
    assert c["matching_trade_closes"] == 1
    del p["trades"][0]["is_block_trade"]
    trade_check(p, bar, Decimal(1), c)
    assert c["unclassified_or_invalid_comparison_trade"] == 1
    rows.append({**rows[0], "price": {"close": "0.3"}})
    assert candles(p, T, T + timedelta(hours=1), Decimal(1), c) is None


def test_replay_and_holdout_separation(tmp_path):
    groups = [group(d) for d in range(2, 12)]
    assert partitions(groups)["nba", "2025-01-11"] == "holdout"
    features, labels, report = summarize(groups, {"nba": {}})
    first = write_outputs(tmp_path, features, labels, report)
    assert first == write_outputs(tmp_path, *summarize(groups, {"nba": {}}))
    rows = [
        json.loads(line)
        for line in (tmp_path / "normalized/holdout/features.jsonl").read_text().splitlines()
    ]
    assert rows and all("outcome" not in row and "result" not in row for row in rows)
    held = {r["contract"] for r in rows}
    assert held.isdisjoint({r["contract"] for r in labels if r["partition"] != "holdout"})
    assert report["nba"]["unknown_original_schedule"] == 20
    assert all(
        not r["settled_before_next_partition"] for r in labels if r["partition"] == "development"
    )
