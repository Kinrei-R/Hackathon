# Architecture

## 1. Data flow

```
 hackathon_preli_dataset.xlsx  (31,320 rows: 60 wards x 522 weeks)
            |
            v
 src/features.py  build_panel()
   per ward_id (groupby, sorted by date):
   rainfall lags 0-8 wk, rolling sum 2/4/8 wk, max 4 wk, wet-week count
   temperature + humidity lags 0/2/4 wk and 4-wk means
   static: population density, water-logging index, sanitation score
   targets y_h2, y_h3, y_h4 = cases 2/3/4 weeks AFTER the origin week            
            |
            v
 stack_horizons(): one row per (ward, origin week, lead time h)
   + target-week seasonality (sin/cos of week of year) + h as a feature
            |
            v
 src/train.py  chronological split by TARGET date
   train <= 2022 | validation 2023 | test 2024-2025
            |
            +--> HistGradientBoosting (Poisson)   -> dengue_model.joblib   (expected cases)
            +--> HistGradientBoosting (quantile)  -> dengue_q10 / q90.joblib (80% range)
            +--> tier cut points from training cases -> model_metadata.json
            +--> feature_store.joblib (all ward-week features) + metrics
            |
            v
 src/inference.py   Predictor (loaded once at startup)
   forecast(origin, h): 3 vectorised predict() calls on 60 rows, memoised
   ward_detail(): exact Shapley over 8 feature groups, memoised
            |
            v
 app.py (FastAPI) -> /api/* JSON -> static/ dashboard (vanilla JS + inline SVG)
```

A forecast is "made" at an origin week t using only data up to t, and describes week t + h for
h = 2, 3, 4. Origins range over the whole history, so a past origin can be compared with what
actually happened, and the latest origin (2025-12-29) gives true future forecasts.

## 2. Chronological validation split

Rows are split by **target date**, not origin date, so no training label falls in an evaluation period.

| Set | Targets | Rows | Use |
|---|---|---|---|
| Train | through 2022-12-31 | 63,720 | fit, derive tier cut points |
| Validation | 2023 | 9,360 | choose number of trees only |
| Test | 2024-01-01 onward | 18,900 | reported once, never tuned on |

The shipped model is refit on train + validation with the chosen tree count (122). Random k-fold was
rejected: neighbouring weeks of the same ward are near-duplicates, so shuffled folds leak and inflate
scores. `tests/test_pipeline.py` checks that lags are computed per ward, never cross ward boundaries,
and that no target column is a feature.

## 3. Model selection rationale

- **Counts, zero-inflated (58% zeros), strongly seasonal**, so a Poisson loss fits better than squared
  error and never predicts negative cases.
- **Gradient-boosted trees** capture the interaction the brief describes: the same rain produces more
  cases in wards with poor drainage, density and sanitation. They train in ~20 s on one CPU and
  predict in milliseconds, with no GPU and a ~0.4 MB model file.
- **Quantile models (10%, 90%)** provide a range, so officers see the uncertainty and the tier a ward
  *could* reach. Coverage on test is 95% against an 80% target: conservative, and reported as such.
- **Weather-only by design.** We measured an ablation that adds recent case counts: MAE 1.104 vs 1.103
  without. Because it adds nothing, production excludes case history, so the warning does not wait on
  delayed hospital reporting. Baselines on test: ward seasonal average MAE 1.26, last-week persistence 1.86,
  model 1.10.
- **Lag evidence.** Correlation of cases with rainfall k weeks earlier peaks at k = 3 (0.75) against
  0.53 for same-week rain (shown in the validation tab).
  - **Risk tiers** use cut points at the 65th, 85th and 96th percentile of training cases
  (1, 8, 14 cases per ward-week), so tiers reflect how rare each level is.
  - **Driver breakdown:** exact Shapley values over 8 groups of features (e.g. "Rainfall 2-4 weeks ago",
  "Ward vulnerability"). Groups, not single columns, so correlated lag columns share credit rather than
  masking each other. Contributions sum to prediction minus the average-ward-week baseline. Note
  that cumulative-rainfall features overlap the individual lag groups, so credit for rainfall is split
  between them; read the rainfall groups together.
