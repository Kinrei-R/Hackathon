# dengue-ews: Urban Vector-Borne Outbreak Decision & Resource Dispatch Engine

BLUEPINE

Offline-first forecasting and dispatch for 60 wards in 5 Bangladesh city corporations. FastAPI + scikit-learn + vanilla HTML/CSS/JS. No CDNs, no cloud APIs, no LLM calls at runtime.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Trained artifacts are included in `artifacts/`. To retrain from the workbook (about 1 minute):

```bash
python -m src.train
```

## Run

```bash
uvicorn app:app --host 127.0.0.1 --port 8000
python generate_exports.py        # writes exports/ (SMS, WhatsApp, 2 commissioner briefs)
```

Open http://127.0.0.1:8000 for the overview page and http://127.0.0.1:8000/app for the command center.

## Layout

```
app.py                  FastAPI routes + kill-switch stress test
generate_exports.py     sample dispatch exports
src/features.py         lags 0-8 (rain, temp, humidity), interactions, seasonality
src/train.py            chronological HistGradientBoosting: Poisson mean + q10/q90, h = 2, 3, 4
src/inference.py        forecasts, ML counterfactual effects, precomputed fallback
src/operations.py       demand, allocation, bed routing, simulator, dispatch templates
static/                 landing.html/css/js (overview), index.html + styles.css + app.js (command center), all local
tests/                  pytest suite: allocation, routing, simulator, fallback engine, API
artifacts/              .joblib models, forecasts, effects, metadata
data/                   bangladesh_dengue_large_dataset_onsite.xlsx
exports/                generated samples
```

## Test

```bash
pip install -r requirements-dev.txt
pytest -q          # API tests are skipped automatically if fastapi/httpx are missing
```

## Dataset

31,320 rows, 60 wards, 5 cities, 522 weeks (2016-01-04 to 2025-12-29). Weekly `dengue_cases`: median 0, p90 9, max 41.

## Command center walkthrough

| Control / panel | What it does |
|---|---|
| Scenario | Peak-season replay (origin 2025-06-09, out-of-sample models) or Live (origin 2025-12-29, off-season, near-zero forecast) |
| Regional stock 30%-100% | Per-city saline and kit pools; wards served in priority order until empty |
| Spraying crews 10-120 | Global crew pool, same priority order |
| Outbreak surge 1x-4x | Scales forecasts to stress allocation and bed routing |
| Ward risk heatmap | Tile color = priority rank; red base edge = CRITICAL DEFICIT |
| Allocation table | Allocated / required per resource, exact shortfalls |
| Bed routing | Transfer manifest, city utilization, unmet beds (same-city only) |
| Vector simulator | 0-3 crews per ward or auto-assign; cases prevented, beds freed, saline saved, ROI; all 60 wards ranked |
| Dispatch preview | SMS (<= 160), WhatsApp brief, printable commissioner brief |
| Color heatmap by | Priority rank, or expected cases per week (honest in quiet seasons) |
| KPI strip and selected-ward panel | Fill rates, deficits, unmet beds; forecast range chart, supply and bed routing for the chosen ward |
| Download CSV | Allocation table for the current filters |
| Offline kill-switch and stress test | Runs the whole pipeline with every outbound connection blocked, then reports 9 checks |

Tip: set surge to 1.5x to see transfers and unmet beds together.

## API

`GET /` overview page | `GET /app` command center | `GET /api/health` | `GET /api/status` | `GET /api/forecast` | `GET /api/operations` | `GET /api/routing` | `POST /api/vector-simulate` | `GET /api/dispatch/{ward_id}` | `GET /api/dispatch/{ward_id}/brief` | `GET /api/stress-test`

## Verify offline

1. Turn Wi-Fi off, start the server, click **Offline kill-switch and stress test**: expect PASS on all checks.
2. `grep -rEn "https?://" static/` returns nothing.
3. DevTools, Network tab: all requests go to 127.0.0.1.

## Git convention

Every commit message must contain `version-onsite-final`:

```bash
git add -A
git commit -m "feat: phase 2 dispatch engine [version-onsite-final]"
```

## Front-end notes

- Controls are remembered in the browser (localStorage, optional) and `Reset controls` restores defaults.
- Responses use a strict Content-Security-Policy (`default-src 'self'`), so a stray CDN link would be blocked as well as caught by the stress test.
- Out-of-order responses are discarded, so dragging a slider quickly never shows stale numbers.
- `/app#stress` opens the stress test directly.

## Known limits

- Live scenario forecasts are near zero because the dataset ends in the off-season; use the peak replay for demonstrations.
- q10-q90 intervals cover about 92-93% of holdout weeks (zero-inflated counts make them wider than 80%).
- The counterfactual uses a model-driven path and a deterministic fallback; effects are modeled, not measured field results.

## AI Disclosure

- Parts of this code and documentation were drafted with Claude (Anthropic), then run and checked by the authors.
- No AI service is called at runtime. Forecasts come from locally trained scikit-learn models; dispatch text comes from fixed templates.
- Outputs are decision support, not medical or operational orders. Qualified public-health staff must review them before action.
- The human authors remain responsible for the data, code, and results.
