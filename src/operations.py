"""Operations layer: demand conversion, scarcity allocation, intra-city bed routing,
vector-control counterfactuals, and deterministic dispatch rendering. Pure functions; no I/O."""
import html
import math

K_MAX = 3
WL_PER_CREW, WL_CAP, SAN_PER_CREW = 0.22, 0.65, 0.12
WEIGHTS = (0.65, 0.90, 1.00)  # vector lifecycle weights for t+2, t+3, t+4
BED_HEADROOM, MIN_CAP, CREW_DIVISOR = 1.15, 4, 8
DEFICIT = "CRITICAL DEFICIT"


def rnd(x):
    return int(math.floor(x + 0.5))


def ceil(x):
    return int(math.ceil(x - 1e-9))


def _ward_num(wid):
    return int("".join(ch for ch in wid if ch.isdigit()) or 0)


def intervene(wl, san, k):
    """Environmental perturbation for k crews (scalar or pandas Series)."""
    import numpy as np
    return wl * (1 - min(WL_CAP, WL_PER_CREW * k)), np.minimum(1.0, san + SAN_PER_CREW * k)


def fallback_factor(wl, san, wl2, san2):
    """Deterministic epidemiological fallback: ratio of risk multipliers after/before intervention."""
    return ((1 + wl2) / (1 + wl)) * ((2 - san2) / (2 - san))


# ---------------------------------------------------------------- demand
def build_wards(wards, fc, basis="expected", surge=1.0):
    """Per-ward predicted cases, resource requirements, bed capacity, priority score."""
    max_d = max(w["density"] for w in wards.values())
    rows = []
    for wid in sorted(wards):
        w, f = wards[wid], fc.loc[wid]
        pred = float(f[basis]) * surge
        cases = rnd(pred)
        rows.append(dict(
            ward_id=wid, city=w["city"], pred=pred, cases=cases,
            lo=float(sum(f[c] for c in f.index if c.endswith("_lo")) / 3) * surge,
            hi=float(sum(f[c] for c in f.index if c.endswith("_hi")) / 3) * surge,
            density=w["density"], wl=w["wl"], san=w["san"],
            priority=pred * math.sqrt(w["density"] / max_d) * (1 + w["wl"]) * (2 - w["san"]),
            saline_req=ceil(w["sal_r"] * cases), kits_req=ceil(w["kit_r"] * cases),
            crews_req=ceil(cases / CREW_DIVISOR), beds_req=ceil(w["bed_r"] * cases),
            capacity=max(MIN_CAP, rnd(w["p90_beds"] * BED_HEADROOM)),
            sal_r=w["sal_r"], bed_r=w["bed_r"]))
    return rows


# ---------------------------------------------------------- allocation
def allocate(rows, stock_pct, crews):
    """Priority-sequential allocation. Stock pools are regional (per city); crews are one global pool."""
    f = stock_pct / 100.0
    pools = {}
    for r in rows:
        p = pools.setdefault(r["city"], {"saline": 0, "kits": 0})
        p["saline"] += r["saline_req"]
        p["kits"] += r["kits_req"]
    for p in pools.values():
        p["saline"], p["kits"] = int(math.floor(f * p["saline"] + 1e-9)), int(math.floor(f * p["kits"] + 1e-9))
    left = crews
    ordered = sorted(rows, key=lambda r: (-r["priority"], r["ward_id"]))
    for rank, r in enumerate(ordered, 1):
        pool = pools[r["city"]]
        r["rank"] = rank
        for res in ("saline", "kits"):
            a = min(r[f"{res}_req"], pool[res])
            pool[res] -= a
            r[f"{res}_alloc"] = a
        r["crews_alloc"] = min(r["crews_req"], left)
        left -= r["crews_alloc"]
        fl = []
        for res in ("saline", "kits", "crews"):
            r[f"{res}_short"] = r[f"{res}_req"] - r[f"{res}_alloc"]
            if r[f"{res}_req"] > 0:
                fl.append(r[f"{res}_alloc"] / r[f"{res}_req"])
        r["fulfillment_pct"] = round(100 * min(fl), 1) if fl else 100.0
        r["deficit"] = any(r[f"{x}_short"] > 0 for x in ("saline", "kits", "crews"))
    return ordered


