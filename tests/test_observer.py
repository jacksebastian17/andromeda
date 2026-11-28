"""Prospective worker verification with a fake exchange, clock and private temporary ledger."""

import hashlib
import io
import json
from contextlib import closing
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from andromeda.api import create_app
from research.observer.__main__ import poll, run
from research.observer.records import discover, group, observe, snapshot
from research.observer.store import LIMITS, Halt, connect, health, initialize, owner
from research.observer.transport import HOST, SERIES, Client, FetchError, Reply, https_get, resource

NOW = datetime(2030, 1, 6, 12, tzinfo=UTC).timestamp()
EVENT = SERIES + "-30JAN06ALPBET"


class Clock:
    def __init__(self):
        self.t = NOW
        self.tick = 1.0

    def sleep(self, s):
        self.t += s
        self.tick += s


def game():
    return [
        {
            "ticker": EVENT + "-" + abbr,
            "event_ticker": EVENT,
            "market_type": "binary",
            "status": "active",
            "yes_sub_title": name,
            "custom_strike": {"team": f"00000000-0000-0000-0000-00000000000{i}"},
            "rules_primary": f"Does {name} win the basketball game on Jan 6, 2030?",
            "yes_bid_dollars": "0.3001",
            "yes_ask_dollars": "0.3550",
            "last_price_dollars": "0.3512",
            "no_bid_dollars": "0.6450",
            "no_ask_dollars": "0.6999",
            "notional_value_dollars": "1.0000",
            "yes_bid_size_fp": "1.23",
            "yes_ask_size_fp": "3.21",
            "volume_fp": "4.56",
            "open_interest_fp": "4.00",
            "volume_24h_fp": "4.56",
        }
        for i, (abbr, name) in enumerate([("ALP", "Alpha"), ("BET", "Beta")])
    ]


def listing(markets):
    return {
        "events": [
            {
                "series_ticker": SERIES,
                "event_ticker": EVENT,
                "mutually_exclusive": True,
                "markets": markets,
            }
        ],
        "milestones": [
            {
                "type": "basketball_game",
                "start_date": "2030-01-06T20:00:00Z",
                "related_event_tickers": [EVENT],
            }
        ],
        "cursor": "",
    }


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("network forbidden")

    monkeypatch.setattr("research.observer.transport.http.client.HTTPSConnection", unexpected)


@pytest.fixture
def db(tmp_path):
    with closing(connect(tmp_path / "smoke.sqlite")) as db:
        initialize(db, "smoke", NOW)
        yield db


def client(db, clock, override=None):
    def send(path, params, cap, timeout):
        clock.sleep(0.125)
        if override:
            return override(path, params, cap, timeout)
        data = {
            "/series/" + SERIES: {"series": {"ticker": SERIES}},
            "/events": listing(game()),
            "/markets": {"markets": game(), "cursor": ""},
        }[path]
        return Reply(200, json.dumps(data).encode())

    return Client(db, send, lambda: clock.t, lambda: clock.tick, clock.sleep)


@pytest.mark.parametrize(
    ("method", "host", "path", "params"),
    [
        ("POST", HOST, "/markets", {"tickers": EVENT + "-ALP"}),
        ("GET", "elsewhere.invalid", "/markets", {}),
        ("GET", HOST, "/portfolio/balance", {}),
        ("GET", HOST, "/markets", {"tickers": "../other"}),
        ("GET", HOST, "/series/" + SERIES, {"token": "private"}),
        ("GET", HOST, "/events", {}),
    ],
)
def test_destinations(method, host, path, params):
    with pytest.raises(Halt):
        resource(method, host, path, params)


