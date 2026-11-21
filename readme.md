# Urban Dengue Early-Warning System

Ward-level dengue risk (Low / Medium /High / Critical) **2 to 4 weeks for 60 wards in
Dhaka North, Dhaka South, Chattogram,  Gazipur and Narayanganj, built from multi-week rainfall,
temperature and humidity lags plus static ward vulnerability.

EDU AI Engineering Hackathon 2026, Phase 1 (preliminary round).

## Run it (under 3 minutes)

Needs Python 3.10+

```bash
git clone <https://github.com/Kinrei-R/Hackathon> dengue-ews && cd dengue-ews
python -m venv .venv && source .venv/bin/ activate  #Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:8000**.

The trained models are committed in `models/`, so there is no training step. If they are missing,
or were saved with a different scikit-learn version,`app.py` retrains once on startup (about 20 s).
To retrain by hand: `python -m src.train`. To run the lag/leakage tests: `python -m tests.test_pipeline`.

No API keys, no paid services, no network calls at runtime. The front end has no CDN dependencies.

## What you can do in the dashboard

- Choose the **week the forecast is made** (slider, arrows or presets such as *Peak 2025*) and a
**lead time of 2, 3 or 4 weeks**; filter by city.
- See all 60 wards as a **risk heatmap board** (colour = tier, number = expected cases), plus a ranked
list of the highest-risk wards with an 80% range and the tier they *could* reach.
- Click a ward to see its forecast fan for 2, 3 and 4 weeks, recent cases and rainfall, **driver
  breakdown** (exact Shapley contributions per factor group), and key weather readings vs. typical.
- **Model validation** tab: chronological hold-out metrics (MAE, RMSE, tier accuracy, interval
coverage), baseline comparison, per-horizon accuracy, predicted vs. actual series, confusion matrix
and the rain-to-cases lag correlation.
- When the chosen origin is in the past, actual outcomes are shown next to predictions. At the latest
week (2025-12-29) forecasts are genuine future predictions with no outcome yet.

## Results (held-out 2024-2025 targets, 18,900 ward-weeks)

| | MAE | RMSE |
|---|---|---|
| **This model** | **1.10** | **2.16** |
| Ward seasonal average | 1.26 | 2.45 |
| Last week's cases carried forward | 1.86 | 3.58 |

R-squared 0.72, tier correct 79%, within one tier 99%, High-or-Critical recall 67% / precision 58%.
The "80%" range covers 95% of outcomes, so it is conservative. Full numbers in
`models/model_metadata.json` and the validation tab.

## Repository layout

```
app.py                  FastAPI server (API + serves the dashboard)
src/features.py         per-ward multi-week lag pipeline
src/train.py            chronological split, Poisson + quantile models, metrics export
src/inference.py        cached inference, risk tiers, Shapley driver breakdown
static/                 index.html, style.css, app.js (vanilla JS, inline SVG charts)
models/                 serialized models, feature store, model_metadata.json
data/                   hackathon_preli_dataset.xlsx
tests/                  lag correctness and leakage checks
ARCHITECTURE.md         data flow, validation split, model rationale, cost controls
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/bootstrap` | origins, cities, wards, tier cut points |
| `GET /api/forecast?origin=2025-08-04&horizon=3&city=` | every ward's tier, expected cases, 80% range |
| `GET /api/ward/{ward_id}?origin=&horizon=` | fan for 2/3/4 weeks, drivers, key readings, history |
| `GET /api/validation` | hold-out metrics, baselines, confusion matrices, lag evidence |

## AI assistants and external APIs used

> Teams: keep this list accurate and complete before submitting.