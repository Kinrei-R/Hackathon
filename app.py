"""FastAPI app: forecasts, scarcity allocation, intra-city bed routing, vector simulation,
dispatch briefs, and the offline kill-switch stress test. Runs fully offline."""
import hashlib
import json
import re
import socket
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src import operations as op
from src.inference import Engine
from src.water_allocation import allocate_safe_water

ROOT = Path(__file__).parent
MODE = "MODE: 100% OFFLINE DETERMINISTIC ENGINE"
TEXT_ASSETS = {".html", ".css", ".js", ".svg", ".json", ".txt"}
SCEN = "^(live|peak)$"
BASIS = "^(expected|upper)$"
# Everything is served from this origin: no CDNs, fonts, or remote frames are ever needed.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'")
app = FastAPI(title="dengue-ews: Urban Vector-Borne Outbreak Decision & Resource Dispatch Engine")
app.add_middleware(GZipMiddleware, minimum_size=1024)
_engines, _lock, _eng_lock = {}, threading.Lock(), threading.Lock()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def eng(scenario="peak"):
    with _eng_lock:  # two first requests must not both load the model files
        if scenario not in _engines:
            _engines[scenario] = Engine(ROOT / "artifacts", scenario)
        return _engines[scenario]


def dates_of(e):
    return {str(h): d for h, d in e.target_dates().items()}


def make_plan(scenario, stock, crews, basis, surge):
    e = eng(scenario)
    return e, op.plan(e.wards, e.forecast_df(), stock, crews, basis, surge, dates_of(e))


# ------------------------------------------------------------------ API
@app.get("/api/health")
def health():
    return dict(ok=True, mode=MODE, engine={s: eng(s).mode for s in ("live", "peak")})


@app.get("/api/status")
def status():
    meta = eng("live").meta
    return dict(mode=MODE, engine={s: eng(s).mode for s in ("live", "peak")}, wards=len(meta["wards"]),
                cities=sorted({w["city"] for w in meta["wards"]}), training_rows=meta["rows"], metrics=meta["metrics"],
                scenarios={s: dict(as_of=eng(s).as_of, targets=dates_of(eng(s))) for s in ("live", "peak")},
                weights=list(op.WEIGHTS))


@app.get("/api/forecast")
def forecast(scenario: str = Query("peak", pattern=SCEN), city: str | None = None):
    e = eng(scenario)
    fc, out = e.forecast_df(), []
    for w in e.ward_ids:
        if city and e.wards[w]["city"] != city:
            continue
        out.append(dict(ward_id=w, city=e.wards[w]["city"], **{c: round(float(fc.loc[w, c]), 3) for c in fc.columns}))
    return dict(scenario=scenario, as_of=e.as_of, targets=dates_of(e), wards=out)


@app.get("/api/operations")
def operations(scenario: str = Query("peak", pattern=SCEN), stock: int = Query(60, ge=30, le=100),
               crews: int = Query(40, ge=10, le=120), basis: str = Query("expected", pattern=BASIS),
               surge: float = Query(1.0, ge=1.0, le=4.0)):
    return make_plan(scenario, stock, crews, basis, surge)[1]


@app.get("/api/routing")
def routing(scenario: str = Query("peak", pattern=SCEN), basis: str = Query("expected", pattern=BASIS),
            surge: float = Query(1.0, ge=1.0, le=4.0)):
    p = make_plan(scenario, 100, 120, basis, surge)[1]
    return dict(manifest=p["manifest"], cities=p["cities"], unmet_beds=p["unmet_beds"], params=p["params"])


class SimReq(BaseModel):
    scenario: str = Field("peak", pattern=SCEN)
    basis: str = Field("expected", pattern=BASIS)
    surge: float = Field(1.0, ge=1.0, le=4.0)
    assignments: dict[str, int] = {}
    auto_crews: int | None = Field(None, ge=0, le=180)


