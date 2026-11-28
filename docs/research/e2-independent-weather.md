# E2 independent weather probabilities

**DATA BLOCKED.** The September 2026 NOAA archive contains probabilistic maximum-temperature forecasts for New York’s Central Park station. Their 18-hour maximum covers a different part of the day from the 24-hour settlement maximum. **Zero of six development days** support a comparison of like-for-like bracket probabilities.

## E1 disposition

**Parked.** Before reading prices, we fixed the last permissible NBA receipt at **2026-11-28 06:44:00 UTC**. One read-only examination of the existing smoke and pilot databases found **236 eligible same-response pairs across six games**. Both contracts were active at receipt, had compatible winner predicates, $1 notionals, valid two-sided quotes and positive displayed sizes. Receipts preceded the decision one hour before the first consistently reported game start. In every pair the combined bid was at most $1 and the combined ask was at least $1. There were **zero gross discrepancies**, so the fee inquiry stopped. These are repeated receipts. Zero fell in the final six-minute freshness window used by the separate calibration protocol. [E1 criteria](e1-complementary-contracts.md) · [A3.1 timing definitions](a3-1-observer.md)

## Which temperature settles the contract?

We froze all six September NYC development days and their 36 contracts from the A3.0 direction-free features before examining NOAA values. All 36 had an eligible historical trade close and two-sided candle closes. Each of the six complete integer partitions had one strict lower tail, four inclusive interior brackets and one strict upper tail. The archived predicate numerals agreed with the strike fields. The six days are the units available for a predictive comparison.

