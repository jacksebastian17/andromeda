"""Immutable initial schema. Timestamps use fixed-width UTC ISO strings."""

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

# Store the event key in relationship tables so SQLite can enforce event membership
# through composite foreign keys even when a writer supplies a valid but unrelated ID.
DDL = (
    """CREATE TABLE events (
        id TEXT PRIMARY KEY NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL,
        description TEXT NOT NULL, opens_at TEXT NOT NULL, closes_at TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('resolved','unresolved')),
        CHECK(opens_at < closes_at)) STRICT""",
    """CREATE TABLE contracts (
        id TEXT PRIMARY KEY NOT NULL, event_id TEXT NOT NULL REFERENCES events(id),
        label TEXT NOT NULL, lower INTEGER, upper INTEGER,
        CHECK(lower IS NULL OR upper IS NULL OR lower < upper), UNIQUE(id,event_id)) STRICT""",
    """CREATE TABLE observations (
        id TEXT PRIMARY KEY NOT NULL, event_id TEXT NOT NULL REFERENCES events(id),
        source TEXT NOT NULL, issued_at TEXT, available_at TEXT, ingested_at TEXT NOT NULL,
        provenance TEXT NOT NULL, counts TEXT NOT NULL, total INTEGER NOT NULL CHECK(total>0),
        CHECK(issued_at <= available_at), CHECK(available_at <= ingested_at),
        UNIQUE(id,event_id)) STRICT""",
    """CREATE TABLE models (
        id TEXT NOT NULL, version TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL,
        PRIMARY KEY(id,version)) STRICT""",
    """CREATE TABLE forecasts (
        id TEXT PRIMARY KEY NOT NULL, event_id TEXT NOT NULL, contract_id TEXT NOT NULL,
        model_id TEXT NOT NULL, model_version TEXT NOT NULL,
        probability REAL NOT NULL CHECK(probability BETWEEN 0 AND 1), cutoff_at TEXT NOT NULL,
        generated_at TEXT NOT NULL, quality TEXT NOT NULL CHECK(quality='valid'),
        CHECK(cutoff_at <= generated_at), UNIQUE(id,event_id), UNIQUE(id,contract_id),
        UNIQUE(contract_id,model_id,model_version,cutoff_at),
        FOREIGN KEY(contract_id,event_id) REFERENCES contracts(id,event_id),
        FOREIGN KEY(model_id,model_version) REFERENCES models(id,version)) STRICT""",
    """CREATE TABLE forecast_sources (
        forecast_id TEXT NOT NULL, observation_id TEXT NOT NULL, event_id TEXT NOT NULL,
        PRIMARY KEY(forecast_id,observation_id),
        FOREIGN KEY(forecast_id,event_id) REFERENCES forecasts(id,event_id),
        FOREIGN KEY(observation_id,event_id) REFERENCES observations(id,event_id)) STRICT""",
    """CREATE TRIGGER forecast_source_cutoff BEFORE INSERT ON forecast_sources
        WHEN EXISTS (SELECT 1 FROM forecasts f JOIN observations o ON o.id=NEW.observation_id
          WHERE f.id=NEW.forecast_id AND (o.available_at IS NULL OR o.available_at>f.cutoff_at
            OR o.ingested_at>f.cutoff_at))
        BEGIN SELECT RAISE(ABORT, 'source unavailable at forecast cutoff'); END""",
    """CREATE TABLE resolutions (
        id TEXT PRIMARY KEY NOT NULL, event_id TEXT NOT NULL, contract_id TEXT NOT NULL UNIQUE,
        outcome INTEGER NOT NULL CHECK(outcome IN (0,1)), resolved_at TEXT NOT NULL,
        available_at TEXT NOT NULL, provenance TEXT NOT NULL, CHECK(resolved_at<=available_at),
        UNIQUE(id,contract_id), FOREIGN KEY(contract_id,event_id)
        REFERENCES contracts(id,event_id)) STRICT""",
    """CREATE TRIGGER resolution_lifecycle BEFORE INSERT ON resolutions
        WHEN EXISTS (SELECT 1 FROM events WHERE id=NEW.event_id AND
          (state<>'resolved' OR closes_at>NEW.resolved_at))
        BEGIN SELECT RAISE(ABORT, 'event unresolved or before close'); END""",
    """CREATE TABLE evaluations (
        id TEXT PRIMARY KEY NOT NULL, contract_id TEXT NOT NULL, forecast_id TEXT NOT NULL,
        resolution_id TEXT NOT NULL, metric TEXT NOT NULL CHECK(metric='brier'),
        score REAL NOT NULL CHECK(score BETWEEN 0 AND 1), evaluated_at TEXT NOT NULL,
        context TEXT NOT NULL, UNIQUE(forecast_id,resolution_id,metric,context),
        FOREIGN KEY(forecast_id,contract_id) REFERENCES forecasts(id,contract_id),
        FOREIGN KEY(resolution_id,contract_id) REFERENCES resolutions(id,contract_id)) STRICT""",
    """CREATE TRIGGER evaluation_cutoff BEFORE INSERT ON evaluations
        WHEN EXISTS (SELECT 1 FROM resolutions r JOIN forecasts f ON f.id=NEW.forecast_id
          WHERE r.id=NEW.resolution_id AND
          (r.available_at>NEW.evaluated_at OR f.generated_at>=r.resolved_at))
        BEGIN SELECT RAISE(ABORT, 'evaluation timeline invalid'); END""",
    """CREATE TABLE issues (
        id TEXT PRIMARY KEY NOT NULL, event_id TEXT NOT NULL, contract_id TEXT NOT NULL UNIQUE,
        source TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('missing','invalid')),
        reason TEXT NOT NULL, FOREIGN KEY(contract_id,event_id) REFERENCES contracts(id,event_id)
        ) STRICT""",
    """CREATE TABLE portfolio (
        id INTEGER PRIMARY KEY CHECK(id=1), starting_cents INTEGER NOT NULL CHECK(starting_cents>=0),
        current_cents INTEGER NOT NULL CHECK(current_cents=starting_cents),
        realized_cents INTEGER NOT NULL CHECK(realized_cents=0)) STRICT""",
    """CREATE TABLE jobs (
        kind TEXT PRIMARY KEY NOT NULL CHECK(kind IN ('ingestion','evaluation')),
        attempted_at TEXT NOT NULL, success_at TEXT, message TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('ok','error'))) STRICT""",
    "CREATE INDEX contracts_event ON contracts(event_id)",
    "CREATE INDEX observations_event ON observations(event_id)",
    "CREATE INDEX forecasts_contract_time ON forecasts(contract_id,generated_at DESC)",
    "CREATE INDEX evaluations_recent ON evaluations(evaluated_at DESC)",
)


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)


def downgrade() -> None:
    for table in (
        "jobs",
        "portfolio",
        "issues",
        "evaluations",
        "resolutions",
        "forecast_sources",
        "forecasts",
        "models",
        "observations",
        "contracts",
        "events",
    ):
        op.execute(f"DROP TABLE {table}")