@app.post("/api/vector-simulate")
def vector_simulate(req: SimReq):
    e = eng(req.scenario)
    bad = [w for w in req.assignments if w not in e.wards]
    if bad:
        raise HTTPException(400, f"Unknown ward_id: {', '.join(bad)}")
    rows = op.build_wards(e.wards, e.forecast_df(), req.basis, req.surge)
    out = op.simulate(rows, e.effects(), req.assignments, req.auto_crews, req.surge)
    out["dates"] = dates_of(e)
    return out


def ward_row(scenario, ward_id, stock, crews, basis, surge):
    e, p = make_plan(scenario, stock, crews, basis, surge)
    row = next((r for r in p["wards"] if r["ward_id"] == ward_id), None)
    if row is None:
        raise HTTPException(404, f"Unknown ward_id: {ward_id}")
    return row, p["dates"]


@app.get("/api/dispatch/{ward_id}")
def dispatch(ward_id: str, scenario: str = Query("peak", pattern=SCEN), stock: int = Query(60, ge=30, le=100),
             crews: int = Query(40, ge=10, le=120), basis: str = Query("expected", pattern=BASIS),
             surge: float = Query(1.0, ge=1.0, le=4.0)):
    r, d = ward_row(scenario, ward_id, stock, crews, basis, surge)
    s = op.sms(r)
    return dict(ward_id=ward_id, city=r["city"], rank=r["rank"], deficit=r["deficit"], sms=s, sms_length=len(s),
                whatsapp=op.whatsapp(r, d), commissioner_html=op.commissioner_html(r, d))


@app.get("/api/dispatch/{ward_id}/brief", response_class=HTMLResponse)
def brief(ward_id: str, scenario: str = Query("peak", pattern=SCEN), stock: int = Query(60, ge=30, le=100),
          crews: int = Query(40, ge=10, le=120), basis: str = Query("expected", pattern=BASIS),
          surge: float = Query(1.0, ge=1.0, le=4.0)):
    r, d = ward_row(scenario, ward_id, stock, crews, basis, surge)
    return op.commissioner_html(r, d)


# ----------------------------------------------- offline kill-switch + stress
class NetworkGuard:
    """Blocks every non-loopback socket connection and DNS lookup while active; records attempts."""
    LOCAL = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}

    def __enter__(self):
        self.attempts = []
        self._c, self._ex, self._gai = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
        guard = self

        def check(addr):
            host = addr[0] if isinstance(addr, tuple) else None
            if host is not None and host not in guard.LOCAL:
                guard.attempts.append(str(host))
                raise OSError(f"offline kill-switch: blocked outbound connection to {host}")

        def connect(s, addr):
            check(addr)
            return guard._c(s, addr)

        def connect_ex(s, addr):
            check(addr)
            return guard._ex(s, addr)

        def gai(host, *a, **k):
            if host not in guard.LOCAL:
                guard.attempts.append(str(host))
                raise OSError(f"offline kill-switch: blocked DNS lookup for {host}")
            return guard._gai(host, *a, **k)

        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, gai
        return self

    def __exit__(self, *exc):
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = self._c, self._ex, self._gai

    def probe(self, host="8.8.8.8", port=53):
        n = len(self.attempts)
        try:
            socket.create_connection((host, port), timeout=1).close()
            return False
        except OSError:
            return len(self.attempts) == n + 1  # blocked by the guard itself


def pipeline(scenario, stock, crews, surge):
    e, p = make_plan(scenario, stock, crews, "expected", surge)
    rows = op.build_wards(e.wards, e.forecast_df(), "expected", surge)
    sim = op.simulate(rows, e.effects(), auto_crews=30, surge=surge)
    disp = {r["ward_id"]: (op.sms(r), op.whatsapp(r, p["dates"]), op.commissioner_html(r, p["dates"])) for r in p["wards"]}
    return e, p, sim, disp


def digest(*objs):
    return hashlib.sha256(json.dumps(objs, sort_keys=True, default=float).encode()).hexdigest()[:16]


