"""Immutable research records and validation shared by the synthetic pipeline."""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import fsum, isclose, isfinite
from typing import Literal

PARTITION_TOLERANCE = 1e-12


def require_utc(*times: datetime | None) -> None:
    for instant in times:
        if instant is not None and instant.utcoffset() != timedelta(0):
            raise ValueError("Timestamp must be timezone-aware UTC")


def probability(value: float) -> float:
    if isinstance(value, bool) or not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("Probability must be finite and in [0, 1]")
    return value


def brier_score(predicted: float, outcome: bool) -> float:
    if type(outcome) is not bool:
        raise ValueError("A resolved binary outcome is required")
    return (probability(predicted) - int(outcome)) ** 2


def validate_probability_partition(values: Iterable[float]) -> None:
    total = fsum(probability(value) for value in values)
    if not isclose(total, 1.0, rel_tol=0.0, abs_tol=PARTITION_TOLERANCE):
        raise ValueError("Probabilities for a complete partition must sum to one")


def unique[T](items: Iterable[T], label: str) -> set[T]:
    result: set[T] = set()
    for item in items:
        if item in result:
            raise ValueError(f"Duplicate {label}: {item}")
        result.add(item)
    return result


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    category: str
    description: str
    opens_at: datetime
    closes_at: datetime
    state: Literal["resolved", "unresolved"]

    def __post_init__(self) -> None:
        require_utc(self.opens_at, self.closes_at)
        if self.opens_at >= self.closes_at or self.state not in {"resolved", "unresolved"}:
            raise ValueError("Invalid event interval or lifecycle state")


@dataclass(frozen=True)
class Contract:
    id: str
    event_id: str
    label: str
    lower: int | None
    upper: int | None

    def __post_init__(self) -> None:
        if self.lower is not None and self.upper is not None and self.lower >= self.upper:
            raise ValueError("Numeric interval must have positive width")

    def contains(self, value: int) -> bool:
        if self.lower is None and self.upper is None:
            raise ValueError("Contract has no numeric interval")
        return (self.lower is None or self.lower <= value) and (
            self.upper is None or value < self.upper
        )


def validate_intervals(contracts: Sequence[Contract]) -> None:
    """Numeric intervals cover the whole number line with lower-inclusive cuts."""
    if len(contracts) < 2 or len({c.event_id for c in contracts}) != 1:
        raise ValueError("A partition requires multiple intervals for a single event")
    unique((c.id for c in contracts), "contract ID")
    if any(c.lower is None and c.upper is None for c in contracts):
        raise ValueError("A standalone binary contract is not a partition interval")
    ordered = sorted(contracts, key=lambda c: (c.lower is not None, c.lower or 0))
    if ordered[0].lower is not None or ordered[-1].upper is not None:
        raise ValueError("Partition requires unbounded outer intervals")
    for left, right in zip(ordered, ordered[1:], strict=False):
        if left.upper is None or left.upper != right.lower:
            raise ValueError("Partition contains a gap or overlap")


@dataclass(frozen=True)
class Observation:
    id: str
    event_id: str
    source: str
    issued_at: datetime | None
    available_at: datetime | None
    ingested_at: datetime
    provenance: str
    counts: tuple[tuple[str, int], ...]
    total: int

    def __post_init__(self) -> None:
        require_utc(self.issued_at, self.available_at, self.ingested_at)
        if self.issued_at is not None and self.issued_at > (self.available_at or self.ingested_at):
            raise ValueError("Observation issuance is out of order")
        if self.available_at is not None and self.available_at > self.ingested_at:
            raise ValueError("Observation ingestion precedes availability")
        unique((cid for cid, _ in self.counts), "observation count")
        if type(self.total) is not int or self.total <= 0:
            raise ValueError("Ensemble size must be a positive integer")
        for _, count in self.counts:
            if type(count) is not int or not 0 <= count <= self.total:
                raise ValueError("Ensemble count is outside its valid range")


@dataclass(frozen=True)
class Model:
    id: str
    version: str
    description: str
    status: str


