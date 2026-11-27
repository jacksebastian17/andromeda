# A3.0 Kalshi historical acquisition and feasibility

**DESCRIPTIVE ONLY.** The campaign linked genuine historical prices to final binary settlements for 92 contracts across 27 underlying events under a retrospective timing assumption. **Zero contracts qualified as strict point-in-time observations.** All 22 unambiguous comparisons between a candle close and the final public trade in that minute agreed. That checks price interpretation. It cannot establish when a historical observer received the candle, what schedule they knew, or whether they could transact at that price.

The starting checkout was clean at `7cc31d86770870db346ad1483ae61bd7efd2d93c` on `main`, tracking `origin/main`. The operator confirmed permission by correspondence for bounded personal trading research, local storage and statistical quality analysis. The original correspondence was not independently reviewed. This report contains aggregate diagnostics. Original responses, exact cutoff snapshots, record IDs, prices and partitioned labels stay on the operator's machine. Acquisition cost $0. No credentials were used.

## Frozen campaign and observed access

Seven discovery GETs checked the independent archive cutoffs, three official series descriptions and one 100-row archive page per series. Only presence, counts and calendar-month distributions informed window selection. The subsequent plan specifies ordinary game winners and one recurring maximum-temperature series. It freezes windows, sibling limits, price definition and sampling before any comparison. The bounded archive listing is complemented by a live listing covering the event window with 14 days of padding on each side. The population filter uses the date in the full event identity. It imposes no minimum activity or outcome filter. Within the available frame, sort by event date and ID and evenly sample indices including the endpoints. [Machine-readable campaign plan](../../research/a3_plan.json)

