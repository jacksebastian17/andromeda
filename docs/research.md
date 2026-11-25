# Synthetic research ledger

The A1 replay answers one reproducibility question. Given a known set of fictional observations, does the system persist the expected forecasts, withhold them when input is missing, and score exactly the forecasts whose outcomes are known?

## Corpus and independent scoring oracle

Each temperature contract settles true if the fictional station's daily maximum falls in its specified interval. All UTC days run from midnight inclusive to the following midnight exclusive. The intervals below cover the full temperature range and share no readings. Their first two upper endpoints are exclusive. The last interval includes exactly 20 °C.

| Event | UTC date in 2026 | Ensemble counts in interval order | Settlement | Forecast probabilities | Expected binary Brier scores |
| --- | --- | --- | --- | --- | --- |
| T-ASTER · Aster Reach | Feb 10 | 2, 5, 3 of 10 | 14 °C | .20, .50, .30 | .0400, .2500, .0900 |
| T-BOREAL · Boreal Sound | Feb 11 | 1, 3, 6 of 10 | 20 °C | .10, .30, .60 | .0100, .0900, .1600 |
| T-CIRRUS · Cirrus Bay | Feb 12 | Missing observation | 9 °C | Unavailable for all three | Unavailable |
| T-DELTA · Delta Vale | Feb 13 | 4, 4, 2 of 10 | Unresolved | .40, .40, .20 | Unavailable |
| B-RELAY · Meridian relay | Feb 12 | 3 confirmations of 4 | Confirmation received | .75 | .0625 |

The temperature interval order is below 10 °C, 10 to below 20 °C, and 20 °C or higher. The generic Meridian event has one binary YES contract whose complement is implicit. Its probability can take any finite value in [0, 1].

For one contract with forecast probability `p` and resolved binary outcome `y`, the score is `(p − y)²`. For example, Boreal Sound settled in the highest interval. Its observed outcomes are 0, 0 and 1. Squaring the errors gives .01, .09 and .16. The relay settled YES, giving (.75 − 1)² = .0625. Smaller scores indicate lower squared probability error.

| Expected count | Value |
| --- | ---: |
| Underlying events | 5 |
| Binary contracts | 13 |
| Available source observations | 4 |
| Missing source observations | 1 |
| Resolved events | 4 |
| Persisted contract resolutions | 10 |
| Valid forecasts | 10 |
| Missing forecasts due to the absent observation | 3 |
| Invalid forecasts persisted | 0 |
| Forecasts with unresolved outcomes | 3 |
| Evaluated forecasts | 7 |
| Distinct underlying events contributing scores | 3 |

The reported mean weights each evaluated contract equally. The score sum is .38 + .26 + .0625 = .7025. Dividing by 7 gives **.10035714285714286**. Two of the scored events contribute three related binary scores each, and the relay contributes one. The seven scores share only three underlying events. This fixture supplies neither a statistical independence assumption nor a market benchmark. No price, order, cost, trade, or profit enters this calculation.

## Inputs and clocks

The local adapter describes synthetic ensemble counts, the ensemble size, contract definitions, and an independent fictional settlement ledger. Counts are nonnegative integers. An interval partition must cover the full ensemble. The deterministic model `ensemble-frequency` version `1.0.0` divides the named contract count by the ensemble size. The model takes one event, one contract, one observation, a cutoff and a generation timestamp. It never consumes a resolution. Every successful forecast references the exact available observation and model version. A complete forecast partition must sum to one within absolute tolerance `1e-12` with zero relative tolerance.

Observation, forecast, settlement, and evaluation record times use a fixed synthetic replay clock. All timestamps have an explicit UTC offset. On each event day, modeled observations are issued at 03:00, become available to the source's consumer at 03:05, and are recorded by the synthetic receiver at 03:08. Meridian's issuance time is unknown and stays null. The information cutoff is 04:00 and generation is at 04:02. Both availability and receipt must be known to be at or before the cutoff. A forecast must be generated strictly before event close. An absent observation produces a per-contract issue with no forecast row.

For resolved events, fictional settlement occurs one hour after closing midnight. Consumers can access the settlement five minutes later. Evaluation uses closing midnight plus two hours and rejects a resolution from the future or from another event or contract. The unresolved Delta record intentionally remains in its fixture state as the operator's wall clock advances.

Runtime activity records use the operator's actual UTC clock when local ingestion and evaluation jobs run. Repeating the replay can update job activity while preserving the same research IDs, times, probabilities, and scores.

## Extension boundaries

The concrete observations in A1 are a count-based ensemble format. Another source can supply its own validated payload and explicit availability semantics. Another model can produce forecasts tied to those inputs. The binary scoring formula requires only a probability and an authoritative contract outcome. Numeric interval checks are generic, and the temperature adapter defines units and cut points. A future structural analysis can store its own result type alongside forecast records.

All records in this ledger are original fictional fixtures. No predecessor code, exchange records, or external observations were used.
