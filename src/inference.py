"""Inference: forecasts (mean, q10, q90) for t+2..t+4 and model-driven counterfactual effects.

If serialized models cannot be loaded, the engine falls back to precomputed
forecasts.csv / effects.json (fully deterministic, no sklearn needed at runtime).
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .features import add_interactions
from .operations import K_MAX, WEIGHTS, intervene, fallback_factor

KINDS = ("mean", "q10", "q90")


class Engine:
    def __init__(self, art="artifacts", scenario="live"):
        """scenario 'live': newest data, final models. 'peak': out-of-sample replay at the holdout peak week."""
        self.art, self.scenario = Path(art), scenario
        self.tag = "" if scenario == "live" else "_peak"
        mdir = "models" if scenario == "live" else "models_holdout"
        self.meta = json.loads((self.art / "meta.json").read_text())
        self.as_of = self.meta["as_of"] if scenario == "live" else self.meta["peak_origin"]
        self.hz = self.meta["horizons"]
        self.cols = self.meta["features"]
        self.wards = {w["ward_id"]: w for w in self.meta["wards"]}
        self.ward_ids = sorted(self.wards)
        self.models, self.latest, self.mode = None, None, "precomputed"
        try:
            self.latest = joblib.load(self.art / f"latest{self.tag}.joblib")
            self.models = {(h, k): joblib.load(self.art / mdir / f"h{h}_{k}.joblib")
                           for h in self.hz for k in KINDS}
            self.mode = "ml"
        except Exception:
            self.models = None
        self._fc, self._fx = None, None

    # ---- forecasts -------------------------------------------------------
    def _predict(self, X):
        out = {}
        for h in self.hz:
            mean = np.maximum(self.models[(h, "mean")].predict(X[self.cols]), 0)
            lo = np.minimum(np.maximum(self.models[(h, "q10")].predict(X[self.cols]), 0), mean)
            hi = np.maximum(self.models[(h, "q90")].predict(X[self.cols]), mean)
            out[h] = (mean, lo, hi)
        return out

    def forecast_df(self):
        if self._fc is not None:
            return self._fc
        if self.models:
            pred = self._predict(self.latest)
            df = pd.DataFrame({f"h{h}_{n}": pred[h][i] for h in self.hz for i, n in enumerate(("mean", "lo", "hi"))},
                              index=self.latest.index)
        else:
            df = pd.read_csv(self.art / f"forecasts{self.tag}.csv", index_col="ward_id")
        df = df.loc[self.ward_ids]
        df["expected"] = df[[f"h{h}_mean" for h in self.hz]].mean(axis=1)
        df["upper"] = df[[f"h{h}_hi" for h in self.hz]].mean(axis=1)
        self._fc = df
        return df

    def target_dates(self):
        t0 = pd.Timestamp(self.as_of)
        return {h: str((t0 + pd.Timedelta(weeks=h)).date()) for h in self.hz}

    # ---- counterfactual effects -----------------------------------------
    def effects(self):
        """{ward: {"delta": [k][h] cases averted per horizon, "src": [k][h] 'ml'|'fallback'}}"""
        if self._fx is not None:
            return self._fx
        fp = self.art / f"effects{self.tag}.json"
        if not self.models and fp.exists():
            self._fx = json.loads(fp.read_text())
            return self._fx
        fc = self.forecast_df()
        ml = {}
        if self.models:
            for k in range(K_MAX + 1):
                X = self.latest.copy()
                wl, s = intervene(X["water_logging_risk_index"], X["sanitation_score"], k)
                X["water_logging_risk_index"], X["sanitation_score"] = wl, s
                ml[k] = self._predict(add_interactions(X))
        idx = {w: i for i, w in enumerate(self.latest.index)} if self.models else {}
        fx = {}
        for w in self.ward_ids:
            info = self.wards[w]
            delta, src = [], []
            for k in range(K_MAX + 1):
                wl2, s2 = intervene(info["wl"], info["san"], k)
                fac = fallback_factor(info["wl"], info["san"], wl2, s2)
                drow, srow = [], []
                for h in self.hz:
                    base = float(fc.loc[w, f"h{h}_mean"])
                    d_fb = base * (1 - fac)
                    d_ml = base - float(ml[k][h][0][idx[w]]) if self.models else 0.0
                    if k > 0 and d_ml > 0:
                        drow.append(min(d_ml, base)); srow.append("ml")
                    else:
                        drow.append(d_fb if k > 0 else 0.0); srow.append("fallback")
                delta.append(drow); src.append(srow)
            fx[w] = {"delta": delta, "src": src}
        self._fx = fx
        return fx

    # ---- artifacts -------------------------------------------------------
    @classmethod
    def precompute(cls, art="artifacts", scenario="live"):
        """Write forecasts + effects so the app works without model files."""
        e = cls(art, scenario)
        assert e.models, "models must load to precompute"
        e.forecast_df().drop(columns=["expected", "upper"]).to_csv(Path(art) / f"forecasts{e.tag}.csv", index_label="ward_id")
        (Path(art) / f"effects{e.tag}.json").write_text(json.dumps(e.effects()))
