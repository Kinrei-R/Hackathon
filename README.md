# Urban Dengue Outbreak Early-Warning System

Ward-level dengue outbreak risk (**Low / Medium / High / Critical**) forecast **2 to 4 weeks ahead** across **60 urban wards** in Dhaka North, Dhaka South, Chattogram, Gazipur, and Narayanganj—built from multi-week rainfall, temperature, and humidity lags, biological *Aedes* breeding interactions, and static ward vulnerability.

Addresses the **Urban Dengue Outbreak Early-Warning System** challenge for the **EDU AI Engineering Hackathon 2026 (Phase 1 — Preliminary Round)**, enabling municipal health officers to allocate fogging, larvicide, and hospital surge capacity before outbreaks peak without waiting on delayed clinical reporting.

## Demo

- **Live Deployed App:** `https://hackathon-t5qe.onrender.com/` *(update with your exact Render URL if different; free-tier instances may take ~30s to wake on first load)*
- **Local URL:** `http://127.0.0.1:8000` (see **Setup & Run Instructions** below for instant zero-latency local execution)

## Team — Kinrei-X

| Member | GitHub | Role & Contributions |
| :--- | :--- | :--- |
| **Gias Uddin Muntasir Rifat** | `@Kinrei-R` | Team Lead, ML Modeling & Feature Engineering (`src/features.py`, `src/train.py`, `src/inference.py`), FastAPI Backend (`app.py`), Interactive What-If Simulator |
| **Fabiha Belal** | `@FabihaBelal` | Documentation (`README.md`), Validation & Metric Analysis, Exploratory Data Verification |
| **Syed Tihan** | `@Syed-Tihan` | System Architecture (`ARCHITECTURE.md`), Limitations & Production Roadmap, QA Testing |

## Tech Stack

- **Language:** Python 3.10+
- **Machine Learning & Data Processing:** `scikit-learn` (`HistGradientBoostingRegressor` with Poisson & Quantile losses), `pandas`, `numpy`, `joblib`, `openpyxl`
- **Backend & API:** `FastAPI`, `Uvicorn`, `Pydantic` (with `GZipMiddleware` and HTTP `Cache-Control`)
- **Frontend & Visualization:** Vanilla HTML5, CSS3, JavaScript (ES6+), custom inline SVG charts (zero external CDN or chart library dependencies)
- **Hosting & Version Control:** Git / GitHub, Render Web Service

## Setup & Run Instructions (Under 3 Minutes)

Requires **Python 3.10+**. **No `.env` file, API keys, or environment variables are required.**

```bash
git clone https://github.com/Kinrei-R/Hackathon.git

python -m venv .venv

# Linux / macOS:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:8000** in your browser.

Pre-trained horizon-specialized models are committed in `models/`, so the dashboard launches immediately with no mandatory training step. If artifacts are missing or saved under a different `scikit-learn` version, `app.py` automatically retrains once on startup (~23 seconds).
- **Manual retraining:** `python -m src.train`
- **Run lag & zero-leakage tests:** `python -m tests.test_pipeline`

## Dashboard Capabilities

- **Ward Risk Heatmap & Ranked Triage Board:** Select any forecast origin week (slider, step buttons, or presets such as *Peak 2025*), lead time (**2, 3, or 4 weeks**), and City Corporation filter to inspect all 60 wards color-coded by risk tier alongside expected cases, 80% prediction intervals (`q10`–`q90`), and worst-case tier escalation.
- **Ward Detail & Exact Shapley Driver Breakdown:** Click any ward to inspect its 2–4 week forecast fan, 16-week historical case and rainfall trend, local weather readings vs. typical baseline, and exact **Shapley value driver attributions** across 8 grouped factors.
- **Interactive What-If Weather Simulator:** Adjust rainfall (`0–350 mm`), temperature (`12–42 °C`), and humidity (`30–100 %`) sliders for any ward to dynamically simulate how shifting monsoon conditions alter predicted cases, risk tier, and Shapley drivers in real time.
- **Model Validation & Calibration Tab:** Inspect out-of-sample chronological hold-out metrics (`2024–2025`), baseline comparisons, per-horizon accuracy (`h = 2, 3, 4`), predicted-vs-actual time series, 4×4 tier confusion matrices, and empirical rainfall-to-cases lag correlations.

## Held-Out Test Results (2024–2025 Targets, 18,900 Ward-Weeks)

| Model / Baseline | MAE | RMSE |
| :--- | :---: | :---: |
| **Horizon-Specialized Poisson HGB (This Model)** | **1.071** | **2.110** |
| Ward seasonal average | 1.259 | 2.453 |
| Last week's cases carried forward (persistence) | 1.861 | 3.582 |

- **$R^2$:** `0.720` | **Exact Tier Accuracy:** `78.9%` | **Within ±1 Tier:** `99.2%`
- **High/Critical Recall:** `59.5%` | **High/Critical Precision:** `60.3%`
- **80% Interval Coverage (`q10`–`q90`):** `94.0%` (well-calibrated conservative uncertainty bounds)

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
| :--- | :--- |
| `GET /api/bootstrap` | Available origin weeks, cities, wards, and calibrated tier thresholds |
| `GET /api/forecast?origin=2025-08-04&horizon=3&city=` | Risk tier, expected cases, and 80% interval for all 60 wards |
| `GET /api/ward/{ward_id}?origin=&horizon=` | 2–4 week forecast fan, Shapley drivers, key readings, and history |
| `POST /api/simulate` | Live What-If weather scenario simulation for a selected ward |
| `GET /api/validation` | Chronological hold-out metrics, baselines, confusion matrices, and lag evidence |
| `POST /api/retrain` | Re-ingest updated dataset, retrain models, and hot-reload predictor |

## AI Tools & APIs Disclosure

- **Claude (Anthropic):** Used during initial development to scaffold the multi-week lag feature pipeline, baseline training/validation scripts, unit test suite, and initial documentation structure. All generated code was reviewed, tested, and modified by the team.
- **Google Gemini:** Used for model optimization (horizon-specialized models for $h \in \{2, 3, 4\}$ and biological *Aedes* breeding interaction features), adding the live What-If weather simulator (`POST /api/simulate`) and hot-reload retraining endpoint (`POST /api/retrain`), frontend polish, and rubric verification.
- **External APIs & Model Endpoints:** None. No LLM endpoints, paid APIs, or external network calls are used during training or runtime inference (`$0.00` operational API/token cost).

## Attributions

- **Dataset:** `data/hackathon_preli_dataset.xlsx` provided by the EDU AI Engineering Hackathon 2026 organizers.
- **Open-Source Libraries:** Built with `scikit-learn`, `pandas`, `numpy`, `FastAPI`, `Uvicorn`, `joblib`, and `openpyxl` under their respective open-source (BSD/MIT) licenses.
- **Frontend Assets & Visualizations:** All HTML/CSS styling, interactive heatmap boards, forecast fans, and SVG charts in `static/` were built from scratch by the team with no external templates, icon fonts, or third-party charting libraries.