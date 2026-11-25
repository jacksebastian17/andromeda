"""Exercise the migration, writer, read API and operator failure paths on real files."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError

from andromeda.api import create_app
from andromeda.database import HEAD, cash_cents, make_engine, migrate, stamp, write_transaction
from andromeda.fixtures import build_fixture
from andromeda.storage import evaluate_persisted, ingest

PREFIX = "/api/v1"
EXPECTED_COUNTS = {
    "events": 5,
    "contracts": 13,
    "forecasts": 10,
    "resolved_events": 4,
    "evaluated_forecasts": 7,
    "missing_forecasts": 3,
    "invalid_forecasts": 0,
    "unresolved_forecasts": 3,
}


def client(path: Path) -> TestClient:
    return TestClient(create_app(path), base_url="http://127.0.0.1:8000")


@pytest.fixture
def db(tmp_path: Path) -> Path:
    # Test URI quoting, not just a simple path.
    path = tmp_path / "research #1.sqlite3"
    migrate(path)
    return path


def test_migration_empty_schema_and_lifecycle(db: Path) -> None:
    migrate(db)
    engine = make_engine(db)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == HEAD
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
    with client(db) as web:
        health = web.get(PREFIX + "/health").json()
        assert health["source_status"] == "uninitialized"
        assert health["last_ingestion_at"] is health["missing_inputs"] is None
        assert health["uptime_seconds"] >= 0 and health["started_at"].endswith("Z")
        assert web.get(PREFIX + "/events").json() == []
        initial = web.get(PREFIX + "/overview").json()
        assert set(initial["counts"].values()) == {0}
        assert initial["mean_brier"] is initial["portfolio"] is None
        assert initial["activity"] == []
        assert web.get(PREFIX + "/portfolio").status_code == 404
    with pytest.raises(ValueError, match="Ingest"):
        evaluate_persisted(engine)
    with client(db) as web:
        assert any("failed" in w for w in web.get(PREFIX + "/health").json()["warnings"])


def test_actual_api_and_persistence_after_restart(db: Path) -> None:
    engine = make_engine(db)
    ingest(engine, 100_000)
    with client(db) as web:
        before = web.get(PREFIX + "/research/evaluations").json()
        assert before["records"] == [] and before["mean_brier"] is None
    evaluate_persisted(engine)
    with client(db) as web:
        one = web.get(PREFIX + "/overview").json()
        assert one["counts"] == EXPECTED_COUNTS
        assert one["mean_brier"] == pytest.approx(0.10035714285714286, abs=1e-14)
        assert {a["kind"] for a in one["activity"]} == {"ingestion", "evaluation"}
        health = web.get(PREFIX + "/health").json()
        assert health["source_status"] == "incomplete" and health["missing_inputs"] == 1
        assert health["last_ingestion_at"].endswith("Z") and health["last_evaluation_at"].endswith(
            "Z"
        )
        ledger = web.get(PREFIX + "/research/evaluations").json()
        assert ledger["counts"] == EXPECTED_COUNTS
        assert len(ledger["records"]) == 7
        assert len({r["event_id"] for r in ledger["records"]}) == 3
        ev = web.get(PREFIX + "/events").json()
        assert len(ev) == 5 and sum(len(e["contracts"]) for e in ev) == 13
        models = web.get(PREFIX + "/research/models").json()
        assert [(m["id"], m["version"], m["status"]) for m in models] == [
            ("ensemble-frequency", "1.0.0", "experimental")
        ]
        missing = web.get(PREFIX + "/events/T-CIRRUS").json()
        assert missing["observations"] == []
        assert all(c["forecast"] is None and c["issue"] for c in missing["contracts"])
        assert all(c["resolution"] is not None for c in missing["contracts"])
        delta = web.get(PREFIX + "/events/T-DELTA").json()
        assert all(c["resolution"] is None and c["forecast"] for c in delta["contracts"])
        relay = web.get(PREFIX + "/events/B-RELAY").json()
        obs = relay["observations"][0]
        assert obs["issued_at"] is None and obs["available_at"].endswith("Z")
        assert relay["contracts"][0]["forecast"]["observation_ids"] == [obs["id"]]
        assert web.get(PREFIX + "/events/unknown").status_code == 404
        account = web.get(PREFIX + "/portfolio").json()
        assert account == dict(
            currency="USD",
            starting_cash="1000.00",
            current_cash="1000.00",
            realized_pnl="0.00",
            open_positions=0,
            transactions=0,
            return_pct=None,
            win_rate=None,
        )
    engine.dispose()
    migrate(db)
    reopened = make_engine(db)
    ingest(reopened, 17)
    evaluate_persisted(reopened)
    with client(db) as web:
        assert web.get(PREFIX + "/overview").json()["counts"] == EXPECTED_COUNTS
        assert web.get(PREFIX + "/portfolio").json() == account
        assert web.get(PREFIX + "/events").json() == ev
        assert web.get(PREFIX + "/research/evaluations").json() == ledger
        assert web.get(PREFIX + "/health").json()["started_at"] != health["started_at"]


def test_missing_database_and_wrong_revision_report_503(tmp_path: Path) -> None:
    path = tmp_path / "absent.sqlite3"
    with client(path) as web:
        health = web.get(PREFIX + "/health")
        assert health.status_code == 503
        assert health.json()["database"] == health.json()["source_status"] == "unavailable"
        assert health.json()["missing_inputs"] is None
        assert web.get(PREFIX + "/overview").status_code == 503
        assert not path.exists()
        migrate(path)
        with write_transaction(make_engine(path)) as conn:
            conn.exec_driver_sql("UPDATE alembic_version SET version_num='unknown'")
        assert web.get(PREFIX + "/health").status_code == 503
        assert web.get(PREFIX + "/events").status_code == 503


def test_replay_is_atomic_and_provenance_is_immutable(db: Path) -> None:
    engine = make_engine(db)
    fixture = build_fixture()
    ingest(engine, 123_45)
    first = fixture.forecasts[0]
    obs = next(o for o in fixture.observations if o.id in first.observation_ids)
    extra = replace(obs, id="EXTRA")
    proposed = replace(
        fixture,
        observations=(*fixture.observations, extra),
        forecasts=(
            replace(first, observation_ids=(*first.observation_ids, extra.id)),
            *fixture.forecasts[1:],
        ),
    )
    with pytest.raises(ValueError, match="Conflicting immutable forecast provenance"):
        ingest(engine, 999_99, lambda: proposed)
    with engine.connect() as conn:
        assert (
            conn.exec_driver_sql("SELECT COUNT(*) FROM observations WHERE id='EXTRA'").scalar() == 0
        )
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM forecast_sources").scalar() == 10
    with client(db) as web:
        health = web.get(PREFIX + "/health").json()
        assert health["source_status"] == "error" and health["last_ingestion_at"]
        assert web.get(PREFIX + "/portfolio").json()["current_cash"] == "123.45"
    ingest(engine, 0)
    with client(db) as web:
        assert web.get(PREFIX + "/health").json()["source_status"] == "incomplete"


@pytest.mark.parametrize(
    ("new_id", "error", "message"),
    [
        (None, ValueError, "Conflicting immutable forecasts record"),
        ("duplicate", IntegrityError, "UNIQUE constraint failed: forecasts.contract_id"),
    ],
)
def test_persisted_cutoff_rejects_conflicting_replay(
    db: Path, new_id: str | None, error: type[Exception], message: str
) -> None:
    engine = make_engine(db)
    fixture = build_fixture()
    relay = next(f for f in fixture.forecasts if f.contract_id == "B-RELAY-YES")
    conflicting = replace(
        relay, id=new_id or relay.id, generated_at=relay.generated_at + timedelta(seconds=1)
    )
    proposed = replace(
        fixture,
        forecasts=tuple(conflicting if f.id == relay.id else f for f in fixture.forecasts),
        evaluations=(),
    )
    proposed.validate()
    ingest(engine, 100_000)
    evaluate_persisted(engine)

    with pytest.raises(error, match=message):
        ingest(engine, 100_000, lambda: proposed)

    with engine.connect() as conn:
        assert conn.exec_driver_sql(
            "SELECT id, cutoff_at, generated_at FROM forecasts WHERE contract_id=?",
            (relay.contract_id,),
        ).all() == [(relay.id, stamp(relay.cutoff_at), stamp(relay.generated_at))]
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM evaluations").scalar_one() == 7
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM forecast_sources").scalar_one() == 10


def test_persist_distinct_cutoffs_with_same_generation_time(db: Path) -> None:
    engine = make_engine(db)
    fixture = build_fixture()
    relay = next(f for f in fixture.forecasts if f.contract_id == "B-RELAY-YES")
    later = replace(relay, id="later-cutoff", cutoff_at=relay.cutoff_at + timedelta(seconds=1))
    proposed = replace(fixture, forecasts=(*fixture.forecasts, later))
    ingest(engine, 100_000)

    for _ in range(2):
        ingest(engine, 100_000, lambda: proposed)

    with engine.connect() as conn:
        assert conn.exec_driver_sql(
            "SELECT id, cutoff_at, generated_at FROM forecasts WHERE contract_id=? ORDER BY cutoff_at",
            (relay.contract_id,),
        ).all() == [
            (relay.id, stamp(relay.cutoff_at), stamp(relay.generated_at)),
            (later.id, stamp(later.cutoff_at), stamp(relay.generated_at)),
        ]


def test_concurrent_replay_and_foreign_keys(db: Path) -> None:
    engine = make_engine(db)

    def replay(_: int) -> None:
        ingest(engine, 100_000)
        evaluate_persisted(engine)

    with ThreadPoolExecutor(3) as pool:
        list(pool.map(replay, range(6)))
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert conn.exec_driver_sql("SELECT count(*) FROM jobs").scalar() == 2
        assert conn.exec_driver_sql("SELECT count(*) FROM evaluations").scalar() == 7
    with pytest.raises(IntegrityError), write_transaction(engine) as conn:
        conn.exec_driver_sql("UPDATE forecasts SET event_id='T-DELTA' WHERE id='F-T-ASTER-MID-v1'")
    with pytest.raises(IntegrityError), write_transaction(engine) as conn:
        conn.exec_driver_sql(
            "UPDATE evaluations SET resolution_id='R-T-ASTER-LOW' WHERE contract_id='B-RELAY-YES'"
        )
    with pytest.raises(IntegrityError), write_transaction(engine) as conn:
        conn.exec_driver_sql(
            "UPDATE forecasts SET probability=1e999 WHERE contract_id='B-RELAY-YES'"
        )


def test_execution_surface_and_cors(db: Path) -> None:
    with (
        pytest.raises(OperationalError, match="readonly"),
        make_engine(db, mode="ro").begin() as conn,
    ):
        conn.exec_driver_sql("INSERT INTO portfolio VALUES (1,0,0,0)")
    with client(db) as web:
        paths = web.get("/openapi.json").json()["paths"]
        assert set(paths) == {
            PREFIX + p
            for p in (
                "/health",
                "/overview",
                "/events",
                "/events/{event_id}",
                "/portfolio",
                "/research/models",
                "/research/evaluations",
            )
        }
        assert all(set(methods) == {"get"} for methods in paths.values())
        assert web.post(PREFIX + "/portfolio").status_code == 405
        assert web.post(PREFIX + "/orders").status_code == 404
        assert web.get(PREFIX + "/health", headers={"Host": "example.org"}).status_code == 400
        for origin, allowed in [("http://localhost:5173", True), ("https://example.org", False)]:
            response = web.get(PREFIX + "/health", headers={"Origin": origin})
            assert (response.headers.get("access-control-allow-origin") == origin) == allowed


@pytest.mark.parametrize(
    "value",
    [
        "1.001",
        "-1",
        "NaN",
        "Infinity",
        "text",
        "92233720368547758.08",
        "0.01000000000000000000000000000000000000001",
    ],
)
def test_invalid_starting_cash(value: str) -> None:
    with pytest.raises(ValueError):
        cash_cents(value)


def test_exact_money() -> None:
    assert cash_cents("1000.00") == 100000
    assert cash_cents("92233720368547758.07") == 2**63 - 1
    assert cash_cents("0.10") == 10
