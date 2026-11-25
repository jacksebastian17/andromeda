"""Read each API payload from one SQLite snapshot. No polling jobs mutate storage."""

import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from . import schemas as s
from .storage import rows, source_links


def counts(conn: Connection) -> s.Counts:
    row = rows(
        conn,
        """SELECT
      (SELECT count(*) FROM events) AS events,
      (SELECT count(*) FROM contracts) AS contracts,
      (SELECT count(*) FROM forecasts) AS forecasts,
      (SELECT count(*) FROM events WHERE state='resolved') AS resolved_events,
      (SELECT count(DISTINCT forecast_id) FROM evaluations) AS evaluated_forecasts,
      (SELECT count(*) FROM issues WHERE kind='missing') AS missing_forecasts,
      (SELECT count(*) FROM issues WHERE kind='invalid') AS invalid_forecasts,
      (SELECT count(*) FROM forecasts f JOIN events e ON f.event_id=e.id
       WHERE e.state='unresolved') AS unresolved_forecasts""",
    )[0]
    return s.Counts.model_validate(row)


def mean_brier(conn: Connection) -> float | None:
    result = conn.exec_driver_sql(
        "SELECT AVG(score) FROM evaluations WHERE metric='brier'"
    ).scalar()
    return None if result is None else float(result)


def portfolio(conn: Connection) -> s.Portfolio | None:
    row = conn.exec_driver_sql("SELECT * FROM portfolio WHERE id=1").mappings().first()
    if row is None:
        return None

    def usd(column: str) -> str:
        return format(Decimal(row[column]).scaleb(-2), ".2f")

    return s.Portfolio(
        starting_cash=usd("starting_cents"),
        current_cash=usd("current_cents"),
        realized_pnl=usd("realized_cents"),
    )


def overview(conn: Connection) -> s.Overview:
    activity = [
        s.Activity.model_validate(row)
        for row in rows(
            conn,
            """
        SELECT kind,attempted_at AS at,message AS description FROM jobs
        ORDER BY attempted_at DESC,kind""",
        )
    ]
    return s.Overview(
        counts=counts(conn),
        mean_brier=mean_brier(conn),
        portfolio=portfolio(conn),
        activity=activity,
    )


def events(conn: Connection, event_id: str | None = None) -> list[s.EventView]:
    where = "" if event_id is None else " WHERE event_id=?"
    args = () if event_id is None else (event_id,)
    links = source_links(conn)
    forecasts: dict[str, s.ForecastView] = {}
    for r in rows(conn, "SELECT * FROM forecasts" + where + " ORDER BY generated_at,id", args):
        # Explorer shows the latest vintage. The evaluation ledger retains every vintage.
        forecasts[r["contract_id"]] = s.ForecastView(**r, observation_ids=links[r["id"]])
    resolutions = {
        r["contract_id"]: s.ResolutionView.model_validate(r)
        for r in rows(conn, "SELECT * FROM resolutions" + where, args)
    }
    issues = {
        r["contract_id"]: r["reason"] for r in rows(conn, "SELECT * FROM issues" + where, args)
    }
    contracts: dict[str, list[s.ContractView]] = defaultdict(list)
    for r in rows(conn, "SELECT * FROM contracts" + where + " ORDER BY lower,id", args):
        cid = r["id"]
        contracts[r["event_id"]].append(
            s.ContractView(
                **r,
                forecast=forecasts.get(cid),
                resolution=resolutions.get(cid),
                issue=issues.get(cid),
            )
        )
    event_filter = "" if event_id is None else " WHERE id=?"
    return [
        s.EventView(**r, contracts=contracts[r["id"]])
        for r in rows(conn, "SELECT * FROM events" + event_filter + " ORDER BY opens_at,id", args)
    ]


def event_detail(conn: Connection, event_id: str) -> s.EventDetail | None:
    selected = events(conn, event_id)
    if not selected:
        return None
    records = rows(
        conn, "SELECT * FROM observations WHERE event_id=? ORDER BY ingested_at,id", (event_id,)
    )
    observations = []
    for r in records:
        r["counts"] = json.loads(r["counts"])
        observations.append(s.ObservationView(**r))
    return s.EventDetail(**selected[0].model_dump(), observations=observations)


def models(conn: Connection) -> list[s.ModelView]:
    return [s.ModelView(**r) for r in rows(conn, "SELECT * FROM models ORDER BY id,version")]


def evaluations(conn: Connection) -> s.Evaluations:
    records = rows(
        conn,
        """SELECT v.*,e.id AS event_id,e.title AS event_title,c.label AS contract_label,
          f.model_id,f.model_version,f.probability,r.outcome
        FROM evaluations v JOIN forecasts f ON f.id=v.forecast_id
        JOIN contracts c ON c.id=v.contract_id JOIN events e ON e.id=c.event_id
        JOIN resolutions r ON r.id=v.resolution_id ORDER BY v.evaluated_at DESC,e.id,c.lower,c.id""",
    )
    return s.Evaluations(
        counts=counts(conn),
        mean_brier=mean_brier(conn),
        records=[s.EvaluationView(**r) for r in records],
    )


def health(conn: Connection, runtime: dict[str, Any]) -> s.Health:
    jobs = {r["kind"]: r for r in rows(conn, "SELECT * FROM jobs")}
    last_ingest = jobs.get("ingestion", {}).get("success_at")
    last_eval = jobs.get("evaluation", {}).get("success_at")
    affected = conn.exec_driver_sql("SELECT count(*) FROM issues").scalar_one()
    missing = conn.exec_driver_sql(
        "SELECT count(*) FROM (SELECT DISTINCT event_id,source FROM issues WHERE kind='missing')"
    ).scalar_one()
    warnings = [j["message"] for j in jobs.values() if j["status"] == "error"]
    source: str
    if jobs.get("ingestion", {}).get("status") == "error":
        source = "error"
    elif last_ingest is None:
        source = "uninitialized"
        warnings.append("Synthetic fixture has never been ingested.")
    elif affected:
        source = "incomplete"
        warnings.append(
            f"Source data missing or invalid for {affected} expected contract forecasts."
        )
    else:
        source = "ready"
    if last_ingest and last_eval is None:
        warnings.append("Fixture ingested. Evaluation has no successful run.")
    return s.Health.model_validate(
        {
            **runtime,
            "database": "connected",
            "source_status": source,
            "last_ingestion_at": last_ingest,
            "last_evaluation_at": last_eval,
            "missing_inputs": missing if last_ingest else None,
            "warnings": warnings,
        }
    )
