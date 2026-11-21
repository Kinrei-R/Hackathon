"""Grouped multi-week lag feature pipeline.

Every feature is computed *per ward* (groupby ward_id) from data available at the
forecast origin week t, so nothing from the future leaks into a prediction.
Target for horizon h (2, 3 or 4 weeks) is dengue_cases at week t + h.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (2, 3, 4)
MAX_LAG = 8  # weeks of rainfall history kept as individual lag columns
MIN_HISTORY_WEEKS = MAX_LAG  # first usable origin needs 8 weeks of history

STATIC_COLS = ["population_density_sqkm", "water_logging_risk_index", "sanitation_score"]

# Human-readable driver groups used by the explanation layer.
FEATURE_GROUPS: dict[str, list[str]] = {
    "Rainfall 0-1 weeks ago": ["rain_lag_0", "rain_lag_1"],
    "Rainfall 2-4 weeks ago (breeding window)": ["rain_lag_2", "rain_lag_3", "rain_lag_4"],
    "Rainfall 5-8 weeks ago": ["rain_lag_5", "rain_lag_6", "rain_lag_7", "rain_lag_8"],
    "Cumulative rainfall": ["rain_sum_2w", "rain_sum_4w", "rain_sum_8w", "rain_max_4w", "rain_wet_weeks_8w"],
    "Temperature": ["temp_lag_0", "temp_lag_2", "temp_lag_4", "temp_mean_4w", "tmin_mean_4w"],
    "Humidity": ["hum_lag_0", "hum_lag_2", "hum_lag_4", "hum_mean_4w"],
    "Ward vulnerability": STATIC_COLS,
    "Time of year and lead time": ["target_woy_sin", "target_woy_cos", "horizon"],
}
FEATURE_COLS: list[str] = [c for cols in FEATURE_GROUPS.values() for c in cols]
# Surveillance case history: computed for baselines/ablation only, NOT used by the production model
# (hospital reporting lags would eat into the early-warning window).
CASE_COLS: list[str] = ["cases_lag_0", "cases_lag_1", "cases_lag_2", "cases_lag_3", "cases_mean_4w", "cases_trend"]


def load_raw(path: str) -> pd.DataFrame:
    """Read the hackathon workbook and normalise column names to lower case."""
    df = pd.read_excel(path, sheet_name="bangladesh_dengue_large_dataset")
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["ward_id", "date"]).reset_index(drop=True)


def _roll(g, col: str, window: int, how: str) -> pd.Series:
    return g[col].transform(lambda s: getattr(s.rolling(window, min_periods=window), how)())


def build_panel(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (ward, origin week) with lag features and future targets y_h{h}."""
    df = df.sort_values(["ward_id", "date"]).reset_index(drop=True)
    g = df.groupby("ward_id", sort=False)
    out = df[["date", "city", "ward_id", *STATIC_COLS]].copy()

    for k in range(MAX_LAG + 1):
        out[f"rain_lag_{k}"] = g["rainfall_mm"].shift(k)
    out["rain_sum_2w"] = _roll(g, "rainfall_mm", 2, "sum")
    out["rain_sum_4w"] = _roll(g, "rainfall_mm", 4, "sum")
    out["rain_sum_8w"] = _roll(g, "rainfall_mm", 8, "sum")
    out["rain_max_4w"] = _roll(g, "rainfall_mm", 4, "max")
    df["_wet"] = (df["rainfall_mm"] > 50).astype(float)
    out["rain_wet_weeks_8w"] = df.groupby("ward_id", sort=False)["_wet"].transform(
        lambda s: s.rolling(8, min_periods=8).sum()
    )

    for k in (0, 2, 4):
        out[f"temp_lag_{k}"] = g["avg_temp_c"].shift(k)
        out[f"hum_lag_{k}"] = g["relative_humidity_pct"].shift(k)
    out["temp_mean_4w"] = _roll(g, "avg_temp_c", 4, "mean")
    out["tmin_mean_4w"] = _roll(g, "min_temp_c", 4, "mean")
    out["hum_mean_4w"] = _roll(g, "relative_humidity_pct", 4, "mean")

    for k in range(4):
        out[f"cases_lag_{k}"] = g["dengue_cases"].shift(k)
    out["cases_mean_4w"] = _roll(g, "dengue_cases", 4, "mean")
    out["cases_trend"] = out["cases_lag_0"] - out["cases_lag_3"]

    for h in HORIZONS:
        out[f"y_h{h}"] = g["dengue_cases"].shift(-h)

    out["origin_idx"] = g.cumcount()
    out = out[out["origin_idx"] >= MIN_HISTORY_WEEKS].drop(columns="origin_idx")
    num = out.select_dtypes("number").columns
    out[num] = out[num].astype("float32")
    return out.reset_index(drop=True)


def add_horizon(panel: pd.DataFrame, h: int) -> pd.DataFrame:
    """Return model-ready frame for lead time h (adds horizon + target-week seasonality)."""
    X = panel.copy()
    X["horizon"] = np.float32(h)
    X["target_date"] = X["date"] + pd.to_timedelta(7 * h, unit="D")
    woy = X["target_date"].dt.isocalendar().week.astype("float32").clip(upper=52)
    X["target_woy_sin"] = np.sin(2 * np.pi * woy / 52).astype("float32")
    X["target_woy_cos"] = np.cos(2 * np.pi * woy / 52).astype("float32")
    X["y"] = X[f"y_h{h}"]
    return X


def stack_horizons(panel: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
    """Long training frame: one block per horizon, rows without a known target dropped."""
    parts = [add_horizon(panel, h) for h in horizons]
    long = pd.concat(parts, ignore_index=True)
    return long.dropna(subset=["y"]).reset_index(drop=True)
