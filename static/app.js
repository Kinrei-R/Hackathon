"use strict";
const $ = (s, r = document) => r.querySelector(s);
const h = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) e.append(c instanceof Node ? c : String(c));
  return e;
};
const DEFAULTS = { scenario: "peak", city: "All", basis: "expected", stock: 60, crews: 40, surge: 1, colorBy: "rank" };
const S = { ...DEFAULTS, ward: null, plan: null, sim: null, fc: {}, asg: {}, tab: "sms", texts: {}, ovfTab: "sms", ovfTexts: {}, status: null };
const q = () => `scenario=${S.scenario}&basis=${S.basis}&stock=${S.stock}&crews=${S.crews}&surge=${S.surge}`;
const f1 = (x) => Number(x).toFixed(1), f2 = (x) => Number(x).toFixed(2);
const pct = (a, r) => (r ? Math.round((100 * a) / r) : 100);

/* ---- saved settings: a convenience only, the page works without storage */
const KEY = "dengue-ews:controls";
const saveControls = () => { try { localStorage.setItem(KEY, JSON.stringify(Object.fromEntries(Object.keys(DEFAULTS).map((k) => [k, S[k]])))); } catch (e) { /* storage unavailable */ } };
const loadControls = () => { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { return {}; } };

/* ---- network, errors, stale-response protection */
async function api(path, opt) {
  const r = await fetch(path, opt);
  if (!r.ok) throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
  return r.json();
}
let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 7000);
}
const safe = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(`Could not update: ${e.message}`); } };
let busy = 0, seq = 0;
const track = async (fn) => {
  busy++; $("#progress").classList.add("on");
  try { return await fn(); } finally { if (--busy === 0) $("#progress").classList.remove("on"); }
};
let timer;
const later = (fn) => { clearTimeout(timer); timer = setTimeout(safe(fn), 150); };

const rows = () => S.plan.wards.filter((r) => S.city === "All" || r.city === S.city);
const rankBin = (r) => (r.priority <= 0 ? 0 : r.rank <= 6 ? 5 : r.rank <= 15 ? 4 : r.rank <= 27 ? 3 : r.rank <= 40 ? 2 : r.rank <= 52 ? 1 : 0);
const casesBin = (r) => (r.pred < 0.2 ? 0 : r.pred < 1 ? 1 : r.pred < 4 ? 2 : r.pred < 8 ? 3 : r.pred < 12 ? 4 : 5);
const bin = (r) => (S.colorBy === "cases" ? casesBin(r) : rankBin(r));

function table(el, heads, body, onRow) {
  el.replaceChildren(h("thead", {}, h("tr", {}, heads.map(([t, n]) => h("th", { class: n ? "n" : "", scope: "col" }, t)))));
  const tb = h("tbody");
  for (const { cells, cls, id } of body) {
    const tr = h("tr", { class: cls || "", tabindex: onRow ? "0" : null });
    cells.forEach((c, i) => tr.append(h("td", { class: heads[i][1] ? "n" : "" }, c)));
    if (onRow) { tr.addEventListener("click", () => onRow(id)); tr.addEventListener("keydown", (e) => { if (e.key === "Enter") onRow(id); }); }
    tb.append(tr);
  }
  el.append(tb);
}

/* ---------------------------------------------------------------- heatmap */
function renderHeat() {
  const box = $("#heat");
  box.replaceChildren();
  for (const c of S.plan.cities.filter((c) => S.city === "All" || c.city === S.city)) {
    const ws = S.plan.wards.filter((r) => r.city === c.city).sort((a, b) => a.ward_id.localeCompare(b.ward_id));
    const tiles = h("div", { class: "tiles" }, ws.map((r) => h("button", {
      class: `tile t${bin(r)}${r.deficit ? " def" : ""}${r.ward_id === S.ward ? " sel" : ""}`,
      title: `${r.ward_id}: ${f1(r.pred)} cases/wk, priority rank ${r.rank}${r.deficit ? ", CRITICAL DEFICIT" : ""}`,
      "aria-label": `${r.ward_id}, priority rank ${r.rank}, ${f1(r.pred)} cases per week${r.deficit ? ", critical deficit" : ""}`,
      "aria-pressed": String(r.ward_id === S.ward),
      onclick: () => pick(r.ward_id) }, r.ward_id.slice(-2))));
    box.append(h("div", { class: "hrow" }, h("span", {}, c.city, h("small", {}, `${c.wards} wards`)), tiles));
  }
  const byCases = S.colorBy === "cases";
  $("#legLo").textContent = byCases ? "0 cases" : "Lower priority";
  $("#legHi").textContent = byCases ? "12 or more" : "Higher";
  renderKpis();
}