# ------------------------------------------------------------- routing
def route_beds(rows):
    """Greedy donor->receiver transfers strictly inside each city corporation (nearest spare capacity tie-break)."""
    manifest, cities, info = [], [], {}
    for city in sorted({r["city"] for r in rows}):
        cw = [r for r in rows if r["city"] == city]
        spare = {r["ward_id"]: max(0, r["capacity"] - r["beds_req"]) for r in cw}
        over = {r["ward_id"]: max(0, r["beds_req"] - r["capacity"]) for r in cw}
        sent = {w: 0 for w in spare}
        recv = {w: 0 for w in spare}
        pair = {}
        for d in sorted((w for w in over if over[w] > 0), key=lambda w: (-over[w], w)):
            need = over[d]
            while need > 0:
                cand = [w for w in spare if spare[w] > 0 and w != d]
                if not cand:
                    break
                t = min(cand, key=lambda w: (-spare[w], abs(_ward_num(w) - _ward_num(d)), w))
                n = min(need, spare[t])
                spare[t] -= n
                need -= n
                sent[d] += n
                recv[t] += n
                pair[(d, t)] = pair.get((d, t), 0) + n
            over[d] = need
        manifest += [{"from": a, "to": b, "city": city, "patients": n} for (a, b), n in sorted(pair.items())]
        dem, cap = sum(r["beds_req"] for r in cw), sum(r["capacity"] for r in cw)
        cities.append(dict(city=city, wards=len(cw), demand=dem, capacity=cap,
                           utilization_pct=round(100 * dem / cap, 1) if cap else 0.0,
                           routed=sum(sent.values()), unmet=sum(over.values())))
        for r in cw:
            w = r["ward_id"]
            info[w] = dict(overflow=max(0, r["beds_req"] - r["capacity"]), sent=sent[w], received=recv[w],
                           unmet_beds=over[w], spare=max(0, r["capacity"] - r["beds_req"]))
    return manifest, cities, info


def plan(wards, fc, stock_pct, crews, basis="expected", surge=1.0, dates=None):
    rows = build_wards(wards, fc, basis, surge)
    ordered = allocate(rows, stock_pct, crews)
    manifest, cities, info = route_beds(rows)
    for r in ordered:
        r.update(info[r["ward_id"]])
        r["send_to"] = [(m["to"], m["patients"]) for m in manifest if m["from"] == r["ward_id"]]
        r["receive_from"] = [(m["from"], m["patients"]) for m in manifest if m["to"] == r["ward_id"]]
    tot = {res: {"required": sum(r[f"{res}_req"] for r in rows), "allocated": sum(r[f"{res}_alloc"] for r in rows)}
           for res in ("saline", "kits", "crews")}
    for t in tot.values():
        t["shortfall"] = t["required"] - t["allocated"]
    return dict(params=dict(stock_pct=stock_pct, crews=crews, basis=basis, surge=surge), dates=dates or {},
                wards=ordered, manifest=manifest, cities=cities, totals=tot,
                deficit_wards=sum(r["deficit"] for r in rows), unmet_beds=sum(c["unmet"] for c in cities))


# ------------------------------------------------------------ simulator
def prevented_table(rows, fx, surge=1.0):
    """{ward: {k: (cases_prevented, beds_freed, saline_saved, src)}} using lifecycle weights."""
    out = {}
    for r in rows:
        d, s = fx[r["ward_id"]]["delta"], fx[r["ward_id"]]["src"]
        out[r["ward_id"]] = {}
        for k in range(K_MAX + 1):
            p = sum(w * x for w, x in zip(WEIGHTS, d[k])) * surge
            kinds = set(s[k])
            src = "ml" if kinds == {"ml"} else ("fallback" if kinds == {"fallback"} else "mixed")
            out[r["ward_id"]][k] = (p, p * r["bed_r"], p * r["sal_r"], src)
    return out