def test_fresh_receipts_and_separate_labels(db, tmp_path):
    clock = Clock()
    api = client(db, clock)
    assert poll(api, 0) == "ok"
    clock.sleep(30)
    assert poll(api, 1) == "ok"
    calls = db.execute("SELECT * FROM requests WHERE path='/markets' ORDER BY id").fetchall()
    assert (
        len(calls) == 2
        and calls[0]["sha"] == calls[1]["sha"] == hashlib.sha256(calls[0]["body"]).hexdigest()
    )
    assert calls[0]["receipt"] < calls[1]["sent"]
    assert all(r["duration"] == 0.125 and r["receipt"] > r["sent"] for r in calls)
    h = health(tmp_path, "smoke", clock.t)
    assert (h.attempts, h.observations, h.groups, h.resolved) == (4, 4, 1, 0)
    assert db.execute("SELECT schedule FROM metadata").fetchone()[0].startswith("2030-01-06T20:")
    snap = json.loads(db.execute("SELECT snapshot FROM observations").fetchone()[0])
    assert snap["actual_game_start"] is None and snap["yes_bid_dollars"] == "0.3001"
    markets = game()
    for i, m in enumerate(markets):
        m.update(
            status="finalized",
            result=("no", "yes")[i],
            settlement_value_dollars=str(i),
            settlement_ts="2030-01-07T02:00:00Z",
        )
    ids = [m["ticker"] for m in markets]
    with db:
        observe(db, 50, clock.t, {"markets": markets}, ids)
    assert health(tmp_path, "smoke", clock.t).resolved == 0
    first_seen = clock.t
    clock.sleep(86400)
    with db:
        observe(db, 51, clock.t, {"markets": markets}, ids)
    assert health(tmp_path, "smoke", clock.t).resolved == 1
    markets[0]["settlement_value_dollars"] = "0.5"
    with db:
        observe(db, 52, clock.t + 2, {"markets": markets}, ids)
    assert health(tmp_path, "smoke", clock.t).resolved == 0
    assert db.execute("SELECT count(*) FROM settlements").fetchone()[0] == 6
    assert db.execute("SELECT min(receipt) FROM settlements").fetchone()[0] == first_seen


def test_missing_crossed_rules_and_schedule_revisions(db):
    ms = game()
    assert group(EVENT, ms)
    assert not group(EVENT, [ms[0], ms[0]])
    assert snapshot({**ms[0], "yes_bid_dollars": "0.9000"})[1] == "crossed_yes"
    assert "invalid_ask" not in snapshot(ms[0])[1]
    _, issues = snapshot(
        {**ms[0], "no_ask_dollars": None, "yes_bid_dollars": "NaN", "yes_bid_size_fp": "0"}
    )
    assert set(issues.split(",")) == {
        "missing_no_ask_dollars",
        "invalid_yes_bid_dollars",
        "empty_yes_bid_size_fp",
    }
    doc = listing(ms)
    discover(db, 1, NOW, doc)
    doc["milestones"] = []
    discover(db, 2, NOW, doc)
    assert [r[0] for r in db.execute("SELECT schedule_state FROM metadata ORDER BY id")] == [
        "reported",
        "missing",
    ]
    assert observe(db, 3, NOW, {"markets": ms[:1]}, [m["ticker"] for m in ms])
    assert [tuple(r) for r in db.execute("SELECT status,group_key FROM observations")] == [
        ("active", None),
        ("missing", None),
    ]


def test_budget_backoff_and_restart(db, tmp_path):
    clock = Clock()
    api = client(db, clock, lambda *args: Reply(429, b"{}", "120"))
    with pytest.raises(FetchError, match="429"):
        api.get(0, "/series/" + SERIES)
    with closing(connect(tmp_path / "smoke.sqlite")) as reopened:
        api = client(reopened, clock)
        with pytest.raises(FetchError, match="backoff"):
            api.get(1, "/series/" + SERIES)
        assert reopened.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
        clock.sleep(121)
        with reopened:
            reopened.execute("UPDATE campaign SET max_bytes=2")
        with pytest.raises(Halt, match="byte budget"):
            api.get(2, "/series/" + SERIES)
        with reopened:
            reopened.execute("UPDATE campaign SET max_requests=1,max_bytes=100")
        with pytest.raises(Halt, match="request budget"):
            api.get(2, "/series/" + SERIES)
    assert LIMITS["pilot"].seconds == 168 * 3600 and LIMITS["pilot"].interval == 300


def test_redirect_deadline_and_stop(db):
    clock = Clock()
    api = client(db, clock, lambda *args: Reply(302, b"private synthetic body"))
    with pytest.raises(Halt, match="HTTP 302"):
        api.get(0, "/series/" + SERIES)
    clock.sleep(900)
    with pytest.raises(Halt, match="deadline"):
        api.get(1, "/series/" + SERIES)
    assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1


