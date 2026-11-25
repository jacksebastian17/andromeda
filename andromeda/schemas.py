"""Read models shared by response validation and the generated OpenAPI contract."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field

Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class Health(BaseModel):
    version: str
    mode: Literal["synthetic research / paper only"] = "synthetic research / paper only"
    started_at: AwareDatetime
    uptime_seconds: float
    database: Literal["connected", "unavailable"]
    source_status: Literal["unavailable", "uninitialized", "ready", "incomplete", "error"]
    last_ingestion_at: AwareDatetime | None
    last_evaluation_at: AwareDatetime | None
    missing_inputs: int | None
    warnings: list[str]


class Counts(BaseModel):
    events: int
    contracts: int
    forecasts: int
    resolved_events: int
    evaluated_forecasts: int
    missing_forecasts: int
    invalid_forecasts: int
    unresolved_forecasts: int


class Portfolio(BaseModel):
    currency: Literal["USD"] = "USD"
    starting_cash: str
    current_cash: str
    realized_pnl: str
    open_positions: int = 0
    transactions: int = 0
    return_pct: None = None
    win_rate: None = None


class Activity(BaseModel):
    kind: str
    at: AwareDatetime
    description: str


class Overview(BaseModel):
    counts: Counts
    mean_brier: Probability | None
    portfolio: Portfolio | None
    activity: list[Activity]


class ForecastView(BaseModel):
    id: str
    probability: Probability
    model_id: str
    model_version: str
    generated_at: AwareDatetime
    cutoff_at: AwareDatetime
    observation_ids: list[str]
    quality: str


class ResolutionView(BaseModel):
    outcome: bool
    resolved_at: AwareDatetime
    available_at: AwareDatetime
    provenance: str


class ContractView(BaseModel):
    id: str
    label: str
    lower: int | None
    upper: int | None
    forecast: ForecastView | None
    resolution: ResolutionView | None
    issue: str | None


class EventView(BaseModel):
    id: str
    title: str
    category: str
    description: str
    opens_at: AwareDatetime
    closes_at: AwareDatetime
    state: Literal["resolved", "unresolved"]
    contracts: list[ContractView]


class ObservationView(BaseModel):
    id: str
    source: str
    issued_at: AwareDatetime | None
    available_at: AwareDatetime | None
    ingested_at: AwareDatetime
    provenance: str
    counts: dict[str, int]
    total: int


class EventDetail(EventView):
    observations: list[ObservationView]


class ModelView(BaseModel):
    id: str
    version: str
    description: str
    status: str


class EvaluationView(BaseModel):
    id: str
    event_id: str
    event_title: str
    contract_id: str
    contract_label: str
    forecast_id: str
    model_id: str
    model_version: str
    resolution_id: str
    probability: Probability
    outcome: bool
    metric: Literal["brier"]
    score: Probability
    evaluated_at: AwareDatetime
    context: str


class Evaluations(BaseModel):
    counts: Counts
    mean_brier: Probability | None
    records: list[EvaluationView]