def simulate(rows, fx, assignments=None, auto_crews=None, surge=1.0):
    pt = prevented_table(rows, fx, surge)
    city = {r["ward_id"]: r["city"] for r in rows}
    board = []
    for w, tab in pt.items():
        best = max(range(1, K_MAX + 1), key=lambda k: (tab[k][0] / k, -k))
        p, b, s, src = tab[best]
        board.append(dict(ward_id=w, city=city[w], best_crews=best, cases_prevented=round(p, 2),
                          beds_freed=round(b, 2), saline_saved=round(s, 2), roi=round(p / best, 3), engine=src,
                          prevented_by_crews=[round(tab[k][0], 2) for k in range(K_MAX + 1)]))
    board.sort(key=lambda x: (-x["roi"], x["ward_id"]))
    for i, x in enumerate(board, 1):
        x["rank"] = i
    asg = {w: max(0, min(K_MAX, int(k))) for w, k in (assignments or {}).items() if w in pt}
    if not asg and auto_crews:  # greedy by marginal cases prevented per added crew
        asg = {w: 0 for w in pt}
        for _ in range(int(auto_crews)):
            gains = [(pt[w][asg[w] + 1][0] - pt[w][asg[w]][0], w) for w in pt if asg[w] < K_MAX]
            g, w = min(gains, key=lambda x: (-x[0], x[1]))
            if g <= 0:
                break
            asg[w] += 1
        asg = {w: k for w, k in asg.items() if k > 0}
    dep, tp, tb, ts = [], 0.0, 0.0, 0.0
    for w in sorted(asg):
        k = asg[w]
        if k == 0:
            continue
        p, b, s, src = pt[w][k]
        tp, tb, ts = tp + p, tb + b, ts + s
        dep.append(dict(ward_id=w, city=city[w], crews=k, cases_prevented=round(p, 2), beds_freed=round(b, 2),
                        saline_saved=round(s, 2), roi=round(p / k, 3), engine=src))
    crews = sum(d["crews"] for d in dep)
    dep.sort(key=lambda d: (-d["roi"], d["ward_id"]))
    return dict(leaderboard=board, deployment=dep,
                totals=dict(crews=crews, cases_prevented=round(tp, 2), beds_freed=round(tb, 2),
                            saline_saved=round(ts, 2), roi=round(tp / crews, 3) if crews else 0.0),
                weights=list(WEIGHTS))


# ------------------------------------------------------------- dispatch
def _short(r):
    parts = [f"{n} {r[f'{k}_short']}" for k, n in (("saline", "saline"), ("kits", "kits"), ("crews", "crews"))
             if r[f"{k}_short"] > 0]
    return ", ".join(parts)


def sms(r):
    status = f"{DEFICIT}: {_short(r).replace(', ', ' ')}" if r["deficit"] else "Supply OK"
    route = f"Send {sum(n for _, n in r['send_to'])} pts to {r['send_to'][0][0]}" if r["send_to"] else (
        f"Receive {r['received']} pts" if r["received"] else "")
    head = f"DENGUE {r['ward_id']}: {r['cases']} cases/wk."
    core = f"Saline {r['saline_alloc']}/{r['saline_req']} Kits {r['kits_alloc']}/{r['kits_req']} Crews {r['crews_alloc']}/{r['crews_req']}."
    for cand in (" ".join(x for x in (head, core, status + ".", route) if x),
                 " ".join(x for x in (head, core, status) if x),
                 " ".join((head, core))):
        if len(cand) <= 160:
            return cand
    return (head + " " + core)[:160]


def whatsapp(r, dates):
    d = dates or {}
    win = f"{d.get('2', '')} to {d.get('4', '')}" if d else "t+2 to t+4 weeks"
    util = round(100 * r["beds_req"] / r["capacity"], 1) if r["capacity"] else 0
    L = [f"*DENGUE DISPATCH BRIEF: {r['ward_id']} ({r['city']})*", f"Forecast window: {win}",
         f"Predicted cases/week: *{r['cases']}* (range {r['lo']:.1f} to {r['hi']:.1f})",
         f"Priority rank: {r['rank']} of 60 (score {r['priority']:.2f})", "",
         "*Supplies (allocated / required)*",
         f"- IV saline bags: {r['saline_alloc']} / {r['saline_req']}",
         f"- NS1/IgM kits: {r['kits_alloc']} / {r['kits_req']}",
         f"- Spraying crews: {r['crews_alloc']} / {r['crews_req']}",
         f"- Status: *{DEFICIT}* (short: {_short(r)})" if r["deficit"] else "- Status: supply fully allocated", "",
         "*Hospital beds*", f"- Demand {r['beds_req']} vs capacity {r['capacity']} ({util}% utilization)"]
    L += [f"- ROUTE OUT: send {n} patients to {w}" for w, n in r["send_to"]]
    L += [f"- ROUTE IN: expect {n} patients from {w}" for w, n in r["receive_from"]]
    if r["unmet_beds"]:
        L.append(f"- UNMET: {r['unmet_beds']} patients have no bed in this city; escalate")
    if not (r["send_to"] or r["receive_from"] or r["unmet_beds"]):
        L.append("- No transfers required")
    L += ["", "*Action checklist*", "- [ ] Confirm stock receipt at ward store",
          f"- [ ] Deploy {r['crews_alloc']} spraying crew(s) to high water-logging sites",
          "- [ ] Open NS1/IgM testing desk; log results daily", "- [ ] Brief ward clinics on transfer orders",
          "- [ ] Report status to city control room"]
    return "\n".join(L)