@app.get("/api/stress-test")
def stress_test(scenario: str = Query("peak", pattern=SCEN), surge: float = Query(3.0, ge=1.0, le=4.0)):
    stock, crews = 30, 10  # worst-case scarcity
    checks, t0 = [], time.perf_counter()

    def chk(name, ok, detail=""):
        checks.append(dict(check=name, passed=bool(ok), detail=detail))

    with _lock:
        ext = []
        scanned = [f for f in sorted((ROOT / "static").glob("*")) if f.suffix in TEXT_ASSETS]
        for f in scanned:
            for m in re.findall(r"""(?:https?:)?//[^\s"'<>)]+""", f.read_text(encoding="utf-8", errors="ignore")):
                if not re.match(r"(?:https?:)?//(127\.0\.0\.1|localhost)", m):
                    ext.append(f"{f.name}: {m[:60]}")
        chk("static assets contain no external URLs or CDNs", not ext, "; ".join(ext[:3]) or f"{len(scanned)} local files scanned")
        with NetworkGuard() as g:
            e, p, sim, disp = pipeline(scenario, stock, crews, surge)
            _, p2, sim2, disp2 = pipeline(scenario, stock, crews, surge)
            attempts = list(g.attempts)
            blocked = g.probe()
        chk("full pipeline ran with every outbound connection blocked", not attempts,
            f"{len(attempts)} outbound attempts by the engine")
        chk("kill-switch blocks a real outbound probe (8.8.8.8:53)", blocked)
        chk("repeat run is byte-identical (deterministic)", digest(p, sim, disp) == digest(p2, sim2, disp2),
            f"sha256/16 {digest(p, sim, disp)}")
        pm = make_plan(scenario, stock, crews, "expected", 1.5)[1]  # mixed load: donors and receivers coexist
        manifests = p["manifest"] + pm["manifest"]
        cross = [m for m in manifests if e.wards[m["from"]]["city"] != e.wards[m["to"]]["city"]]
        chk("no cross-city bed transfers", not cross, f"{len(manifests)} transfers checked across surge {surge}x and 1.5x")
        ok_b, det = True, []
        for q in (p, pm):
            sent, recv = sum(m["patients"] for m in q["manifest"]), sum(r["received"] for r in q["wards"])
            over = sum(r["overflow"] for r in q["wards"])
            ok_b &= sent == recv and over == sent + q["unmet_beds"]
            det.append(f"overflow {over} = routed {sent} + unmet {q['unmet_beds']}")
        chk("bed conservation: sent = received, overflow = routed + unmet", ok_b, "; ".join(det))
        cities = {w["city"] for w in e.meta["wards"]}
        pools_ok = (all(r["saline_alloc"] <= r["saline_req"] and r["kits_alloc"] <= r["kits_req"] for r in p["wards"])
                    and sum(r["crews_alloc"] for r in p["wards"]) <= crews
                    and all(sum(r[f"{x}_alloc"] for r in p["wards"] if r["city"] == c)
                            <= int(stock / 100 * sum(r[f"{x}_req"] for r in p["wards"] if r["city"] == c) + 1e-9)
                            for c in cities for x in ("saline", "kits")))
        chk("allocations never exceed demand, regional stock, or crew limit", pools_ok,
            f"stock {stock}%, crews {crews}")
        chk("all 60 SMS alerts are <= 160 characters", len(disp) == 60 and max(len(v[0]) for v in disp.values()) <= 160,
            f"longest {max(len(v[0]) for v in disp.values())}")
        chk("counterfactual simulator returned all 60 wards ranked by ROI", len(sim["leaderboard"]) == 60)
    return dict(mode=MODE, passed=all(c["passed"] for c in checks), scenario=scenario,
                stress=dict(surge=surge, stock_pct=stock, crews=crews, deficit_wards=p["deficit_wards"],
                            unmet_beds=p["unmet_beds"], totals=p["totals"], cities=p["cities"]),
                elapsed_ms=round(1000 * (time.perf_counter() - t0)), checks=checks)


# ---------------------------------------------------------------- static
@app.get("/")
def landing():
    return FileResponse(ROOT / "static" / "landing.html")


@app.get("/app")
def command_center():
    return FileResponse(ROOT / "static" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
