"""Chronological training: per horizon h in {2,3,4}: Poisson mean + q10/q90 models."""
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor as HGB

from .features import HORIZONS, build_features, feature_columns, load_panel

SEED = 42
PARAMS = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=40,
              l2_regularization=1.0, early_stopping=False, random_state=SEED)
SPECS = {"mean": dict(loss="poisson"), "q10": dict(loss="quantile", quantile=0.10),
         "q90": dict(loss="quantile", quantile=0.90)}


def make(kind):
    return HGB(**SPECS[kind], **PARAMS)


def ward_stats(df):
    """Per-ward covariates, p90 bed surge, empirical supply ratios (fallback: global ratio)."""
    tot = df[["dengue_cases", "saline_bags_needed", "diagnostic_kits_needed", "hospital_beds_required"]].sum()
    glob = {"saline": float(tot.saline_bags_needed / tot.dengue_cases),
            "kits": float(tot.diagnostic_kits_needed / tot.dengue_cases),
            "beds": float(tot.hospital_beds_required / tot.dengue_cases)}
    out = []
    for w, d in df.groupby("ward_id"):
        c = d["dengue_cases"].sum()
        last = d.iloc[-1]

        def ratio(col, k):
            return float(d[col].sum() / c) if c > 0 else glob[k]

        out.append(dict(ward_id=w, city=last["city"], density=float(last["population_density_sqkm"]),
                        wl=float(last["water_logging_risk_index"]), san=float(last["sanitation_score"]),
                        p90_beds=float(np.percentile(d["hospital_beds_required"], 90)),
                        mean_cases=float(d["dengue_cases"].mean()),
                        sal_r=ratio("saline_bags_needed", "saline"), kit_r=ratio("diagnostic_kits_needed", "kits"),
                        bed_r=ratio("hospital_beds_required", "beds")))
    return out, glob


def metrics(y, mean, lo, hi, persist):
    return dict(mae=float(np.mean(np.abs(y - mean))), rmse=float(np.sqrt(np.mean((y - mean) ** 2))),
                mae_persistence=float(np.mean(np.abs(y - persist))),
                coverage_q10_q90=float(np.mean((y >= lo) & (y <= hi))),
                mean_width=float(np.mean(hi - lo)), n=int(len(y)))


def main(xlsx="data/bangladesh_dengue_large_dataset_onsite.xlsx", out="artifacts"):
    out = Path(out)
    (out / "models").mkdir(parents=True, exist_ok=True)
    f = build_features(load_panel(xlsx))
    df = load_panel(xlsx)
    cols = feature_columns(f)
    last = f["date"].max()
    hold_start = last - pd.Timedelta(weeks=51)  # final 52 weeks held out
    report = {}
    for h in HORIZONS:
        d = f[f[f"y{h}"].notna() & f[cols].notna().all(axis=1)]
        tr = d[d["date"] + pd.Timedelta(weeks=h) < hold_start]  # no target leakage into holdout
        te = d[d["date"] >= hold_start]
        ms = {k: make(k).fit(tr[cols], tr[f"y{h}"]) for k in SPECS}
        pr = {k: ms[k].predict(te[cols]) for k in SPECS}
        (out / "models_holdout").mkdir(exist_ok=True)
        for k in SPECS:  # out-of-sample models (trained before holdout) power the peak-season replay
            joblib.dump(ms[k], out / "models_holdout" / f"h{h}_{k}.joblib")
        lo, hi = np.minimum(pr["q10"], pr["mean"]), np.maximum(pr["q90"], pr["mean"])
        report[f"h{h}"] = metrics(te[f"y{h}"].to_numpy(), pr["mean"], lo, hi, te["cases_lag0"].to_numpy())
        report[f"h{h}"].update(train_rows=int(len(tr)), holdout_start=str(hold_start.date()))
        print(f"h={h}", {k: round(v, 3) if isinstance(v, float) else v for k, v in report[f"h{h}"].items()})
        for k in SPECS:  # refit on all labelled rows for serving
            joblib.dump(make(k).fit(d[cols], d[f"y{h}"]), out / "models" / f"h{h}_{k}.joblib")
    latest = f[f["date"] == last].set_index("ward_id").sort_index()
    joblib.dump(latest[cols + ["city"]], out / "latest.joblib")
    ho = f[(f["date"] >= hold_start) & f["y4"].notna()]
    peak = ho.groupby("date")["y3"].sum().idxmax()  # holdout week whose t+3 actual cases are highest
    joblib.dump(ho[ho["date"] == peak].set_index("ward_id").sort_index()[cols + ["city"]], out / "latest_peak.joblib")
    wards, glob = ward_stats(df)
    meta = dict(as_of=str(last.date()), peak_origin=str(peak.date()), features=cols, horizons=list(HORIZONS), metrics=report,
                global_ratios=glob, wards=wards, rows=int(len(df)), seed=SEED)
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    from .inference import Engine
    for sc in ("live", "peak"):
        Engine.precompute(out, sc)
    print("artifacts written to", out, "| peak replay origin:", peak.date())


if __name__ == "__main__":
    main(*sys.argv[1:])
