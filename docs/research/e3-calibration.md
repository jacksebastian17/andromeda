# E3 statistical market calibration

**INSUFFICIENT PRECISION. Pause Andromeda’s expansion.** Recalibrating NBA game-winner probabilities improved the development Brier score by 0.00655. It worsened the score by 0.02276 on validation and by 0.00800 on the untouched test. The exploratory 95% interval for test improvement was **−0.02560 to +0.01651**, spanning both zero and the prespecified useful improvement of +0.005. Neither later partition supplies evidence for spending money on this correction.

## Population and clock

The protocol and partition caps were frozen before acquisition. Two unfiltered-status NBA series listings enumerated 214 candidate game IDs from October 28 through November 26, 2026. The untimed and close-window scans both reached terminal cursors, returning 758 and 608 contracts across their full listing windows. All 428 in-window contract rows appeared in both scans. No in-window ID appeared in the A3.0 listing or event-request identities. Ranking within each partition selected 196 distinct games before checking prices. The other 18 were outside the frozen caps. Only selected games received candle requests. Final metadata showed 392 finalized sibling contracts and zero inactive or unresolved siblings. It cannot establish whether a market was briefly suspended during the observation window. [Frozen protocol](e3-protocol.md) · [Kalshi market listing](https://docs.kalshi.com/api-reference/market/get-markets)

| Partition and rule dates | Listed games | Selected | Eligible | Eligible game days | Missing recent bar | Selected-side wins / losses |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Development, Oct 28–Nov 12 | 118 | 108 | 104 | 14 | 4 | 55 / 49 |
| Validation, Nov 13–18 | 48 | 40 | 40 | 6 | 0 | 19 / 21 |
| Test, Nov 19–26 | 48 | 48 | 44 | 6 | 4 | 28 / 16 |
| **Total** | **214** | **196** | **188** | **26** | **8** | **102 / 86** |

Both $1 binary siblings had to pass the dated full-game winner and participant checks and confirm complementary final payouts. Each game contributed one forecast for the lower canonical participant UUID. The decision was **10:00 UTC on the rule date**, 5 or 6 a.m. Eastern. The independent preseason NBA schedule lists 214 games over the window, with the earliest advertised tip at 1 p.m. Eastern. This supports outcome precedence for ordinary games. Individual actual tip-offs, original quote publication and later schedule changes remain unverified. No closing line or revised start time entered the model. [NBA schedule as released August 13, by date](https://ak-static.cms.nba.com/wp-content/uploads/sites/46/2026/08/2026-27-NBA-Regular-Season-Schedule-By-Date.pdf)

The forecast used the latest eligible one-minute YES bid/ask close midpoint. A complete minute had to fall after opening and end 2–60 minutes before decision. Development labels had to settle before November 13 at 09:00 UTC, and validation labels before November 19 at 09:00 UTC. No observed labels crossed those boundaries. The eight absent recent bars account for every exclusion after selection. Both declaration and selection preceded the check of which participant won. A historical bar can carry an older quote, and ordinary archival retrieval cannot prove the quote was visible two minutes later. These are retrospective pregame proxies. [Candlestick fields and period-end semantics](https://docs.kalshi.com/api-reference/market/get-market-candlesticks)

| Measurement diagnostic | Development | Validation | Test |
| --- | ---: | ---: | ---: |
| Distinct eligible midpoints | 64 | 31 | 39 |
| Median candle-end age | 2 min | 2 min | 2 min |
| Mean full quoted spread per $1 | 1.06¢ | 1.18¢ | 1.14¢ |
| Games with a positive-volume trade close inside the window | 102 | 40 | 44 |
| Mean absolute difference between that trade and the quote midpoint | 0.54¢ | 0.59¢ | 0.61¢ |

The E3 archive records 212 anonymous public GET attempts, all HTTP 200, comprising one historical cutoff, 15 listing pages and 196 candle requests. Response bodies totaled 5,645,705 bytes. The shortest start-to-start interval was 1.231 seconds. Expenditure was $0.

## Frozen fit and out-of-time performance

Before fitting, all three partitions passed the 60/20/30 game minimums, and both development classes exceeded ten outcomes. At 44 test games, independent paired-difference standard deviations of 0.02 and 0.05 imply approximate 95% half-widths of 0.00591 and 0.01477. Even the optimistic scenario exceeded the 0.005 research target. The coefficients and input digests were frozen locally before validation or test scoring.

The development maximum-likelihood fit was **α = 0.24756, β = 1.59148** on market log odds. The positive intercept raises the selected participant’s forecast near even odds. The slope above one steepens the odds curve, consistent *in development* with an underconfident market or a favorite–longshot pattern. The holdout scores and reliability frequencies give no consistent evidence that this bias persists.

| Partition | Raw Brier | Adjusted Brier | Paired improvement, raw − adjusted | Raw log loss | Adjusted log loss |
| --- | ---: | ---: | ---: | ---: | ---: |
| Development | 0.17872 | 0.17217 | +0.00655 | 0.53528 | 0.51272 |
| Validation | 0.23930 | 0.26206 | −0.02276 | 0.67387 | 0.75997 |
| Test | 0.21783 | 0.22584 | −0.00800 | 0.62503 | 0.65885 |

Test reliability is grouped by the **original** market probability. In the 20–40% bin, for example, the raw forecast averaged 28.6%, the adjustment lowered it to 23.5%, and four of nine participants won. In the 60–80% bin, the raw 68.1% was already close to the 66.7% observed. Moving it to 80.6% increased the error.

| Raw probability bin | Test games | Mean raw | Mean adjusted | Observed win rate |
| --- | ---: | ---: | ---: | ---: |
| 0–<20% | 2 | 19.5% | 11.8% | 0.0% |
| 20–<40% | 9 | 28.6% | 23.5% | 44.4% |
| 40–<60% | 13 | 50.0% | 55.9% | 69.2% |
| 60–<80% | 12 | 68.1% | 80.6% | 66.7% |
| 80–100% | 8 | 85.6% | 95.5% | 87.5% |

The test interval uses 10,000 paired resamples, each drawing four adjacent two-calendar-day blocks with replacement from seven possible overlapping blocks. It keeps whole games together, includes two empty dates, and conditions on the frozen model. Six observed game days give weak information about dependence, tail-bin reliability, and performance in other weeks or seasons. The interval includes economically interesting statistical effects in both directions. The two negative later estimates and this uncertainty justify stopping without a claim that the market is perfectly calibrated.

## Economics and the prospective checkpoint

The mean absolute test correction was **8.38 probability points**, compared with a **0.57-point half-spread**. All 44 adjustments lay outside their candle quote intervals. A model can move that far and become *less* accurate, as happened here. For scale only, Kalshi’s July 7 general schedule gives an immediately matched fee of 1.75¢ before rounding at a synthetic 50¢ price and default multiplier of one. The applicable historical event overrides were unverified. Brier units do not convert into cents of profit, and these candles establish neither available size nor fills. There is no evidence of a net advantage, even before attributing an execution cost. [Official fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf)

At **08:43:10 UTC on November 28**, the read-only pilot checkpoint found **632 contract observations in 79 quote batches across four games**. All four first reported one-hour-before-tip horizons were still in the future. Zero games had a scheduled-horizon forecast, zero had independently verified pregame eligibility, and there were zero settlement sightings. There were zero recorded gap slots and zero request errors. The worker was running, with its original deadline of December 5 at 02:10 UTC. No directional settlement values were queried. The pilot can document receipt-time coverage as the scheduled horizons pass. Its two-games-per-date cap and lack of independently verified actual tips keep it from materially resolving E3’s precision question within this campaign. Let the bounded pilot finish on its existing terms. [Prospective eligibility rules](a3-1-observer.md)

## Decision across E1–E3

- **E1 stays parked.** Neither of the two historical one-cent discrepancies survived within-minute ranges or positive fee scenarios. There were zero gross gaps in 236 eligible prospective pairs across six games. [E1 results](e1-complementary-contracts.md) · [Prospective closeout](e2-independent-weather.md)
- **E2 remains data blocked.** The available weather model and settlement contract measure different daily maxima. Zero of six days supported a like-for-like probability comparison. Defer the Central Park window study. [E2 results](e2-independent-weather.md)
- **E3 supplies no basis to expand.** The raw midpoint beat the frozen correction in both later periods. Reopening the calibration hypothesis would require prospective evidence of improved accuracy across many independent days at a defensible decision clock. The current experiments supply no economic reason to fund that collection or build an execution system.

## Local reproduction

The original bounded acquisition was `python -m research.e3 collect`. From the repository root, the following commands replay the saved market responses locally and verify the same frozen fit. They require the private E3 archive and the original A3.0 identifier index. All tracked tests use synthetic inputs.

```powershell
.\.venv\Scripts\python.exe -m research.e3 replay
.\.venv\Scripts\python.exe -m research.e3_calibration assess
.\.venv\Scripts\python.exe -m research.e3_calibration fit
.\.venv\Scripts\python.exe -m research.e3_calibration score
```

The dated checkpoint is saved separately in the ignored E3 directory. Running `python -m research.e3_pilot` reads the current pilot and prints a new aggregate snapshot.

Offline replay reproduced the eligibility counts, coefficients and scores. Local verification passed 133 Python tests, including seven synthetic E3 tests, nine frontend tests, and three Playwright tests with a temporary synthetic database and installed Chrome. Ruff, project and E3 mypy checks, dependency consistency, ESLint, TypeScript and the production build passed.
