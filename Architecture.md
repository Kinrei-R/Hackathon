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

