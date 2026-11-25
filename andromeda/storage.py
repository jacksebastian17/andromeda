"""Transactional persistence of immutable synthetic records and runtime activity."""

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from .database import HEAD, StorageUnavailable, stamp, write_transaction
from .domain import Contract, Dataset, Event, Forecast, Resolution, evaluate
from .fixtures import build_fixture


def rows(conn: Connection, query: str, args: tuple[object, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.exec_driver_sql(query, args).mappings()]


def check_revision(conn: Connection) -> None:
    if conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalars().all() != [HEAD]:
        raise StorageUnavailable("Database migration required.")


def record_fields(record: Any) -> dict[str, Any]:
    return {k: stamp(v) if isinstance(v, datetime) else v for k, v in asdict(record).items()}


def immutable_insert(
    conn: Connection, table: str, data: dict[str, Any], key: tuple[str, ...] = ("id",)
) -> bool:
    """Table, columns and keys are private schema identifiers. Bind every data value."""
    where = " AND ".join(f"{column}=?" for column in key)
    old = rows(conn, f"SELECT * FROM {table} WHERE {where}", tuple(data[k] for k in key))
    if old:
        if old[0] != data:
            raise ValueError(f"Conflicting immutable {table} record: {tuple(data[k] for k in key)}")
        return False
    columns = ", ".join(data)
    params = ", ".join("?" for _ in data)
    conn.exec_driver_sql(f"INSERT INTO {table} ({columns}) VALUES ({params})", tuple(data.values()))
    return True


def persist_dataset(conn: Connection, dataset: Dataset) -> None:
    dataset.validate()
    for event in dataset.events:
        immutable_insert(conn, "events", record_fields(event))
    for contract in dataset.contracts:
        immutable_insert(conn, "contracts", record_fields(contract))
    for model in dataset.models:
        immutable_insert(conn, "models", record_fields(model), ("id", "version"))
    for obs in dataset.observations:
        data = record_fields(obs)
        data["counts"] = json.dumps(dict(obs.counts), sort_keys=True, separators=(",", ":"))
        immutable_insert(conn, "observations", data)
    for forecast in dataset.forecasts:
        data = record_fields(forecast)
        references = data.pop("observation_ids")
        if not immutable_insert(conn, "forecasts", data):
            actual = (
                conn.exec_driver_sql(
                    "SELECT observation_id FROM forecast_sources WHERE forecast_id=?",
                    (forecast.id,),
                )
                .scalars()
                .all()
            )
            if set(actual) != set(references):
                raise ValueError(f"Conflicting immutable forecast provenance: {forecast.id}")
            continue
        for obs_id in references:
            immutable_insert(
                conn,
                "forecast_sources",
                {
                    "forecast_id": forecast.id,
                    "event_id": forecast.event_id,
                    "observation_id": obs_id,
                },
                ("forecast_id", "observation_id"),
            )
    for resolution in dataset.resolutions:
        immutable_insert(conn, "resolutions", record_fields(resolution))
    for issue in dataset.issues:
        immutable_insert(conn, "issues", {**record_fields(issue), "kind": "missing"})


def save_job(conn: Connection, kind: str, status: str, message: str) -> None:
    now = stamp(datetime.now(UTC))
    conn.exec_driver_sql(
        """
        INSERT INTO jobs(kind,attempted_at,success_at,status,message) VALUES (?,?,?,?,?)
        ON CONFLICT(kind) DO UPDATE SET attempted_at=excluded.attempted_at,
            success_at=coalesce(excluded.success_at,jobs.success_at),
            status=excluded.status, message=excluded.message
    """,
        (kind, now, now if status == "ok" else None, status, message),
    )


def run_job(engine: Engine, kind: str, work: Callable[[Connection], str]) -> str:
    try:
        with write_transaction(engine) as conn:
            check_revision(conn)
            message = work(conn)
            save_job(conn, kind, "ok", message)
            return message
    except (ValueError, RuntimeError, SQLAlchemyError) as exc:
        # A failed transaction rolls back all research data. If storage is still
        # reachable, retain the failure without overwriting the last success.
        try:
            with write_transaction(engine) as conn:
                check_revision(conn)
                save_job(conn, kind, "error", f"{kind.capitalize()} failed ({type(exc).__name__}).")
        except (RuntimeError, SQLAlchemyError):
            pass
        raise


def ingest(
    engine: Engine, starting_cents: int, fixture: Callable[[], Dataset] = build_fixture
) -> str:
    def work(conn: Connection) -> str:
        dataset = fixture()
        persist_dataset(conn, dataset)
        conn.exec_driver_sql(
            """
            INSERT INTO portfolio(id,starting_cents,current_cents,realized_cents)
            VALUES (1,?,?,0) ON CONFLICT(id) DO NOTHING
        """,
            (starting_cents, starting_cents),
        )
        return (
            f"Fixture verified · {len(dataset.events)} events, {len(dataset.forecasts)} forecasts"
        )

    return run_job(engine, "ingestion", work)


def source_links(conn: Connection) -> dict[str, list[str]]:
    links: dict[str, list[str]] = defaultdict(list)
    for fid, oid in conn.exec_driver_sql(
        "SELECT forecast_id,observation_id FROM forecast_sources ORDER BY forecast_id,observation_id"
    ):
        links[fid].append(oid)
    return links


def parse_times(row: dict[str, Any], names: Sequence[str]) -> dict[str, Any]:
    return {**row, **{name: datetime.fromisoformat(row[name]) for name in names}}


def evaluate_persisted(engine: Engine) -> str:
    def work(conn: Connection) -> str:
        if not conn.exec_driver_sql(
            "SELECT 1 FROM jobs WHERE kind='ingestion' AND success_at IS NOT NULL"
        ).first():
            raise ValueError("Ingest the synthetic fixture before evaluation.")
        events = {
            r["id"]: Event(**parse_times(r, ("opens_at", "closes_at")))
            for r in rows(conn, "SELECT * FROM events")
        }
        contracts = {r["id"]: Contract(**r) for r in rows(conn, "SELECT * FROM contracts")}
        resolutions = {}
        for r in rows(conn, "SELECT * FROM resolutions"):
            data = parse_times(r, ("resolved_at", "available_at"))
            data["outcome"] = bool(data["outcome"])
            resolutions[r["contract_id"]] = Resolution(**data)
        links = source_links(conn)
        count = 0
        for r in rows(conn, "SELECT * FROM forecasts"):
            forecast = Forecast(
                **parse_times(r, ("cutoff_at", "generated_at")),
                observation_ids=tuple(links[r["id"]]),
            )
            resolution = resolutions.get(forecast.contract_id)
            if resolution is None:
                continue
            event = events[forecast.event_id]
            evaluation = evaluate(
                event,
                contracts[forecast.contract_id],
                forecast,
                resolution,
                event.closes_at + timedelta(hours=2),
            )
            immutable_insert(
                conn,
                "evaluations",
                {**record_fields(evaluation), "contract_id": forecast.contract_id},
            )
            count += 1
        return f"Brier evaluation verified · {count} resolved forecasts"

    return run_job(engine, "evaluation", work)
