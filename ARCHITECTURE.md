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
 app.py (FastAPI + GZip + Cache-Control) -> /api/* JSON -> static/ dashboard (SVG)
```

A forecast is issued at an origin week $t$ using strictly historical observations up to week $t$, predicting ward-level cases at $t + h$ for $h \in \{2, 3, 4\}$ weeks ahead. Historical origins allow side-by-side comparison against realized outcomes, while the latest origin (`2025-12-29`) generates genuine forward forecasts.

## 2. Chronological Validation Split

Rows are partitioned strictly by **target date** rather than origin date so that no training label overlaps an evaluation period:

| Split | Target Dates | Labeled Rows | Purpose |
|---|---|---|---|
| **Train** | `<= 2022-12-31` | 63,720 | Fit horizon-specialized trees & derive tier cut points |
| **Validation** | `2023-01-01` to `2023-12-31` | 9,360 | Tune early-stopping tree count (`n_estimators`) per horizon |
| **Test** | `>= 2024-01-01` | 18,900 | Held-out evaluation reported once (never tuned on) |

Production models are refit on `train + validation` using the validation-selected tree counts (`h=2`: 148 trees, `h=3`: 144 trees, `h=4`: 222 trees). Random k-fold cross-validation was rejected because adjacent weeks within a ward are temporally autocorrelated, which would leak future weather/case regimes and inflate test metrics. `tests/test_pipeline.py` programmatically verifies per-ward grouping boundaries and zero target leakage.

## 3. Model Selection & Feature Rationale

- **Count-Appropriate Poisson Loss:** Ward-week dengue counts are non-negative and zero-inflated (58% zeros) with sharp monsoon spikes. Minimizing Poisson deviance naturally models skewed outbreak counts and guarantees non-negative predictions.
- **Horizon-Specialized Gradient-Boosted Trees:** Training separate `HistGradientBoostingRegressor` models for $h = 2, 3, 4$ weeks aligns each lead time with the biological mosquito incubation window (oviposition $\rightarrow$ larval development $\rightarrow$ extrinsic incubation period) while capturing nonlinear interactions between rainfall, temperature, drainage, and population density.
- **Biological & Spatial Interaction Engineering:**
  - `temp_opt_score`: Gaussian thermal suitability peaking at $28.5^\circ\text{C}$ (*Aedes aegypti* optimal survival/biting temperature).
  - `breeding_suitability_idx`: Joint product of 2–4 week breeding-window rainfall, thermal suitability, and relative humidity.
  - `stagnation_hazard`: Interaction of 2–4 week rainfall with `water_logging_risk_index`.
  - `city_rain_breeding_win`: City-Corporation-level breeding-window rainfall capturing urban outbreak spillover across neighboring wards.
- **Quantile Uncertainty Intervals (`q10`, `q90`):** Separate 10th- and 90th-percentile quantile models produce an 80% prediction interval and worst-case tier escalation (`94.0%` empirical coverage on the 2024–2025 test set).
- **Weather-Only Production Design (Zero Reporting-Delay Dependency):** An ablation adding lagged case counts (`cases_lag_0..3`, `cases_mean_4w`, `cases_trend`) yielded a test MAE of `1.099` vs. `1.071` without case history. Excluding case history prevents hospital reporting delays from degrading early warnings while outperforming both ward seasonal averages (`MAE 1.259`) and persistence (`MAE 1.861`).
- **Empirical Lag Evidence & Risk Tiering:** Rainfall-to-cases correlation peaks at a 3-week lag ($r = 0.75$ vs. $r = 0.53$ for same-week rain). Risk tiers (**Low / Medium / High / Critical**) are calibrated at the 65th, 85th, and 96th percentiles of training cases (`1.0`, `8.0`, and `14.0` cases/ward-week).
- **Exact Group Shapley Explanations:** Driver breakdowns compute exact Shapley values across 8 grouped feature coalitions (`256` coalitions $\times$ `40` background samples) so correlated lags share attribution fairly without masking one another.

## 4. Compute & API Cost Controls

| Control Mechanism | Implementation |
|---|---|
| **Serialized Model Artifacts** | Models trained offline (`~21s` on 1 CPU), compressed via `joblib` (`compress=3`), and loaded once at server startup (`<1s`) in `inference.Predictor`. |
| **Precomputed Feature Store** | `models/feature_store.joblib` stores the validated lag panel so inference never re-parses Excel workbooks or recomputes rolling windows per request. |
| **Vectorized & Memoized Inference** | Full 60-ward forecasts execute in 3 vectorized `predict()` calls (`~30 ms`) and are cached in memory via `@lru_cache(maxsize=512)`. |
| **Batched Shapley Attribution Cache** | All 256 feature coalitions are evaluated in a single vectorized matrix pass (`~0.15 s` cold) and memoized per `(ward_id, origin, horizon)`. |
| **HTTP & Client-Side Caching** | FastAPI serves responses with `GZipMiddleware` and `Cache-Control` headers (`600s`–`3600s`); `static/app.js` caches responses in a `Map` and debounces slider inputs (`120 ms`). |
| **Zero External API / Token Cost** | Zero LLM API calls, zero paid weather APIs, and zero external CDN requests at runtime—**operational API and token cost is $0.00**. |
| **Hot-Reload Retraining** | Optional `POST /api/retrain` (or `python -m src.train`) re-ingests updated Excel data and swaps `Predictor` in memory without downtime. |

## 5. Limitations & Production Roadmap

- **Live Meteorological Feed Integration:** Current inputs use historical weekly weather records; in deployment, `load_raw()` can ingest weekly Bangladesh Meteorological Department (BMD) gridded forecasts with zero changes to the downstream feature or model pipeline.
- **Ward Boundary GeoJSON:** Ward polygons are not included in the preliminary dataset, so spatial risk is rendered as a city-grouped ward heatmap grid; adding official City Corporation GeoJSON enables choropleth map rendering.
- **Threshold Recalibration:** Tier thresholds (`1, 8, 14` cases/ward-week) are calibrated to the preliminary dataset scale and should be recalibrated against DGHS clinical surveillance volume upon hospital integration.