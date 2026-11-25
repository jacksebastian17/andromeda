from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from math import inf, nan
from statistics import mean

import pytest

from andromeda.domain import (
    Contract,
    Dataset,
    brier_score,
    evaluate,
    probability,
    validate_intervals,
    validate_probability_partition,
)
from andromeda.fixtures import build_fixture, ensemble_forecast


@pytest.fixture
def data() -> Dataset:
    return build_fixture()


@pytest.mark.parametrize("p", [0, 0.125, 1])
def test_valid_probability_boundaries(p: float) -> None:
    assert probability(p) == p


@pytest.mark.parametrize("p", [-0.000001, 1.000001, nan, inf, -inf, True])
def test_invalid_probabilities(p: float) -> None:
    with pytest.raises(ValueError, match="Probability"):
        probability(p)


@pytest.mark.parametrize(
    ("p", "outcome", "expected"),
    [(0, False, 0), (1, False, 1), (0.75, True, 0.0625), (0.25, False, 0.0625)],
)
def test_hand_scored_binary_examples(p: float, outcome: bool, expected: float) -> None:
    assert brier_score(p, outcome) == expected


def test_missing_outcome_cannot_be_scored() -> None:
    with pytest.raises(ValueError, match="resolved binary"):
        brier_score(0.1, None)  # type: ignore[arg-type]


def test_probability_partition_tolerance() -> None:
    validate_probability_partition([0.1, 0.2, 0.7])
    validate_probability_partition([0.5, 0.5 - 1e-13])
    for invalid in ([0.6, 0.400000001], [], [nan, 0.6], [-0.1, 1.1]):
        with pytest.raises(ValueError):
            validate_probability_partition(invalid)


@pytest.mark.parametrize(
    ("reading", "truth"),
    [
        (9, [True, False, False]),
        (10, [False, True, False]),
        (19, [False, True, False]),
        (20, [False, False, True]),
    ],
)
def test_partition_boundaries(data: Dataset, reading: int, truth: list[bool]) -> None:
    group = data.contracts[:3]
    validate_intervals(tuple(reversed(group)))
    assert [c.contains(reading) for c in group] == truth


@pytest.mark.parametrize(
    "bounds",
    [
        [(None, 0), (1, None)],
        [(None, 0), (-1, None)],
        [(0, 5), (5, None)],
        [(None, 0), (0, 5)],
        [(None, None), (0, None)],
        [(None, 0), (0, 0)],
    ],
)
def test_invalid_partitions(bounds: list[tuple[int | None, int | None]]) -> None:
    with pytest.raises(ValueError):
        validate_intervals(
            [Contract(str(i), "one-event", str(i), lo, hi) for i, (lo, hi) in enumerate(bounds)]
        )


def test_full_reproducible_replay(data: Dataset) -> None:
    assert data == build_fixture()
    assert len(data.events) == 5
    assert len(data.contracts) == 13
    assert len(data.observations) == 4
    assert len(data.forecasts) == 10
    assert len(data.resolutions) == 10
    assert sum(e.state == "resolved" for e in data.events) == 4
    assert len(data.evaluations) == 7
    assert len(data.issues) == 3
    by_forecast = {f.id: f for f in data.forecasts}
    # Independent arithmetic for each fixture contract, including boundary settlement.
    expected = {
        "T-ASTER-LOW": 0.04,
        "T-ASTER-MID": 0.25,
        "T-ASTER-HIGH": 0.09,
        "T-BOREAL-LOW": 0.01,
        "T-BOREAL-MID": 0.09,
        "T-BOREAL-HIGH": 0.16,
        "B-RELAY-YES": 0.0625,
    }
    observed = {by_forecast[v.forecast_id].contract_id: v.score for v in data.evaluations}
    assert observed == pytest.approx(expected, abs=1e-12)
    assert mean(observed.values()) == pytest.approx(0.10035714285714286)
    assert {by_forecast[e.forecast_id].event_id for e in data.evaluations} == {
        "T-ASTER",
        "T-BOREAL",
        "B-RELAY",
    }


def test_missing_and_unresolved_have_different_denominators(data: Dataset) -> None:
    assert {i.contract_id for i in data.issues} == {"T-CIRRUS-LOW", "T-CIRRUS-MID", "T-CIRRUS-HIGH"}
    assert not any(o.event_id == "T-CIRRUS" for o in data.observations)
    assert not any(f.event_id == "T-CIRRUS" for f in data.forecasts)
    assert not any(r.event_id == "T-DELTA" for r in data.resolutions)
    scored = {e.forecast_id for e in data.evaluations}
    assert [f.event_id for f in data.forecasts if f.id not in scored] == ["T-DELTA"] * 3
    assert next(o for o in data.observations if o.event_id == "B-RELAY").issued_at is None


def test_forecast_identity_rejects_same_cutoff_generated_later(data: Dataset) -> None:
    relay = next(f for f in data.forecasts if f.contract_id == "B-RELAY-YES")
    duplicate = replace(
        relay, id="duplicate", generated_at=relay.generated_at + timedelta(seconds=1)
    )

    with pytest.raises(ValueError, match="Duplicate forecast vintage"):
        replace(data, forecasts=(*data.forecasts, duplicate)).validate()


def test_forecast_identity_accepts_distinct_cutoffs_generated_together(data: Dataset) -> None:
    relay = next(f for f in data.forecasts if f.contract_id == "B-RELAY-YES")
    later_cutoff = replace(
        relay, id="later-cutoff", cutoff_at=relay.cutoff_at + timedelta(seconds=1)
    )

    replace(data, forecasts=(*data.forecasts, later_cutoff)).validate()