def commissioner_html(r, dates):
    e = html.escape
    d = dates or {}
    util = round(100 * r["beds_req"] / r["capacity"], 1) if r["capacity"] else 0
    banner = (f'<div class="alert">{DEFICIT}: short {e(_short(r))}</div>' if r["deficit"]
              else '<div class="ok">Supplies fully allocated</div>')
    orders = "".join(f"<li>Send <b>{n}</b> patients to <b>{e(w)}</b></li>" for w, n in r["send_to"]) + \
             "".join(f"<li>Expect <b>{n}</b> patients from <b>{e(w)}</b></li>" for w, n in r["receive_from"])
    if r["unmet_beds"]:
        orders += f"<li class='bad'><b>{r['unmet_beds']}</b> patients cannot be placed in {e(r['city'])}: escalate</li>"
    orders = orders or "<li>No transfers required</li>"
    rows = "".join(f"<tr><td>{n}</td><td>{a}</td><td>{q}</td><td>{q - a}</td></tr>" for n, a, q in (
        ("IV saline bags", r["saline_alloc"], r["saline_req"]), ("NS1/IgM kits", r["kits_alloc"], r["kits_req"]),
        ("Spraying crews", r["crews_alloc"], r["crews_req"])))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Commissioner brief {e(r['ward_id'])}</title><style>
body{{font:14px/1.5 Georgia,serif;color:#17231f;max-width:760px;margin:24px auto;padding:0 16px}}
h1{{font-size:22px;margin:0}} h2{{font-size:15px;border-bottom:1px solid #17231f;margin-top:22px}}
table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #9aa8a0;padding:6px 8px;text-align:left}}
.alert{{background:#b42318;color:#fff;padding:8px 12px;font-weight:bold;margin:12px 0}}
.ok{{border:1px solid #0e5a55;color:#0e5a55;padding:8px 12px;margin:12px 0}} .bad{{color:#b42318}}
.sig{{margin-top:36px;display:flex;gap:40px}} .sig div{{flex:1;border-top:1px solid #17231f;padding-top:4px}}
@media print{{body{{margin:0;max-width:none}} .alert{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}}}
</style></head><body>
<h1>Ward Commissioner Brief: {e(r['ward_id'])}</h1>
<div>{e(r['city'])} City Corporation. Forecast window {e(d.get('2', 't+2'))} to {e(d.get('4', 't+4'))}</div>
{banner}
<h2>Ward metrics</h2><table>
<tr><th>Predicted cases per week</th><td>{r['cases']} (range {r['lo']:.1f} to {r['hi']:.1f})</td></tr>
<tr><th>Priority rank</th><td>{r['rank']} of 60 (score {r['priority']:.2f})</td></tr>
<tr><th>Density / water-logging / sanitation</th><td>{r['density']:.0f} per sq km / {r['wl']:.2f} / {r['san']:.2f}</td></tr>
<tr><th>Hospital beds</th><td>demand {r['beds_req']}, capacity {r['capacity']} ({util}% utilization)</td></tr></table>
<h2>Supply allocation</h2><table><tr><th>Resource</th><th>Allocated</th><th>Required</th><th>Shortfall</th></tr>{rows}</table>
<h2>Routing orders</h2><ul>{orders}</ul>
<h2>Actions</h2><ol><li>Confirm stock receipt.</li><li>Deploy {r['crews_alloc']} spraying crew(s) to high water-logging sites.</li>
<li>Run NS1/IgM testing and log results daily.</li><li>Report to the city control room.</li></ol>
<div class="sig"><div>Ward commissioner</div><div>Date</div></div></body></html>"""