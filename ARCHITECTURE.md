# System Architecture

## 1. Data Flow

```text
 hackathon_preli_dataset.xlsx  (31,320 rows: 60 wards x 522 weeks)
            |
            v
 src/features.py  build_panel()
   per ward_id & city (groupby, sorted by date):
   - rainfall lags 0-8 wk, rolling sums (2/4/8 wk), 4-wk max, wet-week count, momentum
   - temperature & humidity lags (0/2/4 wk), 4-wk means, Aedes thermal suitability score
   - biological & spatial interactions: breeding_suitability_idx, stagnation_hazard,
     crowding_sanitation_risk, and city_rain_breeding_win (urban spillover)
   - static vulnerability: population density, water-logging index, sanitation score
   - targets y_h2, y_h3, y_h4 = dengue cases 2, 3, and 4 weeks AFTER origin week t
            |
            v
 add_horizon() / stack_horizons(): per-lead-time framing (h in {2, 3, 4})
   + 1st & 2nd harmonic target-week seasonality (sin/cos of week of year)
            |
            v
 src/train.py  chronological split by TARGET date
   train <= 2022-12-31 | validation 2023 | test 2024-01-01 onward
            |
            +--> Horizon-Specialized HGB (Poisson, h=2,3,4)  -> dengue_model.joblib
            +--> Horizon-Specialized HGB (Quantile q10/q90)  -> dengue_q10 / q90.joblib
            +--> Calibrated tier thresholds (65th/85th/96th) -> model_metadata.json
            +--> Precomputed lag panel & background sample   -> feature_store.joblib
            |
            v
 src/inference.py   Predictor (loaded once at FastAPI startup)
   - forecast(origin, h): 3 vectorised predict() calls on 60 rows (~30 ms), memoised
   - ward_detail(): exact Shapley attribution over 8 feature groups, memoised
   - simulate_ward(): live what-if weather perturbation + interaction recomputation
            |
            v
 app.py (FastAPI + GZip + Cache-Control) <-> /api/* JSON <-> static/ dashboard (SVG)
```

- **Request/Response Loop:** The browser UI (`static/index.html`, `styles.css`, `app.js`) communicates exclusively with the FastAPI backend (`app.py`) over local REST JSON endpoints (`/api/bootstrap`, `/api/forecast`, `/api/ward/{ward_id}`, `/api/simulate`, `/api/validation`, `/api/retrain`).
- **External Services:** None at runtime. All meteorological features, trained models, and static assets are self-contained inside the repository.

## 2. Design Choices & Trade-Offs

- **Horizon-Specialized Poisson GBDTs vs. Single Pooled Model / Deep Learning:**
  - *Choice:* Separate `HistGradientBoostingRegressor` models with Poisson deviance loss for $h \in \{2, 3, 4\}$ weeks (`h=2`: 148 trees, `h=3`: 144 trees, `h=4`: 222 trees).
  - *Trade-off:* Ward-week dengue counts are zero-inflated (58% zeros) with sharp monsoon spikes. Poisson loss guarantees non-negative predictions and outperforms squared-error loss on skewed counts, while horizon-specific trees capture how biological incubation lags shift from 2 to 4 weeks without requiring GPU compute or large neural checkpoints (`~4.5 MB` total artifacts).
- **Chronological Validation Split vs. Random K-Fold:**
  - *Choice:* Strict target-date partitioning (`<= 2022` train: 63,720 rows; `2023` validation: 9,360 rows; `2024–2025` test: 18,900 rows).
  - *Trade-off:* Random k-fold leaks temporally autocorrelated weeks across folds and inflates accuracy. Chronological splitting yields a stricter, realistic out-of-sample benchmark (`Test MAE 1.071`, `RMSE 2.110`, $R^2 = 0.720$).
