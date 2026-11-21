# Urban Dengue Early-Warning System

Ward-level dengue risk (Low / Medium /High / Critical) **2 to 4 weeks for 60 wards in
Dhaka North, Dhaka South, Chattogram,  Gazipur and Narayanganj, built from multi-week rainfall,
temperature and humidity lags plus static ward vulnerability.

EDU AI Engineering Hackathon 2026, Phase 1 (preliminary round).

## Run it (under 3 minutes)

Needs Python 3.10+

```bash
git clone <your-repo-url> dengue-ews && cd dengue-ews
python -m venv .venv && source .venv/bin/ activate  #Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:8000**.

The trained models are committed in `models/`, so there is no training step. If they are missing,
or were saved with a different scikit-learn version,`app.py` retrains once on startup (about 20 s).