def test_crash_downtime_health_and_no_backfill(db, tmp_path):
    with db:
        db.execute("UPDATE campaign SET next_slot=1,state='running'")
        db.execute("INSERT INTO polls(slot,started) VALUES(0,?)", (NOW,))
        db.execute(
            "INSERT INTO requests(slot,path,sent,charged) VALUES(0,'/events',?,4096)", (NOW,)
        )
    clock = Clock()
    clock.sleep(66)
    assert health(tmp_path, "smoke", clock.t).state == "stale"
    assert run(db, client(db, clock), clock.sleep) == "campaign complete"
    h = health(tmp_path, "smoke", clock.t)
    assert (h.state, h.gap_slots, h.errors, h.observations) == ("stopped", 2, 1, 4)
    assert [r[0] for r in db.execute("SELECT slot FROM polls ORDER BY slot")] == [0, 2, 3]
    assert db.execute("SELECT charged FROM requests WHERE id=1").fetchone()[0] == 4096
    assert h.deadline == datetime.fromtimestamp(NOW + 900, UTC).isoformat()


@pytest.mark.parametrize(
    ("headers", "body", "expected_bytes", "error"),
    [
        ({"Content-Encoding": "gzip"}, b"xyz", 0, "unexpected encoding"),
        ({"Content-Length": "6"}, b"abcdef", 0, "response exceeds allowance"),
        ({}, b"abcdef", 4, "incomplete response"),
        ({"Content-Length": "4"}, b"abcd", 4, ""),
    ],
)
def test_bounded_http_response(monkeypatch, headers, body, expected_bytes, error):
    class Response(io.BytesIO):
        status = 200

        def getheader(self, key, default=None):
            return headers.get(key, default)

    class Connection:
        sock = None

        def __init__(self, host, timeout):
            assert host == HOST and timeout > 0

        def request(self, method, path, headers):
            assert method == "GET" and path == "/trade-api/v2/series/" + SERIES
            assert headers["Accept-Encoding"] == "identity" and "Authorization" not in headers

        def getresponse(self):
            return Response(body)

        def close(self):
            pass

    monkeypatch.setattr("research.observer.transport.http.client.HTTPSConnection", Connection)
    result = https_get("/series/" + SERIES, {}, 4, 1)
    assert result.error == error and len(result.body) == expected_bytes


def test_empty_roster_still_gets_a_fresh_poll_and_bad_schema_is_reported(db):
    clock = Clock()
    calls = []

    def reply(path, *args):
        calls.append(path)
        if path.startswith("/series/"):
            return Reply(200, json.dumps({"series": {"ticker": SERIES}}).encode())
        event = listing([])
        return Reply(200, json.dumps(event if len(calls) < 3 else {"events": {}}).encode())

    api = client(db, clock, reply)
    assert poll(api, 0) == "no observed roster"
    with pytest.raises(FetchError, match="invalid rows"):
        poll(api, 1)
    assert calls.count("/events") == 2
    assert (
        db.execute("SELECT error FROM requests ORDER BY id DESC LIMIT 1").fetchone()[0]
        == "invalid rows"
    )


def test_ctrl_c_and_concurrent_worker(db, tmp_path):
    def interrupt(_):
        raise KeyboardInterrupt

    clock = Clock()
    with owner(tmp_path, "smoke"), pytest.raises(Halt, match="active"), owner(tmp_path, "smoke"):
        pytest.fail("second worker acquired ownership")
    assert run(db, client(db, clock), interrupt) == "operator interrupt"
    assert health(tmp_path, "smoke", clock.t).state == "stopped"


def test_readonly_health_endpoint(tmp_path):
    app = create_app(tmp_path / "absent.sqlite", tmp_path)
    with TestClient(app, base_url="http://localhost") as web:
        data = web.get("/api/v1/observer").json()
        assert [(x["mode"], x["state"]) for x in data] == [
            ("smoke", "stopped"),
            ("pilot", "stopped"),
        ]
        assert not (tmp_path / "pilot.sqlite").exists()
        with closing(connect(tmp_path / "pilot.sqlite")) as db:
            initialize(db, "pilot", NOW)
            db.execute(
                "UPDATE campaign SET state='running',heartbeat=unixepoch(),deadline=unixepoch()+600"
            )
            db.commit()
        data = web.get("/api/v1/observer").json()
        assert data[1]["state"] == "running" and "body" not in data[1]
