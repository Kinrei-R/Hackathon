"""Dengue early-warning dashboard: FastAPI server + static front end.

Start:  python app.py           (opens on http://127.0.0.1:8000)
   or:  uvicorn app:app --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException, query
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