@dataclass(frozen=True)
class Forecast:
    id: str
    event_id: str
    contract_id: str
    model_id: str
    model_version: str
    probability: float
    cutoff_at: datetime
    generated_at: datetime
    observation_ids: tuple[str, ...]
    quality: str

    def __post_init__(self) -> None:
        require_utc(self.cutoff_at, self.generated_at)
        probability(self.probability)
        if self.cutoff_at > self.generated_at:
            raise ValueError("Forecast generation precedes its information cutoff")
        if not self.observation_ids or self.quality != "valid":
            raise ValueError("A valid forecast requires traceable inputs")
        unique(self.observation_ids, "forecast observation")

    def validate_inputs(
        self, event: Event, contract: Contract, model: Model, observations: Sequence[Observation]
    ) -> None:
        if (
            self.event_id != event.id
            or self.contract_id != contract.id
            or contract.event_id != event.id
        ):
            raise ValueError("Forecast event and contract disagree")
        if (self.model_id, self.model_version) != (model.id, model.version):
            raise ValueError("Forecast model version mismatch")
        if not event.opens_at <= self.cutoff_at <= self.generated_at < event.closes_at:
            raise ValueError("Forecast falls outside the open event interval")
        if set(self.observation_ids) != unique((obs.id for obs in observations), "input"):
            raise ValueError("Forecast references an absent or unrelated observation")
        for obs in observations:
            if obs.event_id != event.id or contract.id not in dict(obs.counts):
                raise ValueError("Observation does not describe the forecast contract")
            if obs.available_at is None or max(obs.available_at, obs.ingested_at) > self.cutoff_at:
                raise ValueError("Input availability at the forecast cutoff is unverified")


@dataclass(frozen=True)
class Resolution:
    id: str
    event_id: str
    contract_id: str
    outcome: bool
    resolved_at: datetime
    available_at: datetime
    provenance: str

    def __post_init__(self) -> None:
        require_utc(self.resolved_at, self.available_at)
        if type(self.outcome) is not bool or self.resolved_at > self.available_at:
            raise ValueError("Invalid binary settlement or resolution chronology")

    def validate_contract(self, event: Event, contract: Contract) -> None:
        if (
            self.event_id != event.id
            or self.contract_id != contract.id
            or contract.event_id != event.id
        ):
            raise ValueError("Resolution event and contract disagree")
        if event.state != "resolved" or self.resolved_at < event.closes_at:
            raise ValueError("Resolution requires a closed, resolved event")


@dataclass(frozen=True)
class Evaluation:
    id: str
    forecast_id: str
    resolution_id: str
    metric: str
    score: float
    evaluated_at: datetime
    context: str


def evaluate(
    event: Event, contract: Contract, forecast: Forecast, resolution: Resolution, at: datetime
) -> Evaluation:
    require_utc(at)
    resolution.validate_contract(event, contract)
    if (forecast.event_id, forecast.contract_id) != (event.id, contract.id):
        raise ValueError("Scoring requires a forecast for the resolved contract")
    if not event.opens_at <= forecast.cutoff_at <= forecast.generated_at < event.closes_at:
        raise ValueError("Forecast falls outside the open event interval")
    if at < resolution.available_at:
        raise ValueError("Evaluation chronology would leak settlement information")
    return Evaluation(
        f"brier-{forecast.id}",
        forecast.id,
        resolution.id,
        "brier",
        brier_score(forecast.probability, resolution.outcome),
        at,
        "synthetic-replay-v1",
    )


@dataclass(frozen=True)
class Issue:
    id: str
    event_id: str
    contract_id: str
    source: str
    reason: str


