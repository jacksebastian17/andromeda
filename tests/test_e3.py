"""Independent synthetic clocks, winner contracts, probabilities and pilot receipts."""

import json
import math
from contextlib import closing
from datetime import UTC, date, datetime

import pytest

from research import e3
from research import e3_calibration as calibration
from research.e1 import AuditError
from research.e3_pilot import checkpoint
from research.observer.store import connect, initialize


def bar(end, bid="0.23", ask="0.27", volume="0"):
    return {
        "end_period_ts": end,
        "yes_bid": {"close": bid},
        "yes_ask": {"close": ask},
        "price": {"close": "0.31"},
        "volume_fp": volume,
    }


def test_clock_spread_trade_and_conflicting_ends():
    bars = [bar(3540), bar(3600, volume="1"), bar(7080, "0.40", "0.50"), bar(7140)]

    def get(rows, opened=0):
        return e3.quote({"ticker": "FAKE", "candlesticks": rows}, "FAKE", 7200, opened)

    obs, reason = get(bars)
    assert reason == "ok"
    assert obs == {"p": 0.45, "spread": 0.1, "age": 120, "trade": 0.31, "trade_age": 3600}
    assert get([bars[1]], 3540)[0]["age"] == 3600
    assert get([bars[1]], 3541)[1] == "no_completed_recent_bar"
    assert get([bars[0], bars[-1]])[0] is None
    assert get([bar(7080, "0", "0.70")])[1] == "no_valid_quote"
    assert get([bar(7080), bar(7080, volume="1")])[1] == "conflicting_candle_end"


def pair(event, day, settlement):
    markets = []
    for idx, (team, code, result) in enumerate([("Blue", "BLU", "no"), ("Mint", "MNT", "yes")]):
        markets.append(
            {
                "event_ticker": event,
                "ticker": event + "-" + code,
                "market_type": "binary",
                "yes_sub_title": team,
                "custom_strike": {"team": f"00000000-0000-0000-0000-00000000000{1 - idx}"},
                "rules_primary": f"If {team} wins the full basketball game on {day}, resolves Yes.",
                "rules_secondary": "Overtime counts.",
                "notional_value_dollars": "1",
                "status": "finalized",
                "result": result,
                "settlement_value_dollars": str(int(result == "yes")),
                "settlement_ts": settlement,
                "open_time": "2026-10-10T00:00:00Z",
                "close_time": settlement,
            }
        )
    return markets


def test_eligible_game_identity_and_boundary_purge(tmp_path, monkeypatch, capsys):
    dev = "KXNBAGAME-26NOV12BLUMNT"
    valid = "KXNBAGAME-26NOV13BLUMNT"
    a = pair(dev, "November 12, 2026", "2026-11-13T09:00:00Z")
    b = pair(valid, "November 13, 2026", "2026-11-14T01:00:00Z")
    assert e3.partition(date(2026, 11, 12)) == "development"
    assert e3.partition(date(2026, 11, 13)) == "validation"
    assert e3.partition(date(2026, 11, 19)) == "test"
    assert e3.binary_pair(b) and e3.binary_pair(list(reversed(b)))
    assert not e3.binary_pair([b[0], b[0]])
    assert e3.winner_identity(valid, b)
    assert not e3.winner_identity(
        valid,
        [
            {**m, "rules_primary": m["rules_primary"].replace("full", "first half of the")}
            for m in b
        ],
    )
    assert not e3.winner_identity(
        valid,
        [
            {**m, "rules_primary": m["rules_primary"].replace("resolves Yes", "resolves No")}
            for m in b
        ],
    )
    assert not e3.winner_identity(valid, [b[0], {**b[1], "rules_secondary": "Regulation only"}])
    assert not e3.winner_identity(
        valid, [{**m, "rules_primary": m["rules_primary"].replace("13", "14")} for m in b]
    )

    class Archive:
        def bind(self, *args):
            pass

        def stats(self):
            return {}

        def get(self, path, **params):
            assert path.endswith("-MNT/candlesticks")
            return {"ticker": path.split("/")[-2], "candlesticks": [bar(params["end_ts"])]}

    monkeypatch.setattr(e3, "ROOT", tmp_path)
    pool = {event: {m["ticker"]: m for m in markets} for event, markets in [(dev, a), (valid, b)]}
    roster = {"development": [dev], "validation": [valid], "test": []}
    monkeypatch.setattr(
        e3, "frame", lambda _: (pool, roster, set(), set(), datetime(2025, 1, 1, tzinfo=UTC), {})
    )
    e3.prepare(Archive())
    coverage = json.loads(capsys.readouterr().out)["partitions"]
    assert coverage["development"]["exclusions"] == {"boundary_purge": 1}
    assert coverage["validation"]["eligible_features"] == 1
    features = json.loads((tmp_path / "validation-features.json").read_text())
    assert set(features[0]) == {"day", "event", "p", "spread", "age", "trade", "trade_age"}


