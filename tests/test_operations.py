"""Invariants of the allocation, routing and simulation layer (no web framework needed)."""
import pytest

from src import operations as op


@pytest.mark.parametrize("stock,crews,surge", [(30, 10, 3.0), (60, 40, 1.0), (100, 120, 1.0), (30, 10, 1.5), (45, 25, 4.0)])
def test_allocation_never_exceeds_limits(peak, make_plan, stock, crews, surge):
    p = make_plan(peak, stock, crews, surge)
    assert sum(r["crews_alloc"] for r in p["wards"]) <= crews
    for r in p["wards"]:
        assert r["saline_alloc"] <= r["saline_req"] and r["kits_alloc"] <= r["kits_req"]
        assert r["deficit"] == any(r[f"{x}_short"] > 0 for x in ("saline", "kits", "crews"))
    for city in {r["city"] for r in p["wards"]}:
        rows = [r for r in p["wards"] if r["city"] == city]
        for res in ("saline", "kits"):
            assert sum(r[f"{res}_alloc"] for r in rows) <= int(stock / 100 * sum(r[f"{res}_req"] for r in rows) + 1e-9)


def test_priority_order_is_a_strict_ranking(peak, make_plan):
    p = make_plan(peak)
    assert [r["rank"] for r in p["wards"]] == list(range(1, len(p["wards"]) + 1))
    pr = [r["priority"] for r in p["wards"]]
    assert pr == sorted(pr, reverse=True)


@pytest.mark.parametrize("surge", [1.0, 1.5, 3.0])
def test_bed_routing_conserves_patients_and_stays_in_city(peak, make_plan, surge):
    p = make_plan(peak, 100, 120, surge)
    city = {r["ward_id"]: r["city"] for r in p["wards"]}
    assert all(city[m["from"]] == city[m["to"]] == m["city"] for m in p["manifest"])
    sent = sum(m["patients"] for m in p["manifest"])
    assert sent == sum(r["received"] for r in p["wards"])
    assert sum(r["overflow"] for r in p["wards"]) == sent + p["unmet_beds"]


def test_more_stock_never_increases_deficit(peak, make_plan):
    short = [make_plan(peak, s, 40)["totals"]["saline"]["shortfall"] for s in (30, 50, 70, 100)]
    assert short == sorted(short, reverse=True)


def test_surge_scales_demand(peak, make_plan):
    assert make_plan(peak, 100, 120, 2.0)["totals"]["saline"]["required"] > make_plan(peak, 100, 120, 1.0)["totals"]["saline"]["required"]


def test_sms_fits_in_160_chars_for_every_ward(peak, make_plan):
    for surge in (1.0, 3.0):
        assert all(len(op.sms(r)) <= 160 for r in make_plan(peak, 30, 10, surge)["wards"])


def test_dispatch_text_is_deterministic(peak, make_plan):
    a, b = make_plan(peak, 30, 10, 3.0), make_plan(peak, 30, 10, 3.0)
    assert [op.whatsapp(r, a["dates"]) for r in a["wards"]] == [op.whatsapp(r, b["dates"]) for r in b["wards"]]


def test_commissioner_brief_escapes_html():
    r = dict(ward_id="<script>x</script>", city="A&B", cases=1, lo=0, hi=1, rank=1, priority=1.0, density=1, wl=.1, san=.1,
             beds_req=1, capacity=4, saline_alloc=1, saline_req=1, kits_alloc=1, kits_req=1, crews_alloc=1, crews_req=1,
             deficit=False, send_to=[], receive_from=[], unmet_beds=0)
    out = op.commissioner_html(r, {})
    assert "<script>x" not in out and "&lt;script&gt;" in out


def test_simulation_totals_match_deployment(peak):
    rows = op.build_wards(peak.wards, peak.forecast_df())
    sim = op.simulate(rows, peak.effects(), auto_crews=12)
    assert len(sim["leaderboard"]) == 60 and sim["totals"]["crews"] <= 12
    assert sim["totals"]["cases_prevented"] == pytest.approx(sum(d["cases_prevented"] for d in sim["deployment"]), abs=0.05)
    assert all(d["crews"] <= op.K_MAX for d in sim["deployment"])


def test_zero_crews_prevent_nothing(peak):
    rows = op.build_wards(peak.wards, peak.forecast_df())
    assert all(v[0] == 0 for v in (op.prevented_table(rows, peak.effects())[w][0] for w in peak.wards))


def test_manual_assignments_are_clamped(peak):
    rows = op.build_wards(peak.wards, peak.forecast_df())
    w = next(iter(peak.wards))
    sim = op.simulate(rows, peak.effects(), assignments={w: 99, "NOPE": 2})
    assert [d["crews"] for d in sim["deployment"]] == [op.K_MAX]
