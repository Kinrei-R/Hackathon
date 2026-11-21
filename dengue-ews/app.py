"""Dengue early-warning dashboard: FastAPI server + static front end.

Start:  python app.py           (opens on http://127.0.0.1:8000)
   or:  uvicorn app:app --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.inference import Predictor, models_ready

ROOT = Path(__file__).resolve().parent
STATE: dict[str, Predictor] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not models_ready():  # fresh clone without model files: train once (~20 s)
        print("Model artifacts not found - training once (about 20 seconds)...")
        from src.train import main as train

        train()
    try:
        STATE["p"] = Predictor()
    except Exception as exc:  # e.g. model pickled with a different scikit-learn version
        print(f"Could not load saved models ({exc.__class__.__name__}); retraining once...")
        from src.train import main as train

        train()
        STATE["p"] = Predictor()
    yield


app = FastAPI(title="Urban Dengue Early-Warning System", version="1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def _check_origin(origin: str | None) -> str | None:
    if origin is None:
        return None
    try:
        pd.Timestamp(origin)
    except (ValueError, TypeError):
        raise HTTPException(422, "origin must be a date like 2025-08-04")
    return origin


def _cached(payload: dict, seconds: int = 300):
    from fastapi.responses import JSONResponse

    return JSONResponse(payload, headers={"Cache-Control": f"public, max-age={seconds}"})


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "model_trained_at": STATE["p"].meta["trained_at"]}


@app.get("/api/bootstrap")
def bootstrap():
    return _cached(STATE["p"].bootstrap(), 3600)


@app.get("/api/forecast")
def forecast(origin: str | None = None, horizon: int = Query(3, ge=2, le=4), city: str | None = None):
    """Risk tiers for every ward at one forecast origin week and lead time."""
    return _cached(STATE["p"].forecast(_check_origin(origin), horizon, city), 600)


@app.get("/api/ward/{ward_id}")
def ward(ward_id: str, origin: str | None = None, horizon: int = Query(3, ge=2, le=4)):
    """Forecast fan (2-4 wk), driver breakdown, key readings and recent history for one ward."""
    try:
        return _cached(STATE["p"].ward_detail(ward_id, _check_origin(origin), horizon), 600)
    except KeyError:
        raise HTTPException(404, f"Unknown ward_id {ward_id}")


@app.get("/api/validation")
def validation():
    """Chronological hold-out metrics, baselines, confusion matrices and lag evidence."""
    return _cached(STATE["p"].validation(), 3600)


if __name__ == "__main__":
    print("Dashboard: http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
