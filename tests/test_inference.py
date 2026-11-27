import json

import numpy as np
import pytest

from src.inference import Engine


def test_forecast_shape_and_interval_order(peak):
    fc = peak.forecast_df()
    assert len(fc) == 60 and np.isfinite(fc.to_numpy()).all()
    for h in peak.hz:
        assert (fc[f"h{h}_lo"] <= fc[f"h{h}_mean"] + 1e-9).all() and (fc[f"h{h}_mean"] <= fc[f"h{h}_hi"] + 1e-9).all()
        assert (fc[f"h{h}_mean"] >= 0).all()


def test_peak_replay_is_busier_than_off_season(peak, live):
    assert peak.forecast_df()["expected"].sum() > 10 * live.forecast_df()["expected"].sum()


def test_precomputed_fallback_matches_ml(tmp_path, peak):
    """With model files removed, the engine must serve the same forecasts from the CSV/JSON artifacts."""
    import shutil
    from pathlib import Path
    art = tmp_path / "art"
    shutil.copytree(Path(peak.art), art, ignore=shutil.ignore_patterns("models", "models_holdout", "latest*.joblib"))
    fb = Engine(art, "peak")
    assert fb.mode == "precomputed"
    assert np.allclose(fb.forecast_df().to_numpy(), peak.forecast_df().to_numpy(), atol=1e-6)
    fx = fb.effects()
    assert set(fx) == set(peak.wards) and all(v["delta"][0] == [0, 0, 0] or sum(v["delta"][0]) == 0 for v in fx.values())


def test_effects_monotone_in_fallback_path(peak):
    for v in peak.effects().values():
        tot = [sum(row) for row in v["delta"]]
        assert tot[0] == 0 and all(t >= -1e-9 for t in tot)


def test_metrics_beat_persistence(peak):
    m = json.loads((peak.art / "meta.json").read_text())["metrics"]
    for h in ("h2", "h3", "h4"):
        assert m[h]["mae"] < m[h]["mae_persistence"]