function kpi(label, value, note, cls = "") {
  return h("div", { class: `kpi ${cls}` }, h("span", { class: "kl" }, label), h("b", {}, value), note ? h("small", {}, note) : "");
}

function renderKpis() {
  const t = S.plan.totals, vis = rows();
  const cases = vis.reduce((a, r) => a + r.pred, 0);
  const demand = (k) => `${t[k].allocated} of ${t[k].required}`;
  $("#kpis").replaceChildren(
    kpi("Expected cases per week", f1(cases), S.city === "All" ? "all 60 wards" : S.city),
    kpi("Saline bags filled", `${pct(t.saline.allocated, t.saline.required)}%`, demand("saline")),
    kpi("Test kits filled", `${pct(t.kits.allocated, t.kits.required)}%`, demand("kits")),
    kpi("Spraying crews filled", `${pct(t.crews.allocated, t.crews.required)}%`, demand("crews")),
    kpi("Wards in critical deficit", S.plan.deficit_wards, S.plan.deficit_wards ? "supply short" : "none", S.plan.deficit_wards ? "bad" : "ok"),
    kpi("Unmet bed demand", S.plan.unmet_beds, S.plan.unmet_beds ? "patients with no bed" : "none", S.plan.unmet_beds ? "bad" : "ok"));
}

/* ------------------------------------------------------- ward detail panel */
function chartSvg(f, surge) {
  const hs = ["h2", "h3", "h4"], W = 300, H = 170, L = 30, R = 26, T = 14, B = 30;
  const g = (k) => hs.map((x) => f[`${x}_${k}`] * surge);
  const hi = g("hi"), lo = g("lo"), mean = g("mean");
  const ymax = Math.max(2, Math.ceil(Math.max(...hi) / 2) * 2);
  const x = (i) => L + (i * (W - L - R)) / 2, y = (v) => T + (1 - v / ymax) * (H - T - B);
  const band = [...hi.map((v, i) => `${x(i)},${y(v)}`), ...[2, 1, 0].map((i) => `${x(i)},${y(lo[i])}`)].join(" ");
  const ticks = [0, ymax / 2, ymax].map((v) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 5}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join("");
  const dates = Object.values(S.status.scenarios[S.scenario].targets);
  const xs = hs.map((_, i) => `<text x="${x(i)}" y="${H - 10}" text-anchor="middle">${(dates[i] || "").slice(5)}</text>`).join("");
  const dots = mean.map((v, i) => `<circle class="dot" cx="${x(i)}" cy="${y(v)}" r="3.5"/><text class="val" x="${x(i)}" y="${y(v) - 8}" text-anchor="middle">${f1(v)}</text>`).join("");
  const path = mean.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Expected cases ${mean.map(f1).join(", ")} for weeks 2, 3 and 4">${ticks}<polygon class="band-area" points="${band}"/><path class="line" d="${path}"/>${dots}${xs}</svg>`;
}

async function forecasts() {
  if (!S.fc[S.scenario]) {
    const d = await api(`/api/forecast?scenario=${S.scenario}`);
    S.fc[S.scenario] = Object.fromEntries(d.wards.map((w) => [w.ward_id, w]));
  }
  return S.fc[S.scenario];
}