def test_partition_vintage_uses_shared_cutoff(data: Dataset) -> None:
    first, *rest = data.forecasts
    generated_later = replace(first, generated_at=first.generated_at + timedelta(seconds=1))
    replace(data, forecasts=(generated_later, *rest)).validate()

    different_cutoff = replace(first, cutoff_at=first.cutoff_at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="Partition forecast vintage is incomplete"):
        replace(data, forecasts=(different_cutoff, *rest)).validate()


@pytest.mark.parametrize("mode", ["unknown", "late-source", "late-receipt"])
def test_forecast_uses_only_known_inputs_at_cutoff(data: Dataset, mode: str) -> None:
    obs = data.observations[0]
    forecast = data.forecasts[0]
    later = forecast.cutoff_at + timedelta(seconds=1)
    if mode == "unknown":
        obs = replace(obs, available_at=None)
    elif mode == "late-source":
        obs = replace(obs, available_at=later, ingested_at=later)
    else:
        obs = replace(obs, ingested_at=later)
    with pytest.raises(ValueError, match="cutoff"):
        ensemble_forecast(
            data.events[0], data.contracts[0], obs, forecast.cutoff_at, forecast.generated_at
        )


def test_inclusive_input_cutoff(data: Dataset) -> None:
    f, obs = data.forecasts[0], data.observations[0]
    obs_at_cutoff = replace(obs, available_at=f.cutoff_at, ingested_at=f.cutoff_at)
    assert (
        ensemble_forecast(
            data.events[0], data.contracts[0], obs_at_cutoff, f.cutoff_at, f.cutoff_at
        ).probability
        == 0.2
    )


def test_invalid_forecast_references(data: Dataset) -> None:
    first, *rest = data.forecasts
    for bad in [
        replace(first, event_id=data.events[1].id),
        replace(first, contract_id=data.contracts[3].id),
        replace(first, observation_ids=("nonexistent",)),
        replace(first, observation_ids=(data.observations[1].id,)),
        replace(first, model_version="unknown"),
        replace(first, generated_at=data.events[0].closes_at),
    ]:
        with pytest.raises(ValueError):
            replace(data, forecasts=(bad, *rest)).validate()


def test_timezones_and_chronology(data: Dataset) -> None:
    obs = data.observations[0]
    for invalid in [
        datetime(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
    ]:
        with pytest.raises(ValueError, match="UTC"):
            replace(obs, ingested_at=invalid)
    with pytest.raises(ValueError, match="ingestion precedes"):
        replace(obs, available_at=obs.ingested_at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="issuance"):
        replace(obs, issued_at=obs.ingested_at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="generation precedes"):
        replace(data.forecasts[0], cutoff_at=datetime(2030, 1, 1, tzinfo=UTC))


def test_evaluation_rejects_wrong_contract_unresolved_and_early_access(data: Dataset) -> None:
    e, c, f, r = data.events[0], data.contracts[0], data.forecasts[0], data.resolutions[0]
    with pytest.raises(ValueError, match="disagree"):
        evaluate(e, c, f, data.resolutions[1], r.available_at)
    with pytest.raises(ValueError, match="resolved event"):
        evaluate(replace(e, state="unresolved"), c, f, r, r.available_at)
    with pytest.raises(ValueError, match="chronology"):
        evaluate(e, c, f, r, r.available_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="resolved contract"):
        evaluate(e, c, data.forecasts[1], r, r.available_at)


def test_snapshot_rejects_bad_scores_partial_or_inconsistent_partitions(data: Dataset) -> None:
    first, *rest = data.evaluations
    with pytest.raises(ValueError, match="Evaluation does not match"):
        replace(data, evaluations=(replace(first, score=0.9), *rest)).validate()
    with pytest.raises(ValueError, match="incomplete"):
        replace(data, forecasts=data.forecasts[1:]).validate()
    f, *other_forecasts = data.forecasts
    with pytest.raises(ValueError, match="sum to one"):
        replace(data, forecasts=(replace(f, probability=0.3), *other_forecasts)).validate()
    r, *other_resolutions = data.resolutions
    with pytest.raises(ValueError, match="one partition contract"):
        replace(data, resolutions=(replace(r, outcome=True), *other_resolutions)).validate()


def test_malformed_ensemble_cannot_create_valid_results(data: Dataset) -> None:
    first, *rest = data.observations
    with pytest.raises(ValueError, match="size"):
        replace(first, total=0)
    with pytest.raises(ValueError, match="Duplicate"):
        replace(first, counts=first.counts + first.counts)
    with pytest.raises(ValueError, match="count keys"):
        replace(data, observations=(replace(first, counts=first.counts[1:]), *rest)).validate()
    with pytest.raises(ValueError, match="full ensemble"):
        replace(data, observations=(replace(first, total=11), *rest)).validate()


def test_fixture_requires_explicit_and_consistent_forecast_coverage(data: Dataset) -> None:
    with pytest.raises(ValueError, match="explicit input issue"):
        replace(data, issues=data.issues[1:]).validate()
    forecast = data.forecasts[0]
    contradictory = replace(
        data.issues[0], id="extra", event_id=forecast.event_id, contract_id=forecast.contract_id
    )
    with pytest.raises(ValueError, match="explicit input issue"):
        replace(data, issues=(*data.issues, contradictory)).validate()
