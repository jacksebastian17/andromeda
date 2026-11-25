# Andromeda

Andromeda is a local quantitative research terminal. A1 replays a fictional source ledger, generates versioned binary forecasts, evaluates known outcomes and serves the results from SQLite. The paper portfolio begins with $1,000 and has zero financial transactions. The fixture establishes a reproducible engineering baseline. Economic performance remains untested.

## Install on Windows

Use a local Python 3.12 or 3.13 interpreter, Node 24 and npm. This checkout was exercised with Windows Store Python 3.13.14, Node 24.14.0 and npm 11.9.0. In PowerShell, run these commands from the repository. Calling the environment's executable directly works without activating a PowerShell script.

```powershell
Set-Location C:\Users\jacks\andromeda
python --version
node --version
npm.cmd --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
npm.cmd --prefix frontend ci
```

If your Python installation uses the Windows launcher, substitute `py -3.12 -m venv .venv` for the environment creation command.

## Initialize and run

In the first PowerShell window, migrate the local database, ingest the fixture, score its resolved forecasts and start the read-only API.

```powershell
Set-Location C:\Users\jacks\andromeda
.\.venv\Scripts\python.exe -m andromeda migrate
.\.venv\Scripts\python.exe -m andromeda ingest
.\.venv\Scripts\python.exe -m andromeda evaluate
.\.venv\Scripts\python.exe -m andromeda serve
```

In a second PowerShell window, start the terminal.

```powershell
Set-Location C:\Users\jacks\andromeda\frontend
npm.cmd run dev
```

Open [the terminal](http://localhost:5173). The Vite server proxies relative API requests to the backend on port 8000. The API works independently while the browser is closed. Each server accepts Ctrl+C. To restart, repeat just the two serve commands. The default database is `var\andromeda.sqlite3`.

Two optional process environment variables control initialization. Supply `$env:ANDROMEDA_DB = 'C:\path\to\research.sqlite3'` to each **backend** shell for a separate database. Supply `$env:ANDROMEDA_STARTING_CASH = '2500.25'` before the first ingestion to choose a USD opening balance. Cash must be nonnegative and exactly representable in cents. Revisiting an initialized ledger preserves its original balance.

## Inspect the result

```powershell
$api = 'http://127.0.0.1:8000/api/v1'
Invoke-RestMethod "$api/health"
(Invoke-RestMethod "$api/overview").counts
Invoke-RestMethod "$api/events/T-CIRRUS" | ConvertTo-Json -Depth 8
(Invoke-RestMethod "$api/research/evaluations").mean_brier
Invoke-RestMethod "$api/portfolio"
```

Expect five underlying events, thirteen contracts and ten valid forecasts. Four events have settlements. Seven forecasts from three events have scores. A single absent source observation accounts for three missing forecasts. Three valid forecasts await resolution. The expected contract-weighted mean Brier score is `.7025 / 7`. The database and terminal expose unavailable history as null or an explicit empty state.

The full API schema ships locally at [OpenAPI JSON](http://127.0.0.1:8000/openapi.json). The [architecture and API reference](docs/architecture.md) describes response shapes and failure states. The [synthetic research ledger](docs/research.md) includes the per-contract oracle, timestamp semantics and model inputs.

## Verify

Backend tests use temporary SQLite files. Run from the repository root.

```powershell
Set-Location C:\Users\jacks\andromeda
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe
```

Run the frontend checks from its directory.

```powershell
Set-Location C:\Users\jacks\andromeda\frontend
npm.cmd test
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
```

For browser verification, leave both servers running with the fixture ingested and evaluated. On a Windows machine with Microsoft Edge installed, run the following in a third window.

```powershell
Set-Location C:\Users\jacks\andromeda\frontend
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm.cmd run e2e
```

To use Playwright's bundled Chromium instead, run these commands in the same directory.

```powershell
Remove-Item Env:PLAYWRIGHT_CHANNEL -ErrorAction SilentlyContinue
npx.cmd playwright install chromium
npm.cmd run e2e
```

The browser suite exercises all five pages against the actual API, opens a contract inspection, interrupts and restores connectivity, and tests a narrow viewport. Each run writes six PNGs under `frontend\test-results\screenshots\`. The tests expect the bundled fixture definitions and allow a custom opening balance. Dependency installation and browser downloads require network access. The initialized terminal operates locally.

GitHub Actions pins `ubuntu-24.04` because Playwright 1.56.1 supports Chromium and its system dependencies on that runner. The A1 run selected Ubuntu 26.04 through `ubuntu-latest` and failed at browser installation. CI runs the Chromium suite and uploads `frontend/test-results/` as the `browser-verification` artifact.

## Research scope

A1 has one experimental ensemble-frequency model. The backend has no exchange client, credential flow, order submission, fills, sizing or market-data collector. Persistent exchange data collection requires a future authorization decision. Calibration, structural valuation, cross-market comparisons, domain-specific ML and prospective economic evaluation remain future work. The archived Kalshi Edge Engine supplied no code or datasets to this implementation.