async function renderDetail() {
  const r = S.plan && S.plan.wards.find((x) => x.ward_id === S.ward), body = $("#detailBody");
  if (!r) { body.replaceChildren(h("p", { class: "sub" }, "Choose a ward on the heatmap.")); return; }
  const fc = (await forecasts())[r.ward_id];
  if (r.ward_id !== S.ward) return;
  const fulfil = h("span", { class: r.deficit ? "bad" : "ok" }, r.deficit ? `${r.fulfillment_pct}% of need met` : "Fully supplied");
  const route = [...r.send_to.map(([w, n]) => `Send ${n} to ${w}`), ...r.receive_from.map(([w, n]) => `Receive ${n} from ${w}`)];
  body.replaceChildren(
    h("p", { class: "dn" }, h("b", {}, r.ward_id), " ", r.city),
    h("div", { class: "chart" }),
    h("p", { class: "cap" }, "Weekly cases for weeks 2 to 4. Line is expected; shaded area is the 10th to 90th percentile."),
    h("dl", { class: "facts" },
      h("div", {}, h("dt", {}, "Priority rank"), h("dd", {}, `${r.rank} of ${S.plan.wards.length}`)),
      h("div", {}, h("dt", {}, "Supply"), h("dd", {}, fulfil)),
      h("div", {}, h("dt", {}, "Beds"), h("dd", {}, `${r.beds_req} needed, ${r.capacity} available`)),
      h("div", {}, h("dt", {}, "Density"), h("dd", {}, `${Math.round(r.density).toLocaleString("en-US")} per sq km`)),
      h("div", {}, h("dt", {}, "Water-logging / sanitation"), h("dd", {}, `${f2(r.wl)} / ${f2(r.san)}`)),
      h("div", {}, h("dt", {}, "Bed routing"), h("dd", {}, route.length ? route.join("; ") : r.unmet_beds ? `${r.unmet_beds} unplaced` : "No transfers"))));
  $(".chart", body).innerHTML = chartSvg(fc, S.surge);
}

/* -------------------------------------------------------------- tables */
const shortText = (r) => [["saline", r.saline_short], ["kits", r.kits_short], ["crews", r.crews_short]].filter((x) => x[1] > 0).map((x) => `${x[0]} ${x[1]}`).join(", ");

function renderAlloc() {
  const ratio = (a, r) => `${a} / ${r}`;
  table($("#alloc"), [["Rank", 1], ["Ward"], ["Cases/wk", 1], ["Priority", 1], ["Saline", 1], ["Kits", 1], ["Crews", 1], ["Status"]],
    rows().map((r) => ({ id: r.ward_id, cls: r.ward_id === S.ward ? "sel" : "",
      cells: [r.rank, r.ward_id, r.cases, f2(r.priority), ratio(r.saline_alloc, r.saline_req), ratio(r.kits_alloc, r.kits_req), ratio(r.crews_alloc, r.crews_req),
        r.deficit ? h("span", { class: "badge" }, `CRITICAL DEFICIT: short ${shortText(r)}`) : h("span", { class: "ok" }, "Fully supplied")] })), pick);
}

