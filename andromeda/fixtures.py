"""Version 1 of the local, fictional ensemble and settlement ledgers."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .domain import (
    Contract,
    Dataset,
    Evaluation,
    Event,
    Forecast,
    Issue,
    Model,
    Observation,
    Resolution,
    evaluate,
)

SOURCE = "Synthetic ensemble ledger"
MODEL = Model(
    "ensemble-frequency",
    "1.0.0",
    "Counts synthetic ensemble members satisfying each contract and divides by ensemble size.",
    "experimental",
)


def ensemble_forecast(
    event: Event,
    contract: Contract,
    observation: Observation,
    cutoff_at: datetime,
    generated_at: datetime,
) -> Forecast:
    """Replay a single forecast from recorded counts visible to the model."""
    counts = dict(observation.counts)
    if contract.id not in counts:
        raise ValueError("Ensemble has no count for this contract")
    forecast = Forecast(
        id=f"F-{contract.id}-v1",
        event_id=event.id,
        contract_id=contract.id,
        model_id=MODEL.id,
        model_version=MODEL.version,
        probability=counts[contract.id] / observation.total,
        cutoff_at=cutoff_at,
        generated_at=generated_at,
        observation_ids=(observation.id,),
        quality="valid",
    )
    forecast.validate_inputs(event, contract, MODEL, (observation,))
    return forecast


def temperature_contracts(event: Event) -> tuple[Contract, ...]:
    return (
        Contract(f"{event.id}-LOW", event.id, "Below 10 °C", None, 10),
        Contract(f"{event.id}-MID", event.id, "10 to below 20 °C", 10, 20),
        Contract(f"{event.id}-HIGH", event.id, "20 °C or higher", 20, None),
    )


@dataclass(frozen=True)
class FixtureEvent:
    event: Event
    contracts: tuple[Contract, ...]
    observation: Observation | None
    resolutions: tuple[Resolution, ...]


def ensemble_observation(
    event: Event,
    contracts: tuple[Contract, ...],
    counts: tuple[int, ...],
    total: int,
    issued_at: datetime | None,
) -> Observation:
    return Observation(
        id=f"O-{event.id}",
        event_id=event.id,
        source=SOURCE,
        issued_at=issued_at,
        available_at=event.opens_at + timedelta(hours=3, minutes=5),
        ingested_at=event.opens_at + timedelta(hours=3, minutes=8),
        provenance=f"Local synthetic ensemble ledger v1 / {event.id}",
        counts=tuple((c.id, n) for c, n in zip(contracts, counts, strict=True)),
        total=total,
    )


def settle(event: Event, contract: Contract, outcome: bool, ledger_note: str) -> Resolution:
    return Resolution(
        f"R-{contract.id}",
        event.id,
        contract.id,
        outcome,
        event.closes_at + timedelta(hours=1),
        event.closes_at + timedelta(hours=1, minutes=5),
        f"Local synthetic settlement ledger v1 / {event.id} / {ledger_note}",
    )


def source_events() -> Iterator[FixtureEvent]:
    """Read fictional facts from the ensemble and settlement ledgers."""
    temperature_rows: tuple[tuple[str, str, int, tuple[int, ...] | None, int | None], ...] = (
        ("T-ASTER", "Aster Reach", 10, (2, 5, 3), 14),
        ("T-BOREAL", "Boreal Sound", 11, (1, 3, 6), 20),
        ("T-CIRRUS", "Cirrus Bay", 12, None, 9),
        ("T-DELTA", "Delta Vale", 13, (4, 4, 2), None),
    )
    for event_id, station, day, counts, daily_high in temperature_rows:
        start = datetime(2026, 2, day, tzinfo=UTC)
        event = Event(
            event_id,
            f"{station} daily high",
            "Temperature",
            f"Highest whole-degree Celsius reading at the fictional {station} station "
            f"during {start:%Y-%m-%d} UTC.",
            start,
            start + timedelta(days=1),
            "unresolved" if daily_high is None else "resolved",
        )
        group = temperature_contracts(event)
        observation = (
            None
            if counts is None
            else ensemble_observation(event, group, counts, 10, start + timedelta(hours=3))
        )
        resolutions = (
            ()
            if daily_high is None
            else tuple(
                settle(event, c, c.contains(daily_high), f"daily high {daily_high} °C")
                for c in group
            )
        )
        yield FixtureEvent(event, group, observation, resolutions)

    start = datetime(2026, 2, 12, tzinfo=UTC)
    relay = Event(
        "B-RELAY",
        "Meridian relay check",
        "Systems",
        "Whether the fictional Meridian relay emits its scheduled confirmation on February 12 UTC.",
        start,
        start + timedelta(days=1),
        "resolved",
    )
    yes = Contract("B-RELAY-YES", relay.id, "Confirmation received", None, None)
    yield FixtureEvent(
        relay,
        (yes,),
        ensemble_observation(relay, (yes,), (3,), 4, issued_at=None),
        (settle(relay, yes, True, "scheduled confirmation received"),),
    )


def build_fixture() -> Dataset:
    """Replay the model against available inputs and score settled contracts."""
    ledger = tuple(source_events())
    forecasts: list[Forecast] = []
    evaluations: list[Evaluation] = []
    issues: list[Issue] = []
    for case in ledger:
        event = case.event
        settlements = {r.contract_id: r for r in case.resolutions}
        for contract in case.contracts:
            if case.observation is None:
                issues.append(
                    Issue(
                        f"I-{contract.id}",
                        event.id,
                        contract.id,
                        SOURCE,
                        "Expected ensemble observation absent at the forecast cutoff.",
                    )
                )
                continue
            forecast = ensemble_forecast(
                event,
                contract,
                case.observation,
                event.opens_at + timedelta(hours=4),
                event.opens_at + timedelta(hours=4, minutes=2),
            )
            forecasts.append(forecast)
            if contract.id in settlements:
                evaluations.append(
                    evaluate(
                        event,
                        contract,
                        forecast,
                        settlements[contract.id],
                        event.closes_at + timedelta(hours=2),
                    )
                )
    dataset = Dataset(
        events=tuple(case.event for case in ledger),
        contracts=tuple(c for case in ledger for c in case.contracts),
        observations=tuple(case.observation for case in ledger if case.observation is not None),
        models=(MODEL,),
        forecasts=tuple(forecasts),
        resolutions=tuple(r for case in ledger for r in case.resolutions),
        evaluations=tuple(evaluations),
        issues=tuple(issues),
    )
    dataset.validate()
    return dataset
