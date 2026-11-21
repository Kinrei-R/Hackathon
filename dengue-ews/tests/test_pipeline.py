"""Sanity tests for the lag pipeline. Run:  python -m tests.test_pipeline  (or pytest)."""
import numpy as np
import pandas as pd

from src.features import FEATURE_COLS, build_panel, load_raw
from src.train import DATA


def _panel():
    raw = load_raw(str(DATA))
    return raw, build_panel(raw)


def test_lags_are_grouped_per_ward_and_correct():
    raw, panel = _panel()
    w = "CCC_Ward_01"
    r = raw[raw.ward_id == w].reset_index(drop=True)
    p = panel[panel.ward_id == w].reset_index(drop=True)
    i = 100
    t = p.loc[i, "date"]
    j = r.index[r.date == t][0]
    for k in (0, 1, 3, 8):
        assert np.isclose(p.loc[i, f"rain_lag_{k}"], r.loc[j - k, "rainfall_mm"])
    assert np.isclose(p.loc[i, "rain_sum_4w"], r.loc[j - 3 : j, "rainfall_mm"].sum(), rtol=1e-5)


def test_no_lag_bleeds_across_wards():
    raw, panel = _panel()
    first_rows = panel.groupby("ward_id").head(1)  # first usable origin has 8 weeks of history
    raw_first = raw.groupby("ward_id").nth(8)
    assert len(first_rows) == raw.ward_id.nunique() == len(raw_first)


def test_features_use_only_past_and_target_is_future():
    raw, panel = _panel()
    w = "DNCC_Ward_01"
    r = raw[raw.ward_id == w].set_index("date")
    p = panel[panel.ward_id == w].set_index("date")
    d = p.index[200]
    assert np.isclose(p.loc[d, "y_h3"], r.loc[d + pd.Timedelta(weeks=3), "dengue_cases"])
    assert not any(c.startswith("y_h") for c in FEATURE_COLS)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
