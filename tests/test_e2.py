import json
from datetime import datetime
from decimal import Decimal

import pytest

from research import e2, e2_noaa
from research.e1 import AuditError


def test_integer_weather_brackets_include_both_inner_bounds():
    assert e2.bracket({"strike_type": "less", "cap_strike": 40}) == (None, 39)
    assert e2.bracket({"strike_type": "between", "floor_strike": 40, "cap_strike": 41}) == (40, 41)
    assert e2.bracket({"strike_type": "greater", "floor_strike": 41}) == (42, None)
    with pytest.raises(AuditError):
        e2.bracket({"strike_type": "between", "floor_strike": 41, "cap_strike": 40})


@pytest.mark.parametrize("change", ["none", "suspended", "zero_size", "rule_mismatch"])
def test_same_response_screen(change):
    rows = []
    for name in ("Test Alpha", "Test Beta"):
        market = {
            "open_time": "2030-01-01T00:00:00Z",
            "close_time": "2030-01-04T00:00:00Z",
            "yes_bid_dollars": "0.4000",
            "yes_ask_dollars": "0.6000",
            "yes_bid_size_fp": "1",
            "yes_ask_size_fp": "2",
            "notional_value_dollars": "1.00",
            "yes_sub_title": name,
            "rules_primary": f"If {name} wins the basketball game, resolves Yes.",
            "rules_secondary": "Synthetic full game.",
        }
        status = "active"
        if rows:
            if change == "suspended":
                status = "inactive"
            if change == "zero_size":
                market["yes_ask_size_fp"] = "0"
            if change == "rule_mismatch":
                market["rules_secondary"] = "Synthetic first half."
        rows.append(
            {"ticker": name, "quality": "ok", "snapshot": json.dumps(market), "status": status}
        )
    result = e2.interval_pair(rows, datetime.fromisoformat("2030-01-02T00:00:00Z").timestamp())
    assert result == ([(Decimal(".4"), Decimal(".6"))] * 2 if change == "none" else None)


def test_card_identity_date_and_daytime_columns(tmp_path, monkeypatch):
    body = b""" KNYC  NBM V5.0 NBP GUIDANCE  9/01/2026 0100 UTC
 UTC     00| 12
 FHR     23| 35
 TXNP1   44| 22
 TXNP2   49| 28
 TXNP5   53| 32
 TXNP7   55| 37
 TXNP9   61| 40
 KZZZ  NBM V5.0 NBP GUIDANCE  9/01/2026 0100 UTC
 TXNP1   99| 99
"""
    frozen = {"days": {"2026-09-01": []}}
    monkeypatch.setattr(e2_noaa, "PRIVATE", tmp_path)
    monkeypatch.setattr(
        e2_noaa,
        "population",
        lambda: (frozen, [{"day": "2026-09-01", "source_end_ts": e2_noaa.CYCLE.timestamp() + 100}]),
    )
    (tmp_path / "population.json").write_text(json.dumps(frozen))
    e2_noaa.save(body, 206, "Tue, 01 Sep 2026 02:00:00 GMT", "synthetic")
    result = e2_noaa.audit()
    assert result["daytime_max_columns"] == result["day_labels_intersect"] == 1
    assert result["candidate_days_archive_object_precedes_all_selected_closes"] == 0
    with pytest.raises(AuditError):
        e2_noaa.bulletin(body.replace(b"0100 UTC", b"0000 UTC"))
    (tmp_path / "noaa-nbp.txt").write_bytes(body + b"x")
    with pytest.raises(AuditError, match="digest"):
        e2_noaa.audit()


def test_oversized_response_is_closed_without_reading(tmp_path, monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def getheader(self, key, default=None):
            return {"Content-Length": str(e2_noaa.LIMIT + 1), "ETag": "synthetic"}.get(key, default)

    class Connection:
        def __init__(self, host, timeout):
            assert host == e2_noaa.HOST

        def request(self, method, path, headers):
            assert (method, path) == ("GET", e2_noaa.OBJECT)

        def getresponse(self):
            return Response()

        def close(self):
            pass

    ranges = []
    monkeypatch.setattr(e2_noaa, "PRIVATE", tmp_path)
    monkeypatch.setattr(e2_noaa, "population", lambda: ({}, []))
    monkeypatch.setattr(e2_noaa.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(e2_noaa, "station_range", lambda n, tag: ranges.append((n, tag)))
    (tmp_path / "population.json").write_text("{}")
    e2_noaa.acquire()
    assert ranges == [(e2_noaa.LIMIT + 1, "synthetic")]
    with pytest.raises(FileExistsError):
        e2_noaa.acquire()