- **Weather-Only Production Design vs. Lagged Case Autoregression:**
  - *Choice:* Exclude lagged clinical case counts from production features.
  - *Trade-off:* An ablation adding lagged cases (`cases_lag_0..3`, `cases_mean_4w`, `cases_trend`) degraded test MAE (`1.099` vs. `1.071` weather-only) and would make early warnings vulnerable to hospital reporting delays.
- **Quantile Intervals (`q10`–`q90`) & Group Shapley Attributions:**
  - *Choice:* Dedicated 10th/90th percentile models (`94.0%` empirical coverage—conservatively calibrated above the `80%` nominal target) plus exact Shapley attributions across 8 correlated feature groups rather than single raw columns so rainfall lags share credit fairly.

## 3. Efficiency: Token Budget, Caching & Latency

- **Token Budget & Prompt Strategy:** **Zero LLM tokens (`$0.00` runtime cost).** Instead of routing tabular epidemiological forecasting through expensive, high-latency LLM prompts, deterministic gradient-boosted inference and exact Shapley game-theoretic attributions execute locally in milliseconds.
- **Startup & Feature Store Precomputation:** Models are trained offline (`~21 s` on 1 CPU), compressed via `joblib` (`compress=3`), and loaded once at startup (`<1 s`). `models/feature_store.joblib` caches the pre-engineered lag panel so requests never re-parse `.xlsx` files.
- **Multi-Layer Caching & Latency Controls:**
  - *Backend Memoization:* `forecast()` runs 3 vectorized `predict()` calls across 60 wards (`~30 ms` cold) and caches results via `@lru_cache(maxsize=512)` (`<1 ms` warm). `ward_detail()` batches all `256` Shapley coalitions $\times$ `40` background rows into a single vectorized pass (`~0.15 s` cold) and caches per `(ward_id, origin, horizon)`.
  - *Network & Browser Caching:* FastAPI compresses payloads with `GZipMiddleware` and attaches `Cache-Control` headers (`600s`–`3600s`); `static/app.js` caches responses in an in-memory `Map`, filters cities client-side without extra API calls, and debounces What-If weather slider inputs by `120 ms`.

## 4. Resilience & Fault Tolerance

- **Immunity to External Network Outages & API Rate Limits:** Because no third-party weather APIs, LLM endpoints, or external CDNs are called at runtime, the dashboard cannot fail due to upstream rate limits (`HTTP 429`), expired API keys, or external service downtime.
- **Self-Healing Model Loading:** On startup (`app.py`), if `models/*.joblib` files are missing, corrupted, or incompatible with the host's `scikit-learn` binary version, the server catches the exception and automatically executes `train_and_save()` to regenerate valid artifacts before accepting requests.
- **Strict Input Validation & Graceful Frontend Degradation:**
  - FastAPI validates query and JSON body parameters (`origin`, `horizon`, `ward_id`, and physical weather bounds in `POST /api/simulate`), returning structured `400`/`404`/`422` JSON responses on invalid inputs rather than unhandled server errors.
  - On transient client-to-server network interruptions (or cold-start wake-up on cloud free tiers), `static/app.js` catches failed `fetch()` calls, surfaces a non-blocking status banner, and preserves the last rendered board state without crashing the UI.
- **Atomic Hot-Reload on Retraining:** `POST /api/retrain` completes dataset ingestion, feature verification, and model serialization before swapping the active `Predictor` instance in memory, ensuring uninterrupted service if a retrain payload is invalid.

## 5. Limitations & Next Steps

- **Live Meteorological Feed Integration:** In production, `load_raw()` can ingest weekly Bangladesh Meteorological Department (BMD) gridded forecasts with zero changes to downstream feature engineering or inference.
- **Ward Boundary GeoJSON:** Adding official City Corporation GeoJSON polygons will upgrade the city-grouped ward grid into an interactive choropleth map.
- **Surveillance Threshold Recalibration:** Tier cut points (`1.0`, `8.0`, `14.0` cases/ward-week) are calibrated to the preliminary dataset and should be recalibrated against DGHS hospital surveillance counts upon deployment.