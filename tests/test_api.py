"""HTTP-level checks. Skipped automatically when fastapi/httpx are not installed."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

import app as appmod  # noqa: E402

c = TestClient(appmod.app)


def test_pages_and_headers():
    for path in ("/", "/app"):
        r = c.get(path)
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
        assert "default-src 'self'" in r.headers["content-security-policy"]
    assert c.get("/api/health").json()["ok"] is True
    assert c.get("/api/status").headers["cache-control"] == "no-store"


def test_validation_rejects_out_of_range():
    assert c.get("/api/operations?stock=5").status_code == 422
    assert c.get("/api/operations?surge=9").status_code == 422
    assert c.get("/api/dispatch/NOPE").status_code == 404
    assert c.post("/api/vector-simulate", json={"assignments": {"NOPE": 1}}).status_code == 400


def test_stress_test_passes():
    r = c.get("/api/stress-test").json()
    assert r["passed"], [x for x in r["checks"] if not x["passed"]]
    assert len(r["checks"]) == 9
