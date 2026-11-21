"""Fast local inference: serialized models, in-memory feature store, driver attribution.

No network calls, no paid APIs. A full 60-ward forecast is three vectorised
`predict` calls on a 60-row matrix (a few milliseconds) and is memoised.
"""
from __future__ import annotations

import json
from functools import lru_cache
from math import factorial
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .features import FEATURE_COLS, FEATURE_GROUPS, HORIZONS, add_horizon

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
TIERS = ["Low", "Medium", "High", "Critical"]
HISTORY_WEEKS = 16
SHAP_BG = 40  # background rows for attribution
_M = len(FEATURE_GROUPS)
_SHAP_W = [factorial(k) * factorial(_M - k - 1) / factorial(_M) for k in range(_M)]


def models_ready() -> bool:
    need = ["dengue_model.joblib", "dengue_q10.joblib", "dengue_q90.joblib", "feature_store.joblib", "model_metadata.json"]
    return all((MODELS / n).exists() for n in need)


class Predictor:
    def __init__(self) -> None:
        self.meta = json.loads((MODELS / "model_metadata.json").read_text())
        self.mean = joblib.load(MODELS / "dengue_model.joblib")
        self.q10 = joblib.load(MODELS / "dengue_q10.joblib")
        self.q90 = joblib.load(MODELS / "dengue_q90.joblib")
        store = joblib.load(MODELS / "feature_store.joblib")
        self.panel: pd.DataFrame = store["panel"]
        self.wards: pd.DataFrame = store["wards"].set_index("ward_id")
        self.bg: pd.DataFrame = store["background"]
        self.thr: list[float] = self.meta["tiers"]["thresholds_cases_per_ward_week"]
        self.origins = sorted(self.panel["date"].unique())
        self.origin_strs = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in self.origins]
        self._by_date = {pd.Timestamp(d): g.reset_index(drop=True) for d, g in self.panel.groupby("date")} # type: ignore
        self._group_idx = {g: [FEATURE_COLS.index(c) for c in cols] for g, cols in FEATURE_GROUPS.items()}
        self._bg_mat = self.bg[FEATURE_COLS].to_numpy(dtype=np.float64)
        self._bg_mean = self.bg.mean()
        self._explain_cache: dict = {}

    # ---------- tiers ----------
    def tier(self, cases: float) -> str:
        return TIERS[int(np.searchsorted(self.thr, cases, side="right"))]

    def score(self, cases: float) -> float:
        """0-100 risk score; tier cut points map to 25/50/75, 2x critical cut point to 100."""
        t = self.thr
        return float(np.interp(cases, [0, t[0], t[1], t[2], 2 * t[2]], [0, 25, 50, 75, 100]))

    def snap_origin(self, origin: str | None) -> pd.Timestamp:
        """Latest available forecast origin on or before the requested date."""
        if not origin:
            return pd.Timestamp(self.origins[-1])
        ts = pd.Timestamp(origin)
        ok = [d for d in self.origins if d <= np.datetime64(ts)]
        return pd.Timestamp(ok[-1] if ok else self.origins[0])

    # ---------- forecasts ----------
    def _frame(self, origin: pd.Timestamp, h: int) -> pd.DataFrame:
        return add_horizon(self._by_date[origin], h)

    @lru_cache(maxsize=512)
    def _forecast_cached(self, origin_str: str, h: int) -> tuple:
        origin = pd.Timestamp(origin_str)
        fr = self._frame(origin, h)
        X = fr[FEATURE_COLS]  # DataFrame keeps feature names
        p = np.clip(self.mean.predict(X), 0, None)
        lo = np.minimum(np.clip(self.q10.predict(X), 0, None), p)
        hi = np.maximum(self.q90.predict(X), p)
        rows = []
        for i, r in fr.iterrows():
            w = self.wards.loc[r.ward_id]
            actual = None if np.isnan(r.y) else float(r.y)
            rows.append({
                "ward_id": r.ward_id, "city": r.city, "predicted_cases": round(float(p[i]), 2),
                "low": round(float(lo[i]), 2), "high": round(float(hi[i]), 2),
                "tier": self.tier(p[i]), "worst_case_tier": self.tier(hi[i]), "risk_score": round(self.score(p[i]), 1),
                "actual_cases": actual, "actual_tier": None if actual is None else self.tier(actual),
                "water_logging_risk_index": float(w.water_logging_risk_index),
                "sanitation_score": float(w.sanitation_score),
                "population_density_sqkm": int(w.population_density_sqkm),
            })
        return tuple(rows), fr["target_date"].iloc[0].strftime("%Y-%m-%d")

    def forecast(self, origin: str | None, h: int, city: str | None = None) -> dict:
        o = self.snap_origin(origin)
        rows, target = self._forecast_cached(o.strftime("%Y-%m-%d"), int(h))
        rows = [r for r in rows if not city or city == "All cities" or r["city"] == city]
        counts = {t: 0 for t in TIERS}
        for r in rows:
            counts[r["tier"]] += 1
        return {"origin": o.strftime("%Y-%m-%d"), "target_date": target, "horizon_weeks": int(h),
                "is_latest": o == pd.Timestamp(self.origins[-1]), "tier_counts": counts,
                "wards": sorted(rows, key=lambda r: -r["predicted_cases"])}

    # ---------- driver breakdown ----------
    def _explain(self, row: pd.DataFrame) -> list[dict]:
        """Exact Shapley values over feature *groups* (interventional, background sample).

        v(S) = mean over background rows b of f(x_S, b_rest). Groups, not single columns,
        so correlated lag columns share credit instead of masking each other, and 8 groups
        means only 256 coalitions -> one vectorised predict call of ~10k rows (~50 ms).
        Contributions sum to f(x) - E[f(background)]; positive pushes expected cases up.
        """
        x = row[FEATURE_COLS].to_numpy(dtype=np.float64)[0]
        bg = self._bg_mat[:SHAP_BG]
        n, groups = len(bg), list(self._group_idx)
        m = len(groups)
        blocks = []
        for mask in range(1 << m):
            M = bg.copy()
            for gi, g in enumerate(groups):
                if mask >> gi & 1:
                    M[:, self._group_idx[g]] = x[self._group_idx[g]]
            blocks.append(M)
        preds = self.mean.predict(pd.DataFrame(np.vstack(blocks), columns=FEATURE_COLS))
        v = preds.reshape(1 << m, n).mean(axis=1)
        phi = np.zeros(m)
        for mask in range(1 << m):
            k = bin(mask).count("1")
            for gi in range(m):
                if not mask >> gi & 1:
                    phi[gi] += _SHAP_W[k] * (v[mask | 1 << gi] - v[mask])
        out = [{"driver": g, "contribution": round(float(p), 3)} for g, p in zip(groups, phi)]
        return sorted(out, key=lambda d: -abs(d["contribution"]))

    def _explain_cached(self, ward_id: str, origin: str, h: int, row: pd.DataFrame) -> list[dict]:
        key = (ward_id, origin, h)
        if key not in self._explain_cache:
            if len(self._explain_cache) > 2000:
                self._explain_cache.clear()
            self._explain_cache[key] = self._explain(row)
        return self._explain_cache[key]

    def _facts(self, row: pd.DataFrame) -> list[dict]:
        r = row.iloc[0]
        b = self._bg_mean
        rain_win = float(r.rain_lag_2 + r.rain_lag_3 + r.rain_lag_4)
        bg_win = float(b.rain_lag_2 + b.rain_lag_3 + b.rain_lag_4)
        return [
            {"label": "Rain 2-4 weeks ago (total)", "value": round(rain_win, 1), "typical": round(bg_win, 1), "unit": "mm"},
            {"label": "Rain, last 4 weeks", "value": round(float(r.rain_sum_4w), 1), "typical": round(float(b.rain_sum_4w), 1), "unit": "mm"},
            {"label": "Mean temperature, last 4 weeks", "value": round(float(r.temp_mean_4w), 1), "typical": round(float(b.temp_mean_4w), 1), "unit": "C"},
            {"label": "Mean humidity, last 4 weeks", "value": round(float(r.hum_mean_4w), 1), "typical": round(float(b.hum_mean_4w), 1), "unit": "%"},
            {"label": "Water-logging risk index", "value": round(float(r.water_logging_risk_index), 2), "typical": round(float(b.water_logging_risk_index), 2), "unit": ""},
            {"label": "Sanitation score", "value": round(float(r.sanitation_score), 2), "typical": round(float(b.sanitation_score), 2), "unit": ""},
        ]

    def ward_detail(self, ward_id: str, origin: str | None, h: int) -> dict:
        if ward_id not in self.wards.index:
            raise KeyError(ward_id)
        o = self.snap_origin(origin)
        horizons = {}
        for hh in HORIZONS:
            rows, tdate = self._forecast_cached(o.strftime("%Y-%m-%d"), hh)
            r = next(x for x in rows if x["ward_id"] == ward_id)
            horizons[str(hh)] = {**r, "target_date": tdate}
        row = self._frame(o, int(h))
        row = row[row.ward_id == ward_id].reset_index(drop=True)

        hist = self.panel[(self.panel.ward_id == ward_id) & (self.panel.date <= o) &
                          (self.panel.date > o - pd.Timedelta(weeks=HISTORY_WEEKS))]
        history = [{"date": d.strftime("%Y-%m-%d"), "cases": float(c), "rain_mm": round(float(rn), 1),
                    "temp_c": round(float(t), 1), "humidity_pct": round(float(hu), 1)}
                   for d, c, rn, t, hu in zip(hist.date, hist.cases_lag_0, hist.rain_lag_0, hist.temp_lag_0, hist.hum_lag_0)]
        later = self.panel[(self.panel.ward_id == ward_id) & (self.panel.date > o) &
                           (self.panel.date <= o + pd.Timedelta(weeks=4))]
        realised = [{"date": d.strftime("%Y-%m-%d"), "cases": float(c)} for d, c in zip(later.date, later.cases_lag_0)]
        w = self.wards.loc[ward_id]
        return {"ward_id": ward_id, "city": w.city, "origin": o.strftime("%Y-%m-%d"), "horizon_weeks": int(h),
                "static": {"population_density_sqkm": int(w.population_density_sqkm), # type: ignore
                           "water_logging_risk_index": float(w.water_logging_risk_index), # type: ignore
                           "sanitation_score": float(w.sanitation_score)}, # type: ignore
                "horizons": horizons, "drivers": self._explain_cached(ward_id, o.strftime("%Y-%m-%d"), int(h), row), "facts": self._facts(row),
                "history": history, "realised_after_origin": realised}

    # ---------- metadata for UI ----------
    def bootstrap(self) -> dict:
        m = self.meta
        wards = [{"ward_id": k, "city": v.city} for k, v in self.wards.iterrows()]
        return {"origins": self.origin_strs, "latest_origin": self.origin_strs[-1],
                "cities": ["All cities"] + sorted(self.wards.city.unique()), "wards": wards,
                "horizons": m["horizons"], "tiers": {"names": TIERS, "thresholds": self.thr},
                "data_range": m["data_range"], "trained_at": m["trained_at"]}

    def validation(self) -> dict:
        m = self.meta
        return {"split": m["split"], "model": m["model"], "metrics": m["metrics"], "lag_correlations": m["lag_correlations"],
                "tiers": m["tiers"]}
