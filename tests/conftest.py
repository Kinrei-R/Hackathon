import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")


@pytest.fixture(scope="session")
def peak():
    from src.inference import Engine
    return Engine(ROOT / "artifacts", "peak")


@pytest.fixture(scope="session")
def live():
    from src.inference import Engine
    return Engine(ROOT / "artifacts", "live")


@pytest.fixture(scope="session")
def make_plan():
    from src import operations as op

    def _plan(e, stock=60, crews=40, surge=1.0, basis="expected"):
        return op.plan(e.wards, e.forecast_df(), stock, crews, basis, surge,
                       {str(h): d for h, d in e.target_dates().items()})
    return _plan