def test_fit_matches_known_bin_frequencies_and_loss_direction():
    # Two log-odds levels, both with empirical win frequencies equal to their forecasts.
    ps = [0.25] * 4 + [0.75] * 4
    ys = [1, 0, 0, 0, 1, 1, 1, 0]
    assert calibration.fit(ps, ys) == pytest.approx((0, 1))
    assert calibration.fit(ps, [1, 1, 0, 0] * 2) == pytest.approx((0, 0), abs=1e-9)
    assert calibration.fit([0.1, 0.2, 0.7, 0.8], [0, 0, 1, 1]) is None
    rows = [
        {"p": p, "y": y, "spread": 0.02, "day": "2035-01-01"} for p, y in zip(ps, ys, strict=True)
    ]
    stats = calibration.summary(calibration.score_rows(rows, 0, 0))
    assert stats["brier_raw"] == 0.1875
    assert stats["gain"] == -0.0625
    assert stats["log_loss_adjusted"] == pytest.approx(math.log(2))
    assert [b[0] for b in stats["bins_n_raw_adjusted_observed"]] == [0, 4, 0, 4, 0]


def test_failed_prefit_gate_leaves_later_labels_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(calibration, "ROOT", tmp_path)
    for split in e3.CAPS:
        (tmp_path / (split + "-features.json")).write_text("[]")
    (tmp_path / "development-labels.json").write_text("{}")
    # Intentionally provide neither validation nor test label files.
    (tmp_path / "prefit.json").write_text(json.dumps(calibration.assess()))
    assert calibration.prepare_fit()["fit_status"] == "insufficient_coverage"
    assert not (tmp_path / "frozen-fit.json").exists()
    with pytest.raises(FileNotFoundError, match="frozen-fit"):
        calibration.evaluate()


def test_fit_is_frozen_without_later_labels_and_changed_inputs_abort(tmp_path, monkeypatch):
    monkeypatch.setattr(calibration, "ROOT", tmp_path)
    features = []
    labels = {}
    for index in range(64):
        event = f"fiction-{index}"
        positive = index % 4 == 0 if index < 32 else index % 4 != 0
        rows = pair(event, "June 2, 2035", "2035-06-03T03:00:00Z")
        labels[event] = rows[::-1] if positive else rows
        features.append(
            {
                "event": event,
                "day": "2035-06-02",
                "p": 0.25 if index < 32 else 0.75,
                "age": 120,
                "spread": 0.02,
                "trade": None,
            }
        )
    for split, day in zip(e3.CAPS, ("2035-06-02", "2035-06-12", "2035-06-22"), strict=True):
        rows = (
            features
            if split == "development"
            else [{**r, "day": day, "event": split + r["event"]} for r in features]
        )
        (tmp_path / (split + "-features.json")).write_text(json.dumps(rows))
    (tmp_path / "development-labels.json").write_text(json.dumps(labels))
    (tmp_path / "prefit.json").write_text(json.dumps(calibration.assess()))
    assert calibration.prepare_fit()["fit_status"] == "frozen"
    assert (tmp_path / "frozen-fit.json").exists()
    # Changed features must stop evaluation before any later label packet is opened.
    (tmp_path / "validation-features.json").write_text("[]")
    with pytest.raises(AuditError, match="frozen features changed"):
        calibration.evaluate()


def test_blocks_resample_adjacent_days_together_including_empty_days():
    start, end = date(2035, 1, 1), date(2035, 1, 5)
    # The middle two games must stay together; the fourth date has no games.
    rows = [
        {"day": "2035-01-01", "delta": -0.4},
        {"day": "2035-01-02", "delta": 0.1},
        {"day": "2035-01-02", "delta": 0.3},
        {"day": "2035-01-03", "delta": 0.2},
    ]
    assert calibration.block_interval(rows, start, end) == pytest.approx((0, 0.2))


def test_pilot_counts_distinct_games_and_requires_covered_decision(tmp_path):
    path = tmp_path / "synthetic.sqlite"
    decision = 6000
    key = "SERIES/date/00000000-0000-0000-0000-000000000000/00000000-0000-0000-0000-000000000001"
    with closing(connect(path)) as db:
        initialize(db, "pilot", 5400)
        db.executemany(
            "INSERT INTO requests(id,slot,status,receipt) VALUES(?,?,200,?)",
            [(1, 0, 5400), (2, 1, 5800)],
        )
        db.execute(
            "INSERT INTO metadata(request_id,event,group_key,schedule,schedule_state) VALUES(1,'fake',?,?,'reported')",
            (key, datetime.fromtimestamp(decision + 3600, UTC).isoformat()),
        )
        for side in range(2):
            payload = {
                "custom_strike": {"team": key.split("/")[-2 + side]},
                "yes_bid_dollars": "0.3",
                "yes_ask_dollars": "0.4",
                "notional_value_dollars": "1",
                "yes_bid_size_fp": "1",
                "yes_ask_size_fp": "2",
            }
            db.execute(
                "INSERT INTO observations(request_id,event,group_key,status,snapshot) VALUES(2,'fake',?,'active',?)",
                (key, json.dumps(payload)),
            )
        db.execute("INSERT INTO polls(slot,finished,quality) VALUES(1,5800,'ok')")
        db.commit()
        assert checkpoint(path, decision - 1)["scheduled_status"] == {"pending_horizon": 1}
        assert checkpoint(path, decision + 1)["scheduled_status"] == {"decision_gap": 1}
        db.execute("INSERT INTO polls(slot,finished,quality) VALUES(2,6000,'ok')")
        db.commit()
    report = checkpoint(path, decision + 1)
    assert (report["observations"], report["observed_games"], report["quote_batches"]) == (2, 1, 1)
    assert report["scheduled_status"] == {"scheduled_quote_eligible": 1}
    assert report["strict_eligible_games"] == 0