function downloadCsv() {
  const cols = ["rank", "ward_id", "city", "cases", "priority", "saline_alloc", "saline_req", "kits_alloc", "kits_req", "crews_alloc", "crews_req", "fulfillment_pct", "deficit", "beds_req", "capacity", "overflow", "unmet_beds"];
  const esc = (v) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.split('"').join('""')}"` : s; };
  const lines = [cols.join(","), ...rows().map((r) => cols.map((c) => esc(c === "priority" ? f2(r[c]) : r[c])).join(","))];
  const url = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "text/csv" }));
  const a = h("a", { href: url, download: `allocation_${S.scenario}_stock${S.stock}_crews${S.crews}_surge${S.surge}.csv` });
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function buildOverflowMessages(m) {
  const fromW = S.plan.wards.find((w) => w.ward_id === m.from) || {};
  const toW = S.plan.wards.find((w) => w.ward_id === m.to) || {};
  const d = S.plan.dates || {};
  const win = d["2"] && d["4"] ? `${d["2"]} to ${d["4"]}` : "Active Forecast Window";

  let sms = `DENGUE OVERFLOW [${m.city}]: ${m.from} beds full. Route ${m.patients} pts to ${m.to} hospital (nearest spare beds). Confirm intake.`;
  if (sms.length > 160) sms = sms.slice(0, 157) + "...";

  const wa = [
    `*HOSPITAL OVERFLOW TRANSFER ORDER — ${m.city.toUpperCase()}*`,
    `Forecast window: ${win} | Surge: ${Number(S.surge).toFixed(1)}x`,
    ``,
    `*Overflowing Facility:* ${m.from} (${fromW.cases ?? "-"} cases/wk, demand ${fromW.beds_req ?? "-"} / cap ${fromW.capacity ?? "-"} beds)`,
    `*Nearest Receiving Hospital:* ${m.to} (demand ${toW.beds_req ?? "-"} / cap ${toW.capacity ?? "-"} beds)`,
    `*Patients Authorized for Transfer:* ${m.patients}`,
    ``,
    `*Action Checklist:*`,
    `- [ ] ${m.from}: Stabilize & dispatch ${m.patients} dengue patients`,
    `- [ ] ${m.to}: Reserve ${m.patients} IV/isolation beds & confirm receipt`,
    `- [ ] Control Room: Update intra-city bed ledger`
  ].join("\n");

  const doc = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Hospital transfer brief ${m.from} to ${m.to}</title><style>
body{font:14px/1.5 Georgia,serif;color:#17231f;max-width:760px;margin:24px auto;padding:0 16px}
h1{font-size:22px;margin:0} h2{font-size:15px;border-bottom:1px solid #17231f;margin-top:22px}
.sub{color:#4f6168;font-size:13px;margin-top:2px}
table{border-collapse:collapse;width:100%;margin-top:10px} td,th{border:1px solid #9aa8a0;padding:6px 8px;text-align:left}
.alert{background:#b42318;color:#fff;padding:8px 12px;font-weight:bold;margin:12px 0}
.sig{margin-top:36px;display:flex;gap:40px} .sig div{flex:1;border-top:1px solid #17231f;padding-top:4px}
@media print{body{margin:0;max-width:none} .alert{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
</style></head><body>
<h1>Intra-City Hospital Overflow Transfer Brief</h1>
<div class="sub">${m.city} City Corporation &bull; Forecast window ${win} &bull; Surge ${Number(S.surge).toFixed(1)}x</div>
<div class="alert">OVERFLOW ROUTING DIRECTIVE: TRANSFER ${m.patients} PATIENTS</div>
<h2>Facility routing details</h2><table>
<tr><th>Source Hospital (Saturated)</th><td><b>${m.from}</b> (Demand: ${fromW.beds_req ?? "-"} / Capacity: ${fromW.capacity ?? "-"} beds)</td></tr>
<tr><th>Nearest Receiving Hospital (Spare Capacity)</th><td><b>${m.to}</b> (Demand: ${toW.beds_req ?? "-"} / Capacity: ${toW.capacity ?? "-"} beds)</td></tr>
<tr><th>Authorized Transfer Volume</th><td><b>${m.patients} patients</b></td></tr>
<tr><th>Jurisdiction Policy</th><td>Strict Intra-City Routing (${m.city} only)</td></tr>
</table>
<h2>Operational directive</h2>
<p><b>${m.from}</b> has exceeded its inpatient dengue bed capacity. Duty officers must stabilize and transfer <b>${m.patients} patients</b> immediately to <b>${m.to}</b>, the nearest facility within ${m.city} with verified spare inpatient beds.</p>
<div class="sig"><div>Sending Medical Officer (${m.from})</div><div>Receiving Registrar (${m.to})</div><div>City Health Commissioner</div></div>
</body></html>`;

  return { sms, wa, doc };
}

function renderOverflowDispatch(selectedIdx = 0) {
  const mList = S.plan.manifest.filter((x) => S.city === "All" || x.city === S.city);
  const statusEl = $("#ovfStatus");
  const bodyEl = $("#ovfBody");
  if (!mList.length) {
    bodyEl.hidden = true;
    statusEl.textContent = S.plan.unmet_beds
      ? "All hospitals in this city are at 100% capacity — no spare receiving hospital available."
      : "No hospital overflow at this surge level. Slide Outbreak surge to 1.5x or higher to trigger nearest-hospital transfer suggestions.";
    return;
  }
  bodyEl.hidden = false;
  statusEl.textContent = `${mList.length} overflow transfer route(s) active. Nearest intra-city receiving hospital selected automatically (click any manifest row to inspect).`;
  const sel = $("#ovfSel");
  sel.replaceChildren(...mList.map((m, idx) => h("option", { value: idx }, `${m.from} → ${m.to} (${m.patients} pts, ${m.city})`)));
  const idx = Math.min(selectedIdx, mList.length - 1);
  sel.value = String(idx);
  S.ovfTexts = buildOverflowMessages(mList[idx]);
  $("#ovfSmsTxt").textContent = S.ovfTexts.sms;
  $("#ovfSmsLen").textContent = `${S.ovfTexts.sms.length} of 160 characters`;
  $("#ovfWaTxt").textContent = S.ovfTexts.wa;
  $("#ovfDocFrame").srcdoc = S.ovfTexts.doc;
}

function renderBeds() {
  const m = S.plan.manifest.filter((x) => S.city === "All" || x.city === S.city);
  if (!m.length) $("#xfer").replaceChildren(h("caption", { class: "sub", style: "padding:10px;text-align:left" }, S.plan.unmet_beds ? "No ward has spare beds to receive transfers." : "No transfers needed at this load. Raise the surge to test overflow."));
  else table($("#xfer"), [["From ward"], ["To ward"], ["City"], ["Patients", 1]], m.map((x, idx) => ({ id: idx, cells: [x.from, x.to, x.city, x.patients] })), (idx) => renderOverflowDispatch(idx));
  table($("#cityTbl"), [["City"], ["Demand", 1], ["Capacity", 1], ["Utilization", 1], ["Routed", 1], ["Unmet", 1]],
    S.plan.cities.filter((c) => S.city === "All" || c.city === S.city).map((c) => ({ cells: [c.city, c.demand, c.capacity, `${f1(c.utilization_pct)}%`, c.routed, c.unmet] })));
  renderOverflowDispatch(0);
}

function renderBoard() {
  const dep = Object.fromEntries((S.sim.deployment || []).map((d) => [d.ward_id, d]));
  const t = S.sim.totals;
  $("#simTotals").replaceChildren(...(t.crews ? [
    h("span", {}, "Crews deployed ", h("b", {}, t.crews)), h("span", {}, "Cases prevented, weeks 2 to 4 ", h("b", {}, f1(t.cases_prevented))),
    h("span", {}, "Beds freed ", h("b", {}, f1(t.beds_freed))), h("span", {}, "Saline saved ", h("b", {}, f1(t.saline_saved))),
    h("span", {}, "ROI ", h("b", {}, `${f2(t.roi)} cases per crew`))] : [h("span", { class: "sub" }, "No crews deployed. Choose crews per ward below, or auto-assign.")]));
  table($("#board"), [["ROI rank", 1], ["Ward"], ["City"], ["Best crews", 1], ["Cases prevented", 1], ["Beds freed", 1], ["Saline saved", 1], ["ROI", 1], ["Engine"], ["Deploy"]],
    S.sim.leaderboard.filter((x) => S.city === "All" || x.city === S.city).map((x) => ({ cls: dep[x.ward_id] ? "dep" : "",
      cells: [x.rank, x.ward_id, x.city, x.best_crews, f2(x.cases_prevented), f2(x.beds_freed), f2(x.saline_saved), f2(x.roi), x.engine,
        h("select", { "aria-label": `Crews for ${x.ward_id}`, onchange: (e) => { S.asg[x.ward_id] = +e.target.value; } },
          [0, 1, 2, 3].map((k) => h("option", { value: k, selected: (S.asg[x.ward_id] || 0) === k }, k)))] })));
}

/* ------------------------------------------------------------- data flow */
async function loadBoard(body) {
  const mine = ++loadBoard.n;
  const sim = await track(() => api("/api/vector-simulate", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario: S.scenario, basis: S.basis, surge: S.surge, assignments: {}, auto_crews: null, ...body }) }));
  if (mine !== loadBoard.n) return;
  S.sim = sim; renderBoard();
}
loadBoard.n = 0;

async function loadDispatch() {
  if (!S.ward) return;
  const mine = ++loadDispatch.n;
  const d = await api(`/api/dispatch/${S.ward}?${q()}`);
  if (mine !== loadDispatch.n) return;
  S.texts = { sms: d.sms, wa: d.whatsapp, doc: d.commissioner_html };
  $("#smsTxt").textContent = d.sms;
  $("#smsLen").textContent = `${d.sms_length} of 160 characters`;
  $("#waTxt").textContent = d.whatsapp;
  $("#docFrame").srcdoc = d.commissioner_html;
}

loadDispatch.n = 0;

const pick = safe(async (id) => { S.ward = id; $("#wardSel").value = id; renderHeat(); renderAlloc(); await Promise.all([renderDetail(), loadDispatch()]); });

async function refresh() {
  const mine = ++seq;
  const plan = await track(() => api(`/api/operations?${q()}`));
  if (mine !== seq) return;
  S.plan = plan;
  const vis = rows();
  if (!vis.find((r) => r.ward_id === S.ward)) S.ward = vis[0].ward_id;
  $("#wardSel").replaceChildren(...vis.slice().sort((a, b) => a.ward_id.localeCompare(b.ward_id)).map((r) => h("option", { value: r.ward_id }, r.ward_id)));
  $("#wardSel").value = S.ward;
  renderHeat(); renderAlloc(); renderBeds();
  await Promise.all([renderDetail(), loadDispatch()]);
}
const reloadAll = async () => { S.asg = {}; await Promise.all([refresh(), loadBoard({})]); };

function syncControls() {
  $("#stock").value = S.stock; $("#stockO").textContent = `${S.stock}%`;
  $("#crews").value = S.crews; $("#crewsO").textContent = S.crews;
  $("#surge").value = S.surge; $("#surgeO").textContent = `${Number(S.surge).toFixed(1)}x`;
  $("#basis").value = S.basis; $("#colorBy").value = S.colorBy;
  document.querySelectorAll("input[name=scenario]").forEach((r) => { r.checked = r.value === S.scenario; });
  const s = S.status.scenarios[S.scenario];
  $("#asof").textContent = `Forecast origin ${s.as_of}. Targets: ${Object.values(s.targets).join(", ")}`;
}

function bindRange(id, key, fmt) {
  const el = $(id);
  el.addEventListener("input", () => {
    S[key] = +el.value; $(id + "O").textContent = fmt(S[key]); saveControls();
    later(async () => { await Promise.all([refresh(), key === "surge" ? loadBoard({}) : null]); });
  });
}

async function runStress() {
  const dlg = $("#stress");
  $("#stressSum").textContent = "Running with all outbound connections blocked..."; $("#stressList").replaceChildren();
  if (!dlg.open) dlg.showModal();
  try {
    const r = await api(`/api/stress-test?scenario=${S.scenario}`);
    const s = r.stress;
    $("#stressSum").textContent = `${r.passed ? "PASS" : "FAIL"}: ${r.checks.filter((c) => c.passed).length} of ${r.checks.length} checks in ${r.elapsed_ms} ms. Worst case: surge ${s.surge}x, stock ${s.stock_pct}%, ${s.crews} crews gives ${s.deficit_wards} wards in CRITICAL DEFICIT and ${s.unmet_beds} unmet bed demand.`;
    $("#stressList").replaceChildren(...r.checks.map((c) => h("li", {}, h("span", { class: c.passed ? "pass" : "fail" }, c.passed ? "PASS" : "FAIL"), h("div", {}, c.check, h("small", {}, c.detail)))));
  } catch (e) { $("#stressSum").textContent = `Stress test failed to run: ${e.message}`; }
}

async function init() {
  S.status = await api("/api/status");
  Object.assign(S, DEFAULTS, loadControls());
  $("#mode").textContent = S.status.mode;
  $("#mode").title = `Forecast engine: ${S.status.engine.peak === "ml" ? "serialized models loaded" : "precomputed forecasts"}`;
  $("#lblPeak").textContent = `Peak-season replay (origin ${S.status.scenarios.peak.as_of}, out-of-sample models)`;
  $("#lblLive").textContent = `Live forecast (origin ${S.status.scenarios.live.as_of})`;
  $("#city").replaceChildren(...["All", ...S.status.cities].map((c) => h("option", { value: c }, c)));
  if (!S.status.cities.includes(S.city)) S.city = "All";
  $("#city").value = S.city;
  syncControls();
  $("#city").addEventListener("change", safe(async (e) => { S.city = e.target.value; saveControls(); await refresh(); await loadBoard({}); }));
  $("#basis").addEventListener("change", safe(async (e) => { S.basis = e.target.value; saveControls(); await reloadAll(); }));
  $("#colorBy").addEventListener("change", (e) => { S.colorBy = e.target.value; saveControls(); renderHeat(); });
  document.querySelectorAll("input[name=scenario]").forEach((r) => r.addEventListener("change", safe(async (e) => { S.scenario = e.target.value; saveControls(); syncControls(); await reloadAll(); })));
  $("#resetBtn").addEventListener("click", safe(async () => { Object.assign(S, DEFAULTS); saveControls(); syncControls(); $("#city").value = "All"; await reloadAll(); }));
  bindRange("#stock", "stock", (v) => `${v}%`);
  bindRange("#crews", "crews", (v) => v);
  bindRange("#surge", "surge", (v) => `${Number(v).toFixed(1)}x`);
  $("#wardSel").addEventListener("change", (e) => pick(e.target.value));
  $("#autoBtn").addEventListener("click", safe(async () => { S.asg = {}; await loadBoard({ auto_crews: +$("#auto").value }); (S.sim.deployment || []).forEach((d) => { S.asg[d.ward_id] = d.crews; }); renderBoard(); }));
  $("#selBtn").addEventListener("click", safe(() => loadBoard({ assignments: Object.fromEntries(Object.entries(S.asg).filter(([, k]) => k > 0)) })));
  $("#clrBtn").addEventListener("click", safe(async () => { S.asg = {}; await loadBoard({}); }));
  $("#csvBtn").addEventListener("click", downloadCsv);
  $("#ovfSel").addEventListener("change", (e) => renderOverflowDispatch(+e.target.value));
  document.querySelectorAll("#ovfTabs button").forEach((b) => b.addEventListener("click", () => {
    S.ovfTab = b.dataset.ovftab;
    document.querySelectorAll("#ovfTabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    ["sms", "wa", "doc"].forEach((t) => { $(`#ovf-pane-${t}`).hidden = t !== S.ovfTab; });
  }));
  $("#ovfCopyBtn").addEventListener("click", async () => {
    const btn = $("#ovfCopyBtn"), text = S.ovfTab === "doc" ? "" : (S.ovfTexts[S.ovfTab] || "");
    if (S.ovfTab === "doc") { toast("Use Print transfer brief to print or save the transfer directive as PDF."); return; }
    try { await navigator.clipboard.writeText(text); btn.textContent = "Copied"; } catch (e) { toast("Copy was blocked by the browser. Select the text and copy it manually."); }
    setTimeout(() => { btn.textContent = "Copy text"; }, 1500);
  });
  $("#ovfPrintBtn").addEventListener("click", () => {
    document.querySelector('#ovfTabs button[data-ovftab="doc"]').click();
    const w = $("#ovfDocFrame").contentWindow; w.focus(); w.print();
  });
  document.querySelectorAll("#dispTabs button").forEach((b) => b.addEventListener("click", () => {
    S.tab = b.dataset.tab;
    document.querySelectorAll("#dispTabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    ["sms", "wa", "doc"].forEach((t) => { $(`#pane-${t}`).hidden = t !== S.tab; });
  }));
  $("#copyBtn").addEventListener("click", async () => {
    const btn = $("#copyBtn"), text = S.tab === "doc" ? "" : (S.texts[S.tab] || "");
    if (S.tab === "doc") { toast("Use Print brief to print or save the commissioner brief as PDF."); return; }
    try { await navigator.clipboard.writeText(text); btn.textContent = "Copied"; } catch (e) { toast("Copy was blocked by the browser. Select the text and copy it manually."); }
    setTimeout(() => { btn.textContent = "Copy text"; }, 1500);
  });
  $("#printBtn").addEventListener("click", () => {
    document.querySelector('#dispTabs button[data-tab="doc"]').click();
    const w = $("#docFrame").contentWindow; w.focus(); w.print();
  });
  $("#stressBtn").addEventListener("click", runStress);
  $("#stressClose").addEventListener("click", () => $("#stress").close());
  $("#stress").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
  await reloadAll();
  if (location.hash === "#stress") runStress();
}
init().catch((e) => { document.body.prepend(h("p", { class: "mode", role: "alert" }, `Engine not reachable: ${e.message}. Start it with: uvicorn app:app --host 127.0.0.1 --port 8000`)); });