All 36 archived rules named **New York City (CLINYC)**, maximum temperature in °F, and **The Weather Company**. All six event records agreed on the publisher. CLINYC is the Central Park climate report, for station **KNYC, WBAN 94728**. The Weather Company identifies its domestic daily highs as official Fahrenheit climate-report figures. The NWS climate day runs midnight to midnight local **standard** time, or **05:00 UTC to 05:00 UTC** the next day in New York. During September that is 1 a.m. to 1 a.m. on the local daylight clock. This identifies the physical target from the archived terms and publisher documentation. Historical versions of the publisher’s feed at each decision time were unavailable in A3.0. [The Weather Company’s climate data methodology](https://weather.com/kalshi) · [NWS Central Park climate reporting](https://www.weather.gov/okx/CentralParkHistorical) · [NOAA station identification](https://www.ncei.noaa.gov/nerms/api/document/1806A23DA9AA4544BAC4868372CD78E4/download)

The series references GLOBALTEMPERATURE. Its terms use the first official non-preliminary report, subject to the material-error provisions, and the precision reported by the source. Apply the bracket to the published whole-degree Fahrenheit daily high. No second rounding of an app reading, converted METAR or forecast percentile is justified. The integer strikes form a complete partition on that reporting scale. Earlier general guidance naming NWS directly predates Kalshi’s August announcement and does not override the event-specific publisher. [Contract terms, pp. 1–2](https://assets.kalshi.com/contract_terms/GLOBALTEMPERATURE.pdf) · [August 27 publisher announcement](https://news.kalshi.com/p/kalshi-weather-company-partnership) · [NWS observation and rounding FAQ](https://www.weather.gov/lot/weather_observations_faq)

## What the public archive supplied

We chose one public calendar anchor, the **September 1, 01:00 UTC** operational NBP cycle. The key was independent of private event IDs, strike values and prices. September fell in the NBM v5.0 era, after its May 5 implementation and the July temperature update, and before the November v5.1 upgrade. The archived KNYC card itself says **V5.0**. It identifies the nominal cycle, without finer patch or first-publication metadata. The station bulletin samples the closest usable model grid point. NOAA’s NODD registry permits public use, requests attribution and requires identification of modifications. The aggregate findings here are Andromeda’s analysis of NOAA NBM data. [NOAA version history](https://vlab.noaa.gov/web/mdl/nbm-documentation) · [NWS service changes](https://www.weather.gov/notification/) · [NBM station products](https://vlab.noaa.gov/web/mdl/nbm-text-products) · [NODD license and access](https://registry.opendata.aws/noaa-nbm/)

The national bulletin was **34,724,483 bytes**. The initial GET stopped after the headers. One HEAD confirmed the size and modification time. Eight range GETs read **1,048,576 response-body bytes** in total and recovered the complete **3,684-byte** station card. The data acquisition used **9 GET attempts, 1 HEAD and $0**. The local receipt records the object, ETag, modification time, retrieval time and card digest. All genuine records remained in ignored local storage. [NOAA operational text archive layout](https://vlab.noaa.gov/web/mdl/nbm-text-archives)

| Coverage from the single archived cycle | Result |
| --- | ---: |
| Station cards checked | 1 at KNYC |
| Forecast lead columns | 18 |
| Daytime maximum columns with five ordered percentiles | 9 |
| Frozen development dates with a matching daytime date label | 5 / 6 |
| Date labels also passing the archive-time check for all six market closes | 4 / 6 |
| Development days with matching physical forecast and settlement windows | **0 / 6** |

The file’s S3 Last-Modified was **02:02:06 UTC**, 62 minutes and 6 seconds after its nominal cycle. The four timing matches use that timestamp against each contract’s selected candle end. This is a retrospective availability proxy. Neither the file header nor the archive timestamp establishes first dissemination, and the historical candles lack contemporaneous receipt timestamps. The unmatched sixth date is outside this single probe’s date coverage. No additional cycles were needed to diagnose the window mismatch.

## Why sparse quantiles cannot price these brackets

KNYC supplies the 10th, 25th, 50th, 75th and 90th percentiles as integer °F for the NBM maximum. The v5 card dates a maximum at 00 UTC for a **12:00–06:00 UTC** window. Against the settlement day, the windows share 17 hours. NOAA omits the first seven climate-day hours and includes one hour from the next climate day. A peak before noon UTC can make the settlement maximum higher. A peak in the extra hour can make the NOAA-window maximum higher. Even an exact distribution for one maximum would not identify the other. [NOAA v5.0 station-card definitions](https://vlab.noaa.gov/web/mdl/nbm-textcard-v5.0)

For an identical target, ordered quantiles could bound its CDF between adjacent probability levels, allowing for temperature rounding and ties. An interior bracket would need bounds at both endpoints. Interpolation would add a distributional assumption. Here the missing hours and the grid-to-sensor difference precede that calculation. Without assumptions about those temperatures and their dependence, the station card alone leaves each settlement-bracket probability with only the trivial **0–100%** bounds. Every valid historical trade probability and quote interval is compatible with those bounds. Neither a directional disagreement, predictive improvement nor an after-fee advantage is measurable.

**Next economic experiment.** Before acquiring more forecasts, use a separate, prespecified 30-day Central Park station-observation sample outside the market partitions. From the same quality-controlled sensor readings, compute both maxima, check the climate-day maximum against the official report and count how often changing only the window changes a two-degree bracket. Include missing days in the denominator. A material bracket-change rate would justify dropping daytime MaxT as a proxy. A low rate would justify evaluating it as an explicitly imperfect predictor on independent days. E2 stopped before that experiment.

## Local reproduction and verification

From the repository root, replay the saved NBA closeout, archived weather rules and cached NOAA card offline:

```powershell
.\.venv\Scripts\python.exe -m research.e2 audit
.\.venv\Scripts\python.exe -m research.e2_noaa audit
```

For provenance, the one-time entry points on a fresh research copy are `python -m research.e2 freeze`, `python -m research.e2 closeout` and `python -m research.e2_noaa acquire`, in that order using the project interpreter. The closeout refuses a second examination. Both audits use the local freeze. Reproduction on another machine requires the private source files.

Local verification passed with 126 Python tests and nine frontend tests. Synthetic E2 cases cover integer bracket edges, quote eligibility, station and cycle identity, the archive-time gate, integrity and the download limit. Ruff, mypy (including both E2 modules), pip dependency checks, ESLint, TypeScript, the production build and Git diff integrity passed.