@dataclass(frozen=True)
class Dataset:
    events: tuple[Event, ...]
    contracts: tuple[Contract, ...]
    observations: tuple[Observation, ...]
    models: tuple[Model, ...]
    forecasts: tuple[Forecast, ...]
    resolutions: tuple[Resolution, ...]
    evaluations: tuple[Evaluation, ...]
    issues: tuple[Issue, ...]

    def validate(self) -> None:
        """Check all cross-record references before persisting a fixture snapshot."""
        for ids in (
            [r.id for r in self.events],
            [r.id for r in self.contracts],
            [r.id for r in self.observations],
            [r.id for r in self.forecasts],
            [r.id for r in self.resolutions],
            [r.id for r in self.evaluations],
            [r.id for r in self.issues],
        ):
            unique(ids, "record ID")
        unique(((m.id, m.version) for m in self.models), "model version")
        unique((r.contract_id for r in self.resolutions), "settled contract")
        unique(
            ((f.model_id, f.model_version, f.contract_id, f.generated_at) for f in self.forecasts),
            "forecast vintage",
        )
        unique(((e.forecast_id, e.resolution_id, e.metric) for e in self.evaluations), "score")
        events = {r.id: r for r in self.events}
        contracts = {r.id: r for r in self.contracts}
        models = {(m.id, m.version): m for m in self.models}
        observations = {r.id: r for r in self.observations}
        forecasts = {r.id: r for r in self.forecasts}
        resolutions = {r.id: r for r in self.resolutions}
        groups: dict[str, list[Contract]] = defaultdict(list)
        partitions: set[str] = set()
        for c in self.contracts:
            if c.event_id not in events:
                raise ValueError("Contract references an unknown event")
            groups[c.event_id].append(c)
            if c.lower is not None or c.upper is not None:
                partitions.add(c.event_id)
        settlements: dict[str, list[Resolution]] = defaultdict(list)
        for r in self.resolutions:
            settlements[r.event_id].append(r)
        for event in self.events:
            group = groups[event.id]
            if not group:
                raise ValueError("Event has no contracts")
            settled = settlements[event.id]
            if event.state == "resolved" and {r.contract_id for r in settled} != {
                c.id for c in group
            }:
                raise ValueError("Resolved event requires settlement for every contract")
            if event.id in partitions:
                validate_intervals(group)
                if settled and sum(r.outcome for r in settled) != 1:
                    raise ValueError("Exactly one partition contract must resolve true")
        for obs in self.observations:
            group = groups.get(obs.event_id, [])
            count_map = dict(obs.counts)
            if not group or set(count_map) != {c.id for c in group}:
                raise ValueError("Observation count keys must match its event contracts")
            if obs.event_id in partitions and sum(count_map.values()) != obs.total:
                raise ValueError("Partition counts must cover the full ensemble")
        vintages: dict[tuple[str, str, str, datetime, datetime], list[Forecast]] = defaultdict(list)
        try:
            for f in self.forecasts:
                f.validate_inputs(
                    events[f.event_id],
                    contracts[f.contract_id],
                    models[f.model_id, f.model_version],
                    [observations[key] for key in f.observation_ids],
                )
                vintages[
                    f.event_id, f.model_id, f.model_version, f.cutoff_at, f.generated_at
                ].append(f)
            for (event_id, *_), vintage in vintages.items():
                group = groups[event_id]
                if event_id in partitions:
                    if {f.contract_id for f in vintage} != {c.id for c in group}:
                        raise ValueError("Partition forecast vintage is incomplete")
                    validate_probability_partition(f.probability for f in vintage)
            for r in self.resolutions:
                r.validate_contract(events[r.event_id], contracts[r.contract_id])
            for e in self.evaluations:
                forecast = forecasts[e.forecast_id]
                expected = evaluate(
                    events[forecast.event_id],
                    contracts[forecast.contract_id],
                    forecast,
                    resolutions[e.resolution_id],
                    e.evaluated_at,
                )
                if e != expected:
                    raise ValueError("Evaluation does not match its forecast and resolution")
            for issue in self.issues:
                if contracts[issue.contract_id].event_id != issue.event_id:
                    raise ValueError("Issue event and contract disagree")
        except KeyError as exc:
            raise ValueError(f"Missing referenced record: {exc}") from exc
        missing = unique((issue.contract_id for issue in self.issues), "missing contract forecast")
        predicted = {f.contract_id for f in self.forecasts}
        if missing & predicted or set(contracts) != missing | predicted:
            raise ValueError("Each fixture contract requires a forecast or an explicit input issue")
