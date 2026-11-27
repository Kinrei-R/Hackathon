"""Feature engineering: meteorological lags (0-8 wks), interactions, seasonality."""
import numpy as np
import pandas as pd

SHEET = "bangladesh_dengue_large_dataset"
METEO = ["rainfall_mm", "avg_temp_c", "relative_humidity_pct"]
MAX_LAG = 8
HORIZONS = (2, 3, 4)
STATIC = ["population_density_sqkm", "water_logging_risk_index", "sanitation_score"]
ID_COLS = ["date", "city", "ward_id"]


def load_panel(path):
    df = pd.read_excel(path, sheet_name=SHEET)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["ward_id", "date"]).reset_index(drop=True)


def add_interactions(f):
    """Interaction terms; recomputed by the counterfactual simulator."""
    f["rain_x_waterlog"] = f["rainfall_mm"] * f["water_logging_risk_index"]
    f["dens_x_unsanitary"] = f["population_density_sqkm"] * (1 - f["sanitation_score"])
    return f


def build_features(df):
    g = df.groupby("ward_id", sort=False)
    cols = {}
    for v in METEO:
        for k in range(MAX_LAG + 1):
            cols[f"{v}_lag{k}"] = g[v].shift(k)
    for k in range(4):
        cols[f"cases_lag{k}"] = g["dengue_cases"].shift(k)
    cols["cases_ma4"] = g["dengue_cases"].transform(lambda s: s.rolling(4).mean())
    woy = df["date"].dt.isocalendar().week.astype(float).to_numpy()
    cols["week_sin"] = np.sin(2 * np.pi * woy / 52.18)
    cols["week_cos"] = np.cos(2 * np.pi * woy / 52.18)
    base = df[ID_COLS + STATIC + ["rainfall_mm", "max_temp_c", "min_temp_c"]].copy()
    f = pd.concat([base, pd.DataFrame(cols, index=df.index)], axis=1)
    f = add_interactions(f)
    for h in HORIZONS:
        f[f"y{h}"] = g["dengue_cases"].shift(-h)
    return f


def feature_columns(f):
    return [c for c in f.columns if c not in ID_COLS and not c.startswith("y")]
