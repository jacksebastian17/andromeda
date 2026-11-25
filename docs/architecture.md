# A1 architecture and API

## Repository map

| Location | Responsibility |
| --- | --- |
| `andromeda/domain.py` | Immutable event, contract, observation, model, forecast, resolution and evaluation records. Validates relationships, partitions, probabilities, input availability and scoring chronology. |
| `andromeda/fixtures.py` | Local ensemble and settlement source adapter, deterministic model and replay assembly. The temperature-specific units and boundaries live here. |
| `andromeda/database.py`, `migrations/`, `alembic.ini` | Connection configuration, exact starting cash parsing, migration entry point and frozen schema revision. |
| `andromeda/storage.py` | Atomic ingest, evaluation against persisted records, immutable record conflict checking, paper ledger initialization and job outcomes. |
| `andromeda/queries.py` | Consistent read snapshots, counts, contract inspection, Brier aggregation and exact USD serialization. |
| `andromeda/api.py`, `andromeda/schemas.py` | FastAPI lifecycle, loopback host/CORS policy, typed Pydantic read models and HTTP errors. |
| `andromeda/__main__.py` | Explicit migration, ingest, evaluation and serve commands. |
| `frontend/src/` | React/TypeScript terminal, routes and shared components. TanStack Query polls visible resources. Tailwind and local CSS provide layout and visual styles. |
| `tests/`, `frontend/src/App.test.tsx`, `frontend/e2e/` | Independent mathematical expectations, real SQLite/API tests, component tests and live browser checks. |
| `requirements.txt`, `frontend/package-lock.json` | Pinned environment for local development and verification. |
| `.github/workflows/verify.yml` | GitHub Actions configuration for Python, frontend and browser checks. |

A single Python process serves the research API. SQLite is the boundary between the operator's writer commands and independent read clients. The browser has no credentials and cannot initiate jobs. The next milestone can introduce a permitted adapter or analysis family without changing the accounting ledger. A structural discrepancy would need its own result schema. The current evaluation table represents binary probability forecasts.

## Persistence and clocks

Migration `0001_foundation` creates SQLite STRICT tables, composite foreign keys, unique constraints and read indexes. Every connection enables foreign keys. The migrator establishes WAL and commits DDL transactionally. The API opens an existing database in URI read-only mode and checks the expected schema revision. Opening the terminal cannot create an empty database at a misspelled path.

An event has many binary contracts. An observation belongs to an event and stores its source, provenance, count payload and independent issued, available and received times. Forecasts identify both the event and contract, reference a specific model version and link to observations through a join table. A missing input creates a contract-level issue. A contract resolution carries a known binary outcome, settlement time, availability time and provenance. Evaluation references must identify a forecast and resolution for the same contract.

A1 permits one forecast per `(contract_id, model_id, model_version, cutoff_at)`. The information cutoff defines the information horizon, and `generated_at` records when the model produced the result. Domain validation and SQLite both enforce cutoff uniqueness. A later generation time cannot create a second forecast at the same cutoff. Distinct cutoffs can share a generation time. Partition validation groups forecasts by event, model version and cutoff so each probability vector represents a shared information horizon. The forecast ID remains the stable row reference for evaluations and source links, and replays must match its immutable fields and source references.

Application validation checks event windows, finite probabilities, known input availability and receipt at cutoff, complete partitions and resolution eligibility. Composite foreign keys also enforce event membership. Insert triggers guard source cutoffs and evaluation chronology. The CLI is the supported research writer. SQLite access outside the application is a trusted local administrative capability. All persisted timestamp strings use six fractional digits and UTC `Z` for lexical time comparisons.

A writer takes a SQLite `BEGIN IMMEDIATE` lock before comparing and inserting immutable records. Replaying the fixture verifies existing fields and source references. Conflicting immutable data causes the entire research transaction to roll back. Job state records one latest attempt and last success per operation, and reports a failure separately if storage can still be reached. Wall-clock job activity advances on successful replays. The scientific records have deterministic replay timestamps. An API response uses one read transaction, including responses assembled from several tables.

The single portfolio row stores opening cash, current cash and realized P&L in signed integer cents. Database checks enforce the A1 cash-only invariant. Zero positions and transactions follow from the absence of an execution ledger. The API emits monetary amounts as decimal strings. Return and win rate are nullable. Keep the accounting and hypothetical economic evaluation boundaries separate in future schema migrations.

## Local read API

Every research endpoint uses HTTP GET under `/api/v1`. Responses are JSON and timestamps include the UTC designation. The corresponding machine-readable types are available at `/openapi.json`.

| Path | Successful response |
| --- | --- |
| `/health` | Actual process version, mode, startup time, monotonic uptime, database status, source state, latest successful jobs and warnings. Missing inputs count distinct event/source pairs. |
| `/overview` | Counts, equally weighted mean binary Brier score, optional paper portfolio and most recent attempt per job type. |
| `/events` | Events with contracts, latest forecast per contract, optional resolution and input issue. |
| `/events/{event_id}` | Event and all its contracts, plus observation payloads, timestamps and provenance. |
| `/research/models` | Registered model identities, versions, descriptions and experimental status. |
| `/research/evaluations` | Counts, mean Brier and scored records with model, probability, outcome, resolution reference and replay context. |
| `/portfolio` | Exact USD balances, position and transaction counts, realized P&L and nullable history-dependent metrics. |

An empty migrated database returns empty collections and null aggregates. An unknown event and an uninitialized portfolio return 404 with a detail message. A database failure or schema mismatch returns 503. Health retains process diagnostics and marks inaccessible data unavailable. A successfully ingested fixture with a missing source reports `incomplete` and remains readable. A failed ingestion reports `error` with the previous successful ingestion time if available.

The browser polls every five seconds. Failed polls withdraw cached metrics from presentation and show their last successful response time. A snapshot older than fifteen seconds is treated as stale even before another successful request. Requests time out after eight seconds. The System Health page can display a reachable backend's structured 503 diagnostics. Browser navigation and sampling have no effect on evaluation or ingestion.

## Operating limits

The expected corpus fits comfortably in memory for inspection. Endpoints return complete fixture collections and the Explorer displays each contract's latest forecast. A1 has no continuous external source, historical job audit log, background scheduler, user authentication or multi-user hosting. The loopback development service assumes a trusted desktop. External collection, persistence permissions, model validation against genuine outcomes and realistic costs are separate future research decisions.
