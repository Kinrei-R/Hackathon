# ARCHITECTURE

Tag: `version-onsite-final`

## 1. Data (`bangladesh_dengue_large_dataset_onsite.xlsx`, sheet `bangladesh_dengue_large_dataset`)

31,320 rows x 15 columns = 60 wards x 522 weeks (2016-01-04 to 2025-12-29). Cities: Dhaka North (20 wards), Dhaka South (20), Chattogram (10), Gazipur (5), Narayanganj (5).

| Column | min | median | p90 | max |
|---|---|---|---|---|
| `dengue_cases` | 0 | 0 | 9 | 41 |
| `saline_bags_needed` | 0 | 0 | 21 | 98 |
| `diagnostic_kits_needed` | 0 | 0 | 10 | 48 |
| `hospital_beds_required` | 0 | 0 | 3 | 12 |

Observed supply per case (dataset-wide): saline 2.378, kits 1.147, beds 0.289. Ward density, water-logging, and sanitation are constant per ward. Zero-inflated, right-skewed counts motivate Poisson loss and quantile bands.

## 2. Forecasting core

Features (`src/features.py`), per ward, at origin week t:
- Lags k = 0..8 of `rainfall_mm`, `avg_temp_c`, `relative_humidity_pct` (27 columns)
- `rain_x_waterlog = rainfall_mm * water_logging_risk_index`
- `dens_x_unsanitary = population_density_sqkm * (1 - sanitation_score)`
- Case lags 0..3 and 4-week moving average, sin/cos week-of-year, static ward covariates, max/min temperature

Models (`src/train.py`): for h in {2, 3, 4}, three `HistGradientBoostingRegressor` models on target `cases(t+h)`: `loss="poisson"` (mean), `loss="quantile"` at 0.10 and 0.90. 9 models, seed 42, no early stopping (deterministic).

Chronological protocol:
- Holdout = last 52 weeks (from 2025-01-06). Train rows require `date + h weeks < holdout start` (no target leakage).
- Holdout fits are saved to `artifacts/models_holdout/` (used by the peak-season replay).
- Serving fits use all labelled rows (`artifacts/models/`).
- Intervals are made monotone: `lo = min(q10, mean)`, `hi = max(q90, mean)`.

Holdout results:

| h | MAE | RMSE | MAE persistence | q10-q90 coverage | mean width |
|---|---|---|---|---|---|
| 2 | 1.069 | 2.072 | 1.803 | 93.3% | 4.36 |
| 3 | 1.183 | 2.250 | 2.106 | 92.6% | 4.51 |
| 4 | 1.294 | 2.463 | 2.342 | 92.3% | 4.60 |

Scenarios: `live` (origin 2025-12-29, final models; off-season so forecasts are near zero) and `peak` (origin 2025-06-09, the holdout week with the most actual cases at t+3; out-of-sample models).

## 3. Operations (`src/operations.py`)

Planning cases per ward: `pred = mean over h of forecast_h * surge` (or the mean of q90 for the upper basis); `c = round(pred)`.

Demand conversion (ward-specific empirical ratios r = sum(resource) / sum(cases), global ratio if a ward has no cases):

```
saline_req = ceil(r_saline * c)    kits_req = ceil(r_kits * c)
beds_req   = ceil(r_beds * c)      crews_req = ceil(c / 8)
```

Priority:

```
priority = pred * sqrt(density / max_density) * (1 + water_logging_risk_index) * (2 - sanitation_score)
```

Allocation: wards sorted by priority descending. Stock pools are regional: `pool_city,r = floor(stock% * sum_city req_r)` for saline and kits. Crews are one global pool in `[10, 120]`. For each ward in order: `alloc = min(req, remaining pool)`. Shortfall = req - alloc. A ward with any shortfall is flagged `CRITICAL DEFICIT` with exact counts; `fulfillment% = 100 * min_r(alloc_r / req_r)`.

Bed routing:

```
capacity = max(4, round(1.15 * p90(ward hospital_beds_required history)))
overflow = max(0, beds_req - capacity)      spare = max(0, capacity - beds_req)
```

Per city only: donors (largest overflow first) send to the receiver with the most spare beds. Output: manifest (from, to, patients), `utilization% = sum beds_req / sum capacity`, and unmet = overflow - routed. No cross-city edges exist.

Counterfactual (k crews, k in 0..3):

```
wl' = wl * (1 - min(0.65, 0.22 k))        san' = min(1.0, san + 0.12 k)
```

Primary path: recompute the two interaction features, re-run the 3 mean models for t+2..t+4, `delta_h = base_h - cf_h`. Deterministic fallback (used per cell when the model path gives no reduction, or when model files are missing):

```
cf_h = base_h * [(1 + wl') / (1 + wl)] * [(2 - san') / (2 - san)]
```

Aggregation with lifecycle weights `w = (0.65, 0.90, 1.00)`:

```
cases_prevented = sum_h w_h * delta_h        beds_freed = r_beds * cases_prevented
saline_saved    = r_saline * cases_prevented  ROI = cases_prevented / k
```

All 60 wards are ranked by best ROI over k = 1..3. Auto-assign adds crews one at a time to the ward with the largest marginal cases prevented (max 3 per ward). Each result is labelled `ml`, `fallback`, or `mixed`.

Dispatch: fixed templates produce an SMS (shortened in steps to stay <= 160 characters), a WhatsApp brief, and a printable HTML brief with `@media print`.

## 4. Data flow

```
xlsx -> train.py -> models/ + models_holdout/ + latest*.joblib + meta.json
                 -> forecasts*.csv + effects*.json (precomputed fallback)
FastAPI -> inference.Engine (ML, or precomputed if models fail to load)
        -> operations.plan: demand -> priority allocation -> bed routing
        -> operations.simulate: counterfactual effects -> ROI ranking
        -> operations.sms / whatsapp / commissioner_html -> exports/
static/ (landing.*, index.html, styles.css, app.js) <-> /api/* on 127.0.0.1
```

## 5. Offline guarantees

| Guarantee | Mechanism |
|---|---|
| No external assets | Local `static/` only; system font stacks; stress test scans text assets for external URLs; Content-Security-Policy restricts the browser to the same origin |
| No outbound traffic | `/api/stress-test` patches socket connect and DNS during a full pipeline run; any non-loopback attempt fails and is counted; a probe to 8.8.8.8:53 must be blocked |
| Model-file failure | Engine falls back to `forecasts*.csv` and `effects*.json`; verified with `models/` removed |
| Determinism | Fixed seed, no early stopping, template text, no randomness; stress test hashes two runs |
| City boundary | Routing loops run per city; stress test asserts zero cross-city transfers |
| Stock integrity | Stress test asserts allocation <= demand, <= regional pool, <= crew limit |

Stress test (9 checks) at 30% stock, 10 crews, surge 3x (and 1.5x for mixed routing): static scan, blocked-network pipeline run, kill-switch probe, repeat-run hash, no cross-city transfers, bed conservation, pool limits, 60 SMS <= 160 chars, 60-ward ROI ranking.
