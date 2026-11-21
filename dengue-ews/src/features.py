"""Grouped multi-week lag feature pipeline with biological & spatial interactions.

Every feature is computed *per ward* (groupby ward_id) or *per city* at or before
forecast origin week t, so nothing from the future leaks into a prediction.
Target for horizon h (2, 3 or 4 weeks) is dengue_cases at week t + h.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (2, 3, 4)
MAX_LAG = 8
MIN_HISTORY_WEEKS = MAX_LAG

STATIC_COLS = ["population_density_sqkm", "water_logging_risk_index", "sanitation_score"]

FEATURE_GROUPS: dict[str, list[str]] = {
    "Rainfall 0-1 weeks ago": ["rain_lag_0", "rain_lag_1", "rain_momentum"],
    "Rainfall 2-4 weeks ago (breeding window)": [
        "rain_lag_2",
        "rain_lag_3",
        "rain_lag_4",
        "rain_breeding_win",
        "city_rain_breeding_win",
    ],
    "Rainfall 5-8 weeks ago": ["rain_lag_5", "rain_lag_6", "rain_lag_7", "rain_lag_8"],
    "Cumulative rainfall": ["rain_sum_2w", "rain_sum_4w", "rain_sum_8w", "rain_max_4w", "rain_wet_weeks_8w"],
    "Temperature": ["temp_lag_0", "temp_lag_2", "temp_lag_4", "temp_mean_4w", "tmin_mean_4w", "temp_opt_score"],
    "Humidity": ["hum_lag_0", "hum_lag_2", "hum_lag_4", "hum_mean_4w"],
    "Ward vulnerability & breeding synergy": [
        *STATIC_COLS,
        "stagnation_hazard",
        "breeding_suitability_idx",
        "crowding_sanitation_risk",
    ],
    "Time of year and lead time": ["target_woy_sin", "target_woy_cos", "target_woy_sin2", "target_woy_cos2", "horizon"],
}
FEATURE_COLS: list[str] = [c for cols in FEATURE_GROUPS.values() for c in cols]
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

    # 1. Individual & rolling rainfall lags
    for k in range(MAX_LAG + 1):
        out[f"rain_lag_{k}"] = g["rainfall_mm"].shift(k)
    out["rain_sum_2w"] = _roll(g, "rainfall_mm", 2, "sum")
    out["rain_sum_4w"] = _roll(g, "rainfall_mm", 4, "sum")
    out["rain_sum_8w"] = _roll(g, "rainfall_mm", 8, "sum")
    out["rain_max_4w"] = _roll(g, "rainfall_mm", 4, "max")
    out["rain_breeding_win"] = out["rain_lag_2"] + out["rain_lag_3"] + out["rain_lag_4"]
    out["rain_momentum"] = out["rain_sum_2w"] - (out["rain_lag_2"] + out["rain_lag_3"])

    df["_wet"] = (df["rainfall_mm"] > 50).astype(float)
    out["rain_wet_weeks_8w"] = df.groupby("ward_id", sort=False)["_wet"].transform(
        lambda s: s.rolling(8, min_periods=8).sum()
    )

    # 2. Temperature & humidity lags + Aedes thermal suitability (peaks around 28.5 C)
    for k in (0, 2, 4):
        out[f"temp_lag_{k}"] = g["avg_temp_c"].shift(k)
        out[f"hum_lag_{k}"] = g["relative_humidity_pct"].shift(k)
    out["temp_mean_4w"] = _roll(g, "avg_temp_c", 4, "mean")
    out["tmin_mean_4w"] = _roll(g, "min_temp_c", 4, "mean")
    out["hum_mean_4w"] = _roll(g, "relative_humidity_pct", 4, "mean")
    out["temp_opt_score"] = np.exp(-0.5 * ((out["temp_mean_4w"] - 28.5) / 3.5) ** 2)

    # 3. Domain interactions: standing water + optimal mosquito climate + urban crowding
    out["stagnation_hazard"] = out["rain_breeding_win"] * out["water_logging_risk_index"]
    out["breeding_suitability_idx"] = (
        out["rain_breeding_win"] * out["temp_opt_score"] * (out["hum_mean_4w"] / 100.0)
    )
    out["crowding_sanitation_risk"] = (out["population_density_sqkm"] / 10000.0) * (
        1.05 - out["sanitation_score"].clip(0, 1)
    )

    # 4. City-corporation wide breeding-window rainfall (captures urban spillover)
    out["city_rain_breeding_win"] = out.groupby(["city", "date"])["rain_breeding_win"].transform("mean")

    # 5. Case history (for baselines/ablation only, excluded from production model)
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
    """Return model-ready frame for lead time h (adds horizon + 1st/2nd harmonic seasonality)."""
    X = panel.copy()
    X["horizon"] = np.float32(h)
    X["target_date"] = X["date"] + pd.to_timedelta(7 * h, unit="D")
    woy = X["target_date"].dt.isocalendar().week.astype("float32").clip(upper=52)
    X["target_woy_sin"] = np.sin(2 * np.pi * woy / 52).astype("float32")
    X["target_woy_cos"] = np.cos(2 * np.pi * woy / 52).astype("float32")
    X["target_woy_sin2"] = np.sin(4 * np.pi * woy / 52).astype("float32")
    X["target_woy_cos2"] = np.cos(4 * np.pi * woy / 52).astype("float32")
    X["y"] = X[f"y_h{h}"]
    return X


def stack_horizons(panel: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
    """Long training frame: one block per horizon, rows without a known target dropped."""
    parts = [add_horizon(panel, h) for h in horizons]
    long = pd.concat(parts, ignore_index=True)
    return long.dropna(subset=["y"]).reset_index(drop=True)