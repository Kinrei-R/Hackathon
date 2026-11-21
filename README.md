# Urban Dengue Outbreak Early-Warning System

Ward-level dengue outbreak risk (**Low / Medium / High / Critical**) forecast **2 to 4 weeks ahead** across **60 urban wards** in Dhaka North, Dhaka South, Chattogram, Gazipur, and Narayanganj—built from multi-week rainfall, temperature, and humidity lags, biological *Aedes* breeding interactions, and static ward vulnerability.

EDU AI Engineering Hackathon 2026 — Phase 1 (Preliminary Round).

## Run Locally (Under 3 Minutes)

Requires **Python 3.10+**.

```bash
git clone https://github.com/Kinrei-R/Hackathon.git dengue-ews
cd dengue-ews
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:8000** in your browser.

Pre-trained horizon-specialized models are committed in `models/`, so the dashboard starts immediately with no mandatory training step. If artifacts are missing or incompatible with the local `scikit-learn` version, `app.py` automatically retrains once on startup (~23 seconds).
- Manual retraining: `python -m src.train`
- Run lag & leakage verification tests: `python -m tests.test_pipeline`

No API keys, no paid cloud services, and zero external network calls at runtime. The front end uses vanilla HTML/CSS/JS with zero CDN dependencies.

## Dashboard Capabilities

- **Ward Risk Heatmap & Ranked Triage Board:** Select any forecast origin week (slider, step buttons, or presets such as *Peak 2025*), lead time (**2, 3, or 4 weeks**), and City Corporation filter to view all 60 wards color-coded by risk tier alongside expected cases, 80% prediction intervals (`q10`–`q90`), and worst-case tier escalation.
- **Ward Detail & Exact Shapley Driver Breakdown:** Click any ward to inspect its 2–4 week forecast fan, 16-week historical case and rainfall trend, local weather readings vs. typical baseline, and exact **Shapley value driver attributions** (multi-week rainfall breeding lag, ward vulnerability & breeding synergy, temperature, humidity, and seasonality).
- **Interactive What-If Weather Simulator:** Adjust rainfall (`0–350 mm`), temperature (`12–42 °C`), and humidity (`30–100 %`) sliders for any ward to dynamically simulate how shifting monsoon conditions alter predicted cases, risk tier, and Shapley drivers in real time.
- **Model Validation & Calibration Tab:** Inspect out-of-sample chronological hold-out metrics (`2024–2025`), baseline comparisons, per-horizon accuracy (`h = 2, 3, 4`), predicted-vs-actual time series, 4×4 tier confusion matrices, and empirical rainfall-to-cases lag correlations.

## Held-Out Test Results (2024–2025 Targets, 18,900 Ward-Weeks)

| Model / Baseline | MAE | RMSE |
|---|---|---|
| **Horizon-Specialized Poisson HGB (This Model)** | **1.071** | **2.110** |
| Ward seasonal average | 1.259 | 2.453 |
| Last week's cases carried forward (persistence) | 1.861 | 3.582 |

- **$R^2$:** `0.720` | **Exact Tier Accuracy:** `78.9%` | **Within ±1 Tier:** `99.2%`
- **High/Critical Recall:** `59.5%` | **High/Critical Precision:** `60.3%`
- **80% Interval Coverage (`q10`–`q90`):** `94.0%` (well-calibrated conservative uncertainty bounds)

Full metrics and per-horizon breakdowns are stored in `models/model_metadata.json` and displayed in the **Model validation** tab.

## Repository Layout

```text
app.py                  FastAPI server (REST API + static dashboard host)
src/features.py         Per-ward multi-week lag & biological breeding synergy pipeline
src/train.py            Chronological split, horizon-specialized Poisson & quantile training
src/inference.py        Cached inference, risk tiering, What-If simulator, exact Shapley drivers
static/                 index.html, styles.css, app.js (vanilla JS, inline SVG charts)
models/                 Serialized joblib models, feature store, model_metadata.json
data/                   hackathon_preli_dataset.xlsx
tests/                  Lag correctness and zero-leakage verification tests
ARCHITECTURE.md         System data flow diagram, chronological split, model rationale, cost controls
```

## API Endpoints

| Method & Endpoint | Purpose |
|---|---|
| `GET /api/bootstrap` | Available origin weeks, cities, wards, and calibrated tier thresholds |
| `GET /api/forecast?origin=2025-08-04&horizon=3&city=` | Risk tier, expected cases, and 80% interval for all 60 wards |
| `GET /api/ward/{ward_id}?origin=&horizon=` | 2–4 week forecast fan, Shapley drivers, key readings, and history |
| `POST /api/simulate` | Live What-If weather scenario simulation for a selected ward |
| `GET /api/validation` | Chronological hold-out metrics, baselines, confusion matrices, and lag evidence |
| `POST /api/retrain` | Re-ingest updated dataset, retrain models, and hot-reload predictor |

## AI Assistants & External APIs Disclosure

- **Claude (Anthropic):** Used for initial scaffolding of the data pipeline, model training scripts, test suite, and documentation drafts.
- **Google Gemini:** Used for model architecture refinement (horizon-specialized models, biological breeding interaction features), interactive What-If weather simulator integration, UI/UX refinements, and rubric validation.
- **External APIs / Cloud Services:** None. All training and inference run 100% locally using open-source Python libraries (`scikit-learn`, `pandas`, `numpy`, `fastapi`, `uvicorn`, `joblib`, `openpyxl`) with zero external API calls or LLM token usage at runtime.