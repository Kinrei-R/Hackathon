"""Chronological training, quantile intervals, tier calibration and metrics export.

Split is by TARGET date so that no training label overlaps the evaluation period:
    train: targets  <= 2022-12-31      (model fitting)
    val  : targets in 2023             (choose number of trees, nothing else)
    test : targets  >= 2024-01-01      (touched once, for reporting)
The shipped model is refit on train+val with the chosen tree count.

Run:  python -m src.train
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor as HGB
from sklearn.metrics import mean_absolute_error, mean_poisson_deviance, mean_squared_error

from .features import CASE_COLS, FEATURE_COLS, HORIZONS, build_panel, load_raw, stack_horizons

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "hackathon_preli_dataset.xlsx"
MODELS = ROOT / "models"
TRAIN_END, VAL_END = pd.Timestamp("2022-12-31"), pd.Timestamp("2023-12-31")
TIERS = ["Low", "Medium", "High", "Critical"]
TIER_QUANTILES = (0.65, 0.85, 0.96)  # of training case counts -> Low|Medium|High|Critical cut points
SEED = 42


def tier_index(pred, thresholds) -> np.ndarray:
    return np.searchsorted(np.asarray(thresholds), np.asarray(pred), side="right")


def _base(loss="poisson", n=400, **kw):
    return HGB(loss=loss, max_iter=n, learning_rate=0.05, max_leaf_nodes=24, min_samples_leaf=40,
               l2_regularization=1.0, early_stopping=False, random_state=SEED, **kw)


def _metrics(y, p) -> dict:
    p = np.clip(p, 1e-6, None)
    return {"mae": float(mean_absolute_error(y, p)),
            "rmse": float(np.sqrt(mean_squared_error(y, p))),
            "poisson_deviance": float(mean_poisson_deviance(y, p))}


def main() -> None:
    t0 = time.time()
    MODELS.mkdir(exist_ok=True)
    raw = load_raw(str(DATA))
    panel = build_panel(raw)
    long = stack_horizons(panel)
    print(f"panel {panel.shape}, stacked training frame {long.shape}")

    tr = long[long.target_date <= TRAIN_END]
    va = long[(long.target_date > TRAIN_END) & (long.target_date <= VAL_END)]
    te = long[long.target_date > VAL_END]
    trva = pd.concat([tr, va])
    print(f"train {len(tr)}  val {len(va)}  test {len(te)}")

    # 1) pick tree count on validation (chronologically after train)
    probe = _base(n=700).fit(tr[FEATURE_COLS], tr.y)
    devs = [mean_poisson_deviance(va.y, np.clip(p, 1e-6, None))
            for p in probe.staged_predict(va[FEATURE_COLS])]
    best_n = int(np.argmin(devs)) + 1
    print(f"best n_estimators on val: {best_n}")

    # 2) refit on train+val; quantile models for the 80% interval
    mean_m = _base(n=best_n).fit(trva[FEATURE_COLS], trva.y)
    q_n = max(150, best_n // 2)
    q10 = _base("quantile", q_n, quantile=0.10).fit(trva[FEATURE_COLS], trva.y)
    q90 = _base("quantile", q_n, quantile=0.90).fit(trva[FEATURE_COLS], trva.y)

    # 3) risk tiers: thresholds from *training* case distribution only
    raw_thr = [float(np.quantile(trva.y, q)) for q in TIER_QUANTILES]
    thr, prev = [], 0.0
    for t in raw_thr:  # keep strictly increasing
        prev = max(t, prev + 0.5)
        thr.append(prev)
    print("tier thresholds (cases/ward-week):", thr)

    # 4) test evaluation
    Xte, yte = te[FEATURE_COLS], te.y.to_numpy()
    p, lo, hi = mean_m.predict(Xte), q10.predict(Xte), q90.predict(Xte)
    lo, hi = np.minimum(lo, p), np.maximum(hi, p)
    te = te.assign(pred=p, lo=lo, hi=hi)

    with_cases = _base(n=best_n).fit(trva[FEATURE_COLS + CASE_COLS], trva.y)
    seas = trva.assign(woy=trva.target_date.dt.isocalendar().week.clip(upper=52).astype(int))
    seas_mean = seas.groupby(["ward_id", "woy"]).y.mean()
    te_woy = te.target_date.dt.isocalendar().week.clip(upper=52).astype(int)
    seas_pred = np.array([seas_mean.get((w, k), 0.0) for w, k in zip(te.ward_id, te_woy)])

    ti_true, ti_pred = tier_index(yte, thr), tier_index(p, thr)
    metrics = {
        "overall": {**_metrics(yte, p), "r2": float(np.corrcoef(yte, p)[0, 1] ** 2),
                    "interval_80_coverage": float(np.mean((yte >= lo) & (yte <= hi))),
                    "tier_accuracy": float(np.mean(ti_true == ti_pred)),
                    "tier_within_one": float(np.mean(np.abs(ti_true - ti_pred) <= 1)),
                    "high_or_critical_recall": float(np.mean(ti_pred[ti_true >= 2] >= 2)),
                    "high_or_critical_precision": float(np.mean(ti_true[ti_pred >= 2] >= 2))},
        "baselines": {"persistence_last_week_cases": _metrics(yte, te.cases_lag_0.to_numpy()),
                      "ward_seasonal_mean": _metrics(yte, seas_pred),
                      "ablation_plus_case_history_model": _metrics(yte, with_cases.predict(te[FEATURE_COLS + CASE_COLS]))},
        "by_horizon": {}, "confusion": {}, "series": {},
    }
    for h in HORIZONS:
        m = (te.horizon == h).to_numpy()
        metrics["by_horizon"][str(h)] = {**_metrics(yte[m], p[m]),
                                         "interval_80_coverage": float(np.mean((yte[m] >= lo[m]) & (yte[m] <= hi[m]))),
                                         "tier_accuracy": float(np.mean(ti_true[m] == ti_pred[m]))}
        cm = np.zeros((4, 4), int)
        np.add.at(cm, (ti_true[m], ti_pred[m]), 1)
        metrics["confusion"][str(h)] = cm.tolist()
        sub = te[m]
        s = {}
        for name, grp in [("All cities", sub)] + list(sub.groupby("city")):
            a = grp.groupby("target_date").agg(actual=("y", "sum"), predicted=("pred", "sum"))
            s[name] = [{"date": d.strftime("%Y-%m-%d"), "actual": float(r.actual), "predicted": round(float(r.predicted), 2)}
                       for d, r in a.iterrows()]
        metrics["series"][str(h)] = s

    # 5) lag evidence (shown in the UI): correlation of cases with rainfall k weeks earlier
    g = raw.groupby("ward_id")
    lagcorr = {str(k): float(raw.dengue_cases.corr(g.rainfall_mm.shift(k))) for k in range(0, 9)}

    # 6) persist
    bg = trva.sample(150, random_state=SEED)[FEATURE_COLS].reset_index(drop=True)
    wards = raw.groupby("ward_id").agg(
        city=("city", "first"), population_density_sqkm=("population_density_sqkm", "first"),
        water_logging_risk_index=("water_logging_risk_index", "first"),
        sanitation_score=("sanitation_score", "first")).reset_index()
    joblib.dump(mean_m, MODELS / "dengue_model.joblib", compress=3)
    joblib.dump(q10, MODELS / "dengue_q10.joblib", compress=3)
    joblib.dump(q90, MODELS / "dengue_q90.joblib", compress=3)
    joblib.dump({"panel": panel, "wards": wards, "background": bg}, MODELS / "feature_store.joblib", compress=3)
    meta = {
        "trained_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "feature_cols": FEATURE_COLS, "horizons": list(HORIZONS),
        "split": {"train_targets_through": str(TRAIN_END.date()), "validation_year": 2023,
                  "test_targets_from": "2024-01-01", "n_train": len(tr), "n_val": len(va), "n_test": len(te)},
        "model": {"type": "HistGradientBoostingRegressor (Poisson) + 2 quantile models (q10, q90)",
                  "n_estimators": best_n, "quantile_n_estimators": q_n},
        "tiers": {"names": TIERS, "thresholds_cases_per_ward_week": thr, "quantiles": list(TIER_QUANTILES)},
        "data_range": {"first": str(raw.date.min().date()), "last": str(raw.date.max().date())},
        "lag_correlations": lagcorr, "metrics": metrics,
    }
    (MODELS / "model_metadata.json").write_text(json.dumps(meta, indent=2))
    o = metrics["overall"]
    print(f"TEST  MAE {o['mae']:.3f}  RMSE {o['rmse']:.3f}  R2 {o['r2']:.3f}  cov80 {o['interval_80_coverage']:.2f}")
    print("tier acc", round(o["tier_accuracy"], 3), "within1", round(o["tier_within_one"], 3),
          "High+ recall", round(o["high_or_critical_recall"], 3), "precision", round(o["high_or_critical_precision"], 3))
    for k, v in metrics["baselines"].items():
        print(f"  baseline {k}: MAE {v['mae']:.3f} RMSE {v['rmse']:.3f}")
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