The public production origin used was `https://api.elections.kalshi.com/trade-api/v2`, listed alongside the external-api hostname in the official Predictions OpenAPI reference (manual schema 3.38.0). Archive market and candle routing follows market settlement time. Trade routing follows trade creation/fill time. The exact two boundary timestamps from this campaign are in the local manifest. Ranges touching a boundary use overlapping integer-second limits with ID deduplication. The live and historical candle schemas use different names for fixed-point dollar prices and contract quantities. [Quick start](https://docs.kalshi.com/getting_started/quick_start_market_data) · [Cutoff endpoint](https://docs.kalshi.com/api-reference/historical/get-historical-cutoff-timestamps) · [Tier guide](https://docs.kalshi.com/getting_started/historical_data) · [Units](https://docs.kalshi.com/getting_started/fixed_point_migration)

| Successful public GET under the v2 path | Requests |
| --- | ---: |
| `/historical/cutoff` | 1 |
| `/series/{series}` | 3 |
| `/historical/markets` | 43 |
| `/markets` | 38 |
| `/events/{event}` | 34 |
| `/historical/markets/{contract}/candlesticks` | 96 |
| `/series/{series}/markets/{contract}/candlesticks` | 12 |
| `/historical/trades` | 36 |
| `/markets/trades` | 1 |

**264 attempts, all HTTP 200, 4,170,285 identity-encoded response-body bytes** (3.98 MiB), including discovery and repeated reads of related records. Shortest start-to-start interval was 1.188 seconds. No retries, redirects, authentication challenges or 429s occurred. The campaign ceilings were 500 attempts, 50 MiB, three cohorts, 34 targeted events and 108 targeted contracts. Discovery listings cover additional identities. Each stored attempt has a route, local parameter record, UTC time, status, byte count and SHA-256. [Pagination](https://docs.kalshi.com/getting_started/pagination) · [Rate limits](https://docs.kalshi.com/getting_started/rate_limits) · [Historical markets](https://docs.kalshi.com/api-reference/historical/get-historical-markets)

## Empirical coverage

Counts are from local replay. One market ticker is one contract. Sides, repeated observations and sibling contracts do not add independent events.

| Cohort and window | Observed event days in sample | Window events / contracts before quarantine | Frame events / final binary contracts | Detailed event groups / contracts | Contracts with usable close | Proxy-eligible groups / contracts |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| NCAA men's game winner, March 2026 | Mar 12–29 | 140 / 280 | 140 / 280 | 12 / 24 | 18 | 6 / 12 |
| NBA game winner, May 2026 | May 1–30 | 34 / 68 | 34 / 68 | 12 / 24 | 22 | 11 / 21 |
| New York daily maximum, September 2026 | Sep 1–30 | 30 / 180 | 21 / 126 | 10 / 60 | 59 | 10 / 59 |
| **Total** | | **204 / 528** | **195 / 474** | **34 / 108** | **99** | **27 / 92** |

The three archival series scans each reached the three-page cap with a further cursor. All live series scans reached a terminal cursor, returning 0, 0 and 156 rows respectively across the padded windows. These are bounded denominators. March college basketball visibly lacks the first eleven days in the detailed sample. All 54 conflicting ticker representations arose in weather overlap. The freeze required exact duplicate agreement, so all 54 were quarantined, regardless of which fields differed. Nine weather event groups consequently left the frame. Reconciliation did not produce any conflict in the final sample. We cannot estimate selection bias from these counts.

For each selected basketball event, the local check reconciled the exchange event and full sibling list, series, game date in the rules, two distinct participant UUIDs in the strikes, named winner predicates, and team codes in the full event ID. Both contracts stayed in the same real-game group. All 24 sampled games had complementary final outcomes. Weather checks linked six distinct strike predicates to one city-day within the same maximum-temperature series, with matching dated rules and event settlement-source metadata. An independent physical-station crosswalk for another data provider remains unverified. Exact-event archive and live lookups reconciled 108 duplicate contract rows. There were zero ambiguous groups among the 34 selected. Missing identity, ambiguous dates, rule conflicts or incomplete sibling rosters prevent eligibility.

All 108 detailed contracts had a final YES or NO result, a settlement timestamp and a corresponding payout of zero or the recorded notional. Separate validators handle unresolved, void, scalar, malformed and inconsistent settlements. Counts were zero in each of these categories in the detailed sample. Directional labels are stored separately on disk. No holdout outcome or performance statistic is disclosed.

## Prices, exclusions and clocks

The primary candidate is the **latest completed one-minute YES trade close** in the first hour after market opening. Require a positive fixed-point contract volume, a finite dollar close within notional, an interval fully inside the window, and an assumed 60-second publication delay before the decision. A bar's source time is its inclusive period end. The cutoff is opening time plus one hour. Retrospective processing time is recorded separately in the local manifest. No software-generated forecast is backdated. [Historical candle schema](https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks) · [Live candle schema](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) · [Historical public trades](https://docs.kalshi.com/api-reference/historical/get-historical-trades)

| Diagnostic | College | NBA | Weather |
| --- | ---: | ---: | ---: |
| One-minute rows returned | 607 | 651 | 2,393 |
| Empty, zero-volume or previous-price-only rows excluded | 306 | 363 | 1,977 |
| Positive-volume rows with both bid and ask closes | 301 | 288 | 416 |
| Positive-volume rows too late under the delay assumption | 5 | 6 | 7 |
| Contracts with no qualifying primary price | 6 | 2 | 1 |
| Contracts failing the conservative pre-outcome time screen | 8 | 2 | 0 |
| Public trades with timestamp, valid price and positive quantity | 272 | 422 | 219 |
| Complete trade scans / targeted contract scans | 12 / 12 | 11 / 12 | 10 / 10 |
| Same-minute price agreements / unambiguous comparisons | 7 / 7 | 9 / 9 | 6 / 6 |

All 108 candle responses were retrieved. No invalid primary probabilities, duplicate conflicting candle ends or crossed closes were observed in the checked positive-volume rows. No stale price was carried forward. The bounded query cannot distinguish an older stale trade from no earlier trading. Trade checks used one preselected contract per event. One NBA scan reached its page limit. Seven comparisons had tied last timestamps with different prices. Unknown trade classifications, incomplete pagination or ambiguous ordering disqualify a comparison. Bid and ask candle closes are recorded separately. Their average would be a proxy for a midpoint, since historical quote synchronization is unverified. An execution, displayed side, candle close and final payout each describe a different observation. Depth and fill probability were not measured.

Every sampled contract had recorded open and final close times and allowed early closure. The occurrence field was populated for all sampled NBA and weather contracts and none of the college contracts. The acquired responses provide no verified version history of original schedules, intervening suspensions, rule amendments, or first publication of each price. The final close therefore cannot establish a 24-hour or one-hour pre-close decision. Opening-relative eligibility conservatively requires the decision to precede the earliest plausible event day (UTC+14 for sports, 04:00 UTC as the earliest midnight in New York), as well as the recorded trading close, settlement and any reported occurrence. These are retrospective screens. The actual schedule and price-availability gates remain open for **all 108**. The price and precedence exclusions overlap for three contracts. Sixteen contracts failed at least one proxy gate.

## Proposed A3.1 and statistical adequacy

Do a **timing-provenance audit** before fitting. Seek a permitted, bounded source of original schedules, rule versions, suspension history and timestamped dissemination, then check against these archived fields. Preserve the frozen opening-relative definition for that comparison. For weather, verify the station/day oracle and rule-version stability. For basketball, verify contemporaneous game scheduling and roster identity. Expansion alone cannot resolve missing timing evidence. A retrospective proxy experiment would require an explicitly narrower claim and independent review.

| Cohort | Chronological development / validation / holdout target groups | Corresponding proxy-eligible groups |
| --- | ---: | ---: |
| College | 7 / 3 / 2 | 1 / 3 / 2 |
| NBA | 7 / 3 / 2 | 7 / 3 / 1 |
| Weather | 6 / 2 / 2 | 6 / 2 / 2 |

Whole event days stay together within each cohort. The three cohorts occupy disjoint calendar windows. Pooling these partitions would let later seasons enter training for earlier predictions. For a later fit require every training label to have actually been available before the earliest next decision, and purge overlapping groups. Even using settlement time as an availability proxy, **6 college and 2 NBA development labels** failed the validation boundary, as did **4 NBA validation labels** at the holdout boundary. No fitting took place. Direction-free features and holdout labels occupy separate local files. Fit eligibility must be checked again once publication evidence exists.

If those gates are met, freeze one venue/cohort, split chronologically, compare raw market probability to `sigmoid(alpha + beta × logit(p))` with one predeclared horizon and an untouched holdout. Average paired Brier differences within each event, then equally across events. Candidate minus baseline is the contrast. Keep log loss and reliability plots secondary. Use day or longer time blocks where shared participants, weather or release timing create dependence. Keep the provisional **0.005 absolute Brier difference** as a research effect size. There is no economic threshold or implied return.

For planning, let *s* be the standard deviation of paired **event-level** loss differences. A normal approximation gives a 95% half-width of 1.96s/√n for independent events. These are variance scenarios, not estimates from holdout outcomes. Five proxy-eligible holdout events spread across three populations severely limit inference.

| Assumed s | Half-width with 5 independent holdout events | With all 27 proxy groups hypothetically independent | Effective holdout n for ±0.01 | For ±0.005 |
| ---: | ---: | ---: | ---: | ---: |
| 0.02 | 0.0175 | 0.0075 | 16 | 62 |
| 0.05 | 0.0438 | 0.0189 | 97 | 385 |
| 0.10 | 0.0877 | 0.0377 | 385 | 1,537 |

For illustration, a design effect of two at s = 0.05 requires about 770 eligible holdout groups for ±0.005. With a 20% holdout and the observed 27/34 proxy yield, that would mean roughly **4,850 targeted groups**, **37,700 GETs** and **570 MiB** at this campaign's average cost per group. At one request per second the request count alone implies over ten hours. These are rough planning numbers. One cohort's yield, time dependence, archive pagination, strict availability and fitted variance could change them materially. Strict eligible yield was zero, so a confirmatory acquisition size cannot yet be justified. No expansion was launched.

## Local reproduction and handling

Run from the repository root in PowerShell with the existing Python environment. With the archived campaign present, **replay** verifies successful response hashes, reconstructs partition files without network access and prints aggregate diagnostics. **Status** reads cumulative budget usage.

```powershell
Set-Location 'C:\Users\jacks\andromeda'
.venv/Scripts/python.exe -m research.a3_campaign status
.venv/Scripts/python.exe -m research.a3_campaign replay
```

These are the original acquisition entry points. They resume against the same ledger and reuse recorded responses. Retain that ledger to preserve the campaign limits and the original market snapshot. A fresh acquisition at a later date can encounter different archive boundaries or revisions.

```powershell
.venv/Scripts/python.exe -m research.a3_campaign discover
.venv/Scripts/python.exe -m research.a3_campaign collect
```

Local root is `var/research/kalshi/a3_0/`, covered by the existing Git ignore rule. `acquisition.sqlite` holds original response bodies and per-attempt metadata, including exact local parameters, attempt phase, original units and response digests. `manifest.json` holds the frozen plan, retrieval references, two cutoff clocks, transformation version, processing time, aggregate diagnostics and six normalized-file hashes. `normalized/{development,validation,holdout}/features.jsonl` contains the selected price, clock and identity fields. `labels/{development,validation,holdout}/outcomes.jsonl` contains settlement direction and timing. An offline replay reproduced all six hashes without adding a GET. CI runs independently constructed synthetic tests only.

The transport allows named GET routes on one TLS origin, refuses redirects and compressed bodies, and uses a 20-second socket timeout. It reserves request and byte budget before I/O, charges retries and retains a conservative reservation after interruption. It spaces requests across restarts, bounds each request key to three attempts, honors backoff, and stops the affected route on an authentication challenge. A process lock serializes access. Malformed objects, repeated cursors, page caps and unavailable records have separate diagnostic codes. Only aggregate output goes to stdout. The accepted synthetic database and application are separate from this research tool.
