# A3.1 prospective NBA observer

The observer makes fresh anonymous GETs and records what the desktop actually received. It runs separately from the terminal, the synthetic ledger and A3.0. The operator confirmed bounded personal research permission. The reviewer has not inspected the correspondence. Keep response bodies, normalized snapshots and individual market records on the local machine. System Health exposes aggregate diagnostics only.

## Operate the seven-day pilot

From PowerShell in the checkout, launch once. The foreground command owns the worker until interruption or a campaign limit.

```powershell
Set-Location 'C:\Users\jacks\andromeda'
.\.venv\Scripts\python.exe -m research.observer start pilot
```

Press **Ctrl+C** in that window to stop. From a second PowerShell window in the same directory, use these commands individually as needed.

```powershell
.\.venv\Scripts\python.exe -m research.observer status pilot
.\.venv\Scripts\python.exe -m research.observer stop pilot
.\.venv\Scripts\python.exe -m research.observer resume pilot
```

For background operation, use this **instead of** the foreground launch. Use the same status and stop commands. To resume in the background substitute `'resume'` for `'start'`. Closing the browser has no effect. Computer sleep, shutdown or process termination interrupts coverage.

```powershell
Start-Process -FilePath '.\.venv\Scripts\python.exe' -ArgumentList '-m','research.observer','start','pilot' -WorkingDirectory (Get-Location).Path -WindowStyle Hidden
```

| Campaign | Poll schedule | Absolute lifetime | GET allowance | Response-body allowance |
| --- | --- | --- | ---: | ---: |
| Smoke | Four slots, 30 seconds apart | Up to 15 minutes | 30 | 20 MiB |
| Pilot | Five minutes, up to 2,016 slots | 168 hours from first launch | 3,500 | 512 MiB |

The ledger and deadline survive restarts. A second writer cannot take the same campaign lock. The worker stops at exhaustion and never renews. A resume advances to the current slot and counts missed slots. It does not backfill prices. The terminal reads `GET /api/v1/observer` every five seconds on System Health. A heartbeat over 60 seconds old, or a running flag past the deadline, is stale. Gap counts include missed, interrupted and partial polls. During an operator stop the displayed count includes slots already missed. The byte budget measures response bodies. Disk usage also includes the normalized records, database and SQLite sidecars.

## Sample and provenance

The production origin is `api.elections.kalshi.com/trade-api/v2`. The worker verifies `/series/KXNBAGAME`, then reads a bounded page of up to 100 ordinary series events with nested markets and associated milestones. Discovery uses a minimum market close of 24 hours before the query and applies no price, volume, status or result filter. It considers the current and following UTC calendar dates encoded in event identity. For each date it fills up to two places in full event-ID order on first discovery. These are convenience samples subject to listing order and late listings. A remaining cursor marks partial frame coverage. Discovery refreshes hourly and on empty rosters. Selected tickers remain on the watchlist for the campaign, including after close. [Public market-data guide](https://docs.kalshi.com/getting_started/quick_start_market_data) · [Event listing and milestone options](https://docs.kalshi.com/api-reference/events/get-events) · [Series reference](https://docs.kalshi.com/api-reference/market/get-series)

Each scheduled quote poll requests a fresh batch from `/markets?tickers=…`, including settled and inactive markets when returned. Identical consecutive payloads still produce independent receipts. A missing requested ticker gets a missing observation. Malformed responses, partial enumeration and API failures leave gaps. A 429 or 503 defers subsequent requests for at least 60 seconds and honors longer Retry-After values. Retries use subsequent scheduled opportunities. The worker accepts only the three public GET routes, refuses redirects and compressed bodies, and bounds each transfer to the smaller of 2 MiB and the remaining allowance. It reserves a request and bytes before dispatch, retaining a conservative byte charge for interrupted transfers. [Market listing](https://docs.kalshi.com/api-reference/market/get-markets) · [Rate limits](https://docs.kalshi.com/getting_started/rate_limits)

Local databases are `var/research/kalshi/a3_1/{smoke,pilot}.sqlite`. These paths are ignored by Git. Each request stores its path, parameters, UTC request initiation and completed receipt, monotonic duration, HTTP status, local body, size and SHA-256. Successful market responses append contract snapshots. Metadata rows retain the event/series relationship, source reference and schedule vintage. The full response preserves unrecognized fields. The worker keeps the decimal strings for YES/NO sides, YES best sizes, last trade, volume and open interest. It flags absent, invalid, empty-size and crossed fields. Missing price never becomes zero. A REST response may reflect provider caching or asynchronous book changes. No first-publication or fill time follows from receipt alone. [Fixed-point fields](https://docs.kalshi.com/getting_started/fixed_point_migration)

Two complementary contracts can share one underlying game. The grouping check requires the NBA series/event relation, mutual exclusivity, two sides, distinct participant UUIDs, matching side codes and dated basketball winner rules. Ambiguous observations remain local without an accepted group key. A unique linked basketball milestone start is a **reported schedule** at discovery receipt. Unknown or conflicting starts remain explicit. A trading close, market opening, reported occurrence and actual tip-off have different semantics. The actual game-start field remains unknown in this feed. Keep the original timestamps and any revisions. [Milestone schema and status limitations](https://docs.kalshi.com/api-reference/milestone/get-milestones)

Settlement sightings append separately with source settlement time and local receipt time. Only a final binary state with compatible nominal payout, YES/NO direction and a nonfuture settlement timestamp qualifies. Resolved game counts require complementary confirmations for both sides. Zero observed settlements leaves resolution coverage unknown.

## Proposed cutoff for later calibration

Freeze the first unambiguous scheduled tip-off seen for a game. Set the decision time to 60 minutes before that schedule. The schedule itself must have been received by the decision. Take the last valid two-sided quote received at or before the decision, no more than six minutes old, with positive reported size on both YES sides. For one game forecast, choose the lexicographically first validated participant UUID before looking at prices or outcomes. Use the YES midpoint divided by contract notional as the primary probability. Keep the opposite contract as a consistency diagnostic. The latest trade, its unknown age, the bid to sell, the ask to buy and the later settlement have separate meanings.

Exclude from the primary comparison games with late enrollment, conflicting grouping or schedules, a known reschedule, a gap across the decision, or unavailable required fields. To call the observation **pregame**, independently verify actual tip-off after the decision. Until then, describe it as relative to a reported schedule. Only use labels received before a later model-fit cutoff. Keep whole games and nearby game-day dependence together in chronological evaluation.

## Observed smoke result

On 27 November 2026 the worker completed four scheduled polls. Six HTTP 200 responses totaled **454,587 bytes**: one series check, one discovery response and four fresh market batches. All six stored hashes verified. The smallest recorded request-start interval was 1.225 seconds. Four underlying games supplied eight contracts and **32 observations**. All four had a linked reported schedule. All 32 passed the implemented quote-field checks. There were zero recorded gaps, request errors or settlement sightings. The same open System Health page displayed running and then stopped when the worker finished. The seven-day pilot was not launched. This verifies the acquisition path and persistence. It supplies no evidence of profitability, pregame eligibility or eventual settlement coverage.
