# E1 complementary NBA contract consistency

**INCONCLUSIVE — insufficient or ambiguous evidence.** Two of 136 same-minute quote pairs were incompatible at their printed closes, one on the ask side and one on the bid side. Neither gap exceeded one cent per $1 of ordinary settlement. Both disappeared when the intervals used the printed within-minute ranges. Neither survived any positive fee scenario. The May 2026 series and event fee history remains unverified. This sample gives no economic reason to expand historical acquisition or build execution tooling.

## Sample and comparable observations

The six prespecified A3.0 NBA development pairs represent six distinct games and 12 contracts. Some games can share teams or series-level information. Each game is one observational unit, with repeated minutes within it. Each event had a complete two-contract roster, shared opening and cutoff clocks, two distinct team identities, mutually exclusive event metadata, a shared settlement source and matching dated full-game winner predicates for $1 binary contracts. The primary rules matched after replacing the named winner. All archived secondary summaries were empty. Kalshi’s later basketball game-winner filing documents that some cancellations, suspensions and delays can resolve at a fair price. The May archive cannot establish the contemporaneous exception terms or guarantee a joint $1 payout in those cases. [A3.0 report](a3-0-campaign.md) · [Kalshi’s June 2026 product filing](https://www.cftc.gov/filings/ptc/ptc0623267144.pdf)

There were **354** eligible game-minute slots and **708** contract-minute slots under the frozen 60-second lag. Of the latter, **344** (48.6%) were absent. There were no conflicting rows or unusable quote intervals among the 364 returned contract-minutes, but 190 lacked a fresh trade close. Both contracts had quote intervals in **136 of 354** game-minutes (38.4%) across all six games. Only **45** game-minutes across five games had fresh trades on both sides. Among 292 adjacent observed contract-minute transitions, **190** repeated the same bid and ask. Repetition and zero trade volume cannot distinguish a resting quote from a stale one. Missing periods stayed missing. [Frozen protocol](e1-protocol.md) · [Kalshi candle schema](https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks)

| Comparison | Last-trade sums different from $1 | Bid–ask sums excluding $1 |
| --- | ---: | ---: |
| Latest individually eligible closes | 6 / 6 | 0 / 6 |
| Latest common quote minute per game | 2 / 2 | 0 / 6 |
| Latest common trade minute per game | 4 / 5 | 0 / 5 |
| All common minute ends | 40 / 45 | 2 / 136 |
| Second contract shifted one minute earlier | 38 / 39 | 1 / 125 |
| Second contract shifted one minute later | 36 / 42 | 1 / 124 |

Five of the six latest-individual comparisons used different minute ends. The five nonzero time gaps totaled 56 minutes and spanned up to 39 minutes. Across same-minute comparisons the equal-game mean absolute trade-sum deviation was **13.40¢**, with an aggregate maximum of **64¢**. Under the deliberate earlier and later shifts, the means were **1.64¢** and **1.24¢** respectively. The shifts change the available observations and cannot isolate a causal effect of timestamp mismatch. Even trades in the same minute can occur at different times within it. The size of a last-trade discrepancy does not measure the distance between the quoted intervals.

On the 136 matched quote minutes, midpoint sums deviated from $1 in **112** cases. The equal-game mean absolute midpoint deviation was **4.67¢** and the mean combined spread was **84.64¢** across two $1 contracts. The two quote incompatibilities, in two games, were a combined ask below $1 and a combined bid above $1. Using 0 and 120 seconds of publication lag changed coverage to 140 and 132 quote minutes, respectively, with two close incompatibilities in each. Both original gaps had usable within-minute ranges. The widened intervals overlapped in **all 130** minutes with complete ranges. On the 45 minutes with trades in both contracts there were **zero** close incompatibilities. A printed range still cannot establish which quotes coexisted or when they became visible.

## Cost sensitivity and decision

The indexed official February 5, 2026 fee schedule gave a general immediately matched fee of `0.07 × C × p × (1 − p)`, rounded up to cents. The live PDF now serves a July 7 revision with a different rounding convention. Kalshi’s April help page confirms market-specific fees and its API documentation distinguishes series changes from event overrides. The six archived event snapshots show no override, but they cannot establish which multiplier, fee type, rounding convention or waiver was in effect for these events in May. The zero, half, standard and double coefficient rows below are explicit sensitivities using the February cent-rounding convention. [Indexed February schedule URL](https://kalshi.com/docs/kalshi-fee-schedule.pdf?trk=public_post_comment-text) · [April help page](https://help.kalshi.com/en/articles/13823805-fees) · [July schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf) · [Series fee history](https://docs.kalshi.com/api-reference/exchange/get-series-fee-changes) · [Event fee history](https://docs.kalshi.com/api-reference/events/get-event-fee-changes)

| Coefficient on `p(1−p)`, per $1 contract, two separately rounded fees | Positive residuals / 136 | Largest positive residual |
| --- | ---: | ---: |
| 0% frictionless bound | 2 | 1¢ |
| 3.5% sensitivity | 0 | 0¢ |
| 7% sensitivity | 0 | 0¢ |
| 14% sensitivity | 0 | 0¢ |

A bid/ask separation is a mathematical diagnostic conditional on a full-game winner and contemporaneous sides. Subtracting hypothetical fees supplies a cost-adjusted diagnostic. The archive does not establish quote age, simultaneous executable size, queue position, fills or the applicable effective fees. No signals, orders or simulated returns were calculated. The 136 matched observations are coverage of these six games, with no exchange-wide inference.

Make the next check small. If the operator’s already collected prospective data provides at least 30 eligible same-response pairs across four games, read those locally once. Require reported positive size on the relevant sides, contemporaneous receipt before the fixed A3.1 research cutoff, compatible rules and documented fees for the observation dates. Check only interval overlap and fee-adjusted distance. If no gap survives or coverage is too thin, park this hypothesis. [Prospective observer and cutoff](a3-1-observer.md)

## Reproduce locally

Run these commands from the repository root. Run `freeze` once only where the private whitelist is absent. The whitelist created before the analysis remains in the ignored A3.0 data directory.

```powershell
.\.venv\Scripts\python.exe -m research.e1 freeze
.\.venv\Scripts\python.exe -m research.e1 analyze
```

The runner verifies the frozen feature and protocol hashes and the digests of the scoped archived responses, opens SQLite read-only, and prints aggregate diagnostics. It does not read label files or the validation and holdout partitions.
