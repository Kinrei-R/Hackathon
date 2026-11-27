"use strict";
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) e.append(c instanceof Node ? c : String(c));
  return e;
};
const api = async (path) => {
  const r = await fetch(path);
  if (!r.ok) throw new Error((await r.text()).slice(0, 160));
  return r.json();
};
const num = (x) => Number(x).toLocaleString("en-US");
const f1 = (x) => Number(x).toFixed(1);
const NAMES = { DNCC: "Dhaka North", DSCC: "Dhaka South", CCC: "Chattogram", GCC: "Gazipur", NCC: "Narayanganj" };
const cityOrder = (a, b) => b.wards - a.wards || a.city.localeCompare(b.city);

/* Color class from expected weekly cases, so a quiet season reads as quiet. */
const shade = (v) => (v < 0.2 ? 0 : v < 1 ? 1 : v < 4 ? 2 : v < 8 ? 3 : v < 12 ? 4 : 5);

/* ---------------------------------------------------------------- hero map */
const state = { scenario: "peak", plans: {}, status: null };

async function planFor(sc) {
  if (!state.plans[sc]) state.plans[sc] = await api(`/api/operations?scenario=${sc}&stock=60&crews=40`);
  return state.plans[sc];
}

function readout(r, total) {
  $("#readout").replaceChildren(
    el("b", {}, r.ward_id), " ", el("span", {}, r.city), el("br"),
    `Expected ${f1(r.pred)} cases a week (range ${f1(r.lo)} to ${f1(r.hi)}). Priority rank ${r.rank} of ${total}.`);
}

async function drawMap() {
  const plan = await planFor(state.scenario);
  const wards = plan.wards, total = wards.length;
  const map = $("#tileMap");
  map.replaceChildren();
  const cities = plan.cities.slice().sort(cityOrder);
  const big = cities.filter((c) => c.wards >= 10), small = cities.filter((c) => c.wards < 10);
  const tilesOf = (c) => wards.filter((r) => r.city === c.city).sort((a, b) => a.ward_id.localeCompare(b.ward_id));
  const tile = (r) => {
    const t = el("button", {
      type: "button", class: `tile c${shade(r.pred)}`,
      style: `--d:${Math.min(900, r.rank * 12)}`,
      "aria-label": `${r.ward_id}, expected ${f1(r.pred)} cases a week, priority rank ${r.rank}`,
    }, r.ward_id.slice(-2));
    const show = () => { document.querySelectorAll(".tile.on").forEach((x) => x.classList.remove("on")); t.classList.add("on"); readout(r, total); };
    t.addEventListener("mouseenter", show); t.addEventListener("focus", show); t.addEventListener("click", show);
    return t;
  };
  const label = (c, half) => el("div", { class: `city-label${half ? " half" : ""}` }, c.city, el("small", {}, `${c.wards} wards`));
  for (const c of big) { map.append(label(c, false), ...tilesOf(c).map(tile)); }
  if (small.length) {
    map.append(...small.map((c) => label(c, true)));
    map.append(...small.flatMap((c) => tilesOf(c).map(tile)));
  }
  const top = wards[0];
  readout(top, total);
  const s = state.status.scenarios[state.scenario];
  $("#mapNote").textContent = state.scenario === "peak"
    ? `Replay from ${s.as_of}, forecast by models that had not seen 2025.`
    : `Forecast from ${s.as_of}, the latest data. Dengue is seasonal and this is the off-season, so most wards are near zero.`;
}

function bindSeg() {
  document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", async () => {
    state.scenario = b.dataset.sc;
    document.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    try { await drawMap(); } catch (e) { mapFailed(e); }
  }));
}

function mapFailed(e) {
  $("#tileMap").replaceChildren(el("p", { class: "unavailable" }, `The forecast service did not answer (${e.message}). Start it with: uvicorn app:app --host 127.0.0.1 --port 8000`));
}

/* ---------------------------------------------------- facts + accuracy */
function drawFacts(st) {
  const m = st.metrics.h2;
  $("#fWards").textContent = st.wards;
  $("#fRows").textContent = num(st.training_rows);
  $("#fGain").textContent = `${Math.round(100 * (1 - m.mae / m.mae_persistence))}%`;
  const max = Math.max(...["h2", "h3", "h4"].map((k) => st.metrics[k].mae_persistence));
  const box = $("#acc");
  box.replaceChildren(...["h2", "h3", "h4"].map((k) => {
    const x = st.metrics[k], w = (v) => `${(100 * v / max).toFixed(1)}%`;
    return el("div", { class: "row" }, el("h3", {}, `${k.slice(1)} weeks ahead`), el("div", { class: "bars" },
      el("span", {}, "Model"), el("div", { class: "track m" }, el("i", { style: `width:${w(x.mae)}` })), el("span", { class: "v" }, x.mae.toFixed(2)),
      el("span", {}, "Repeat last week"), el("div", { class: "track p" }, el("i", { style: `width:${w(x.mae_persistence)}` })), el("span", { class: "v" }, x.mae_persistence.toFixed(2))));
  }));
  const cov = ["h2", "h3", "h4"].map((k) => st.metrics[k].coverage_q10_q90 * 100);
  $("#covLine").textContent = `The 10th to 90th percentile range held ${Math.min(...cov).toFixed(0)} to ${Math.max(...cov).toFixed(0)}% of real outcomes on the held-out year.`;
}

/* ------------------------------------------------------- decision lanes */
function drawChart(w, dates) {
  const hs = ["h2", "h3", "h4"], W = 320, H = 190, L = 34, R = 26, T = 16, B = 34;
  const hi = hs.map((h) => w[`${h}_hi`]), lo = hs.map((h) => w[`${h}_lo`]), mean = hs.map((h) => w[`${h}_mean`]);
  const ymax = Math.max(2, Math.ceil(Math.max(...hi) / 2) * 2);
  const x = (i) => L + (i * (W - L - R)) / 2, y = (v) => T + (1 - v / ymax) * (H - T - B);
  const band = [...hi.map((v, i) => `${x(i)},${y(v)}`), ...lo.map((v, i) => `${x(2 - i)},${y(lo[2 - i])}`)].join(" ");
  const ticks = [0, ymax / 2, ymax].map((v) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join("");
  const xs = hs.map((h, i) => `<text x="${x(i)}" y="${H - 12}" text-anchor="middle">${(dates[h.slice(1)] || "").slice(5)}</text>`).join("");
  const dots = mean.map((v, i) => `<circle class="dot" cx="${x(i)}" cy="${y(v)}" r="4"/><text class="val" x="${x(i)}" y="${y(v) - 9}" text-anchor="middle">${f1(v)}</text>`).join("");
  const path = mean.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join("");
  $("#chart").innerHTML = `<svg viewBox="0 0 ${W} ${H}" aria-hidden="true">${ticks}<polygon class="band-area" points="${band}"/><path class="line" d="${path}"/>${dots}${xs}</svg>`;
  $("#chart").setAttribute("aria-label", `${w.ward_id} expected cases: ${mean.map(f1).join(", ")} for weeks 2, 3 and 4`);
  $("#chartCap").textContent = `${w.ward_id}, weekly cases. Line is the expected value; shaded area is the 10th to 90th percentile.`;
}

function drawAlloc(plan) {
  const first = plan.wards.slice(0, 3), seen = new Set(first.map((r) => r.ward_id));
  const short = plan.wards.filter((r) => r.deficit && !seen.has(r.ward_id)).slice(0, 3);
  const pct = (r) => (r.saline_req ? Math.round(100 * r.saline_alloc / r.saline_req) : 100);
  $("#allocList").replaceChildren(...[...first, ...short].map((r) => el("li", { class: r.saline_short > 0 ? "short" : "" },
    el("span", { class: "nm" }, r.ward_id, " ", el("small", {}, `rank ${r.rank}`)),
    el("span", { class: "ratio" }, `${r.saline_alloc} of ${r.saline_req} saline bags`),
    el("span", { class: "bar" }, el("i", { style: `width:${pct(r)}%` })))));
  $("#allocCap").textContent = `${plan.deficit_wards} of ${plan.wards.length} wards end up in critical deficit. Top-ranked wards are filled first; lower-ranked ones absorb the shortage.`;
}

async function drawDecisions() {
  const q = "scenario=peak&stock=40&crews=30";
  const [plan, fc] = await Promise.all([api(`/api/operations?${q}`), api("/api/forecast?scenario=peak")]);
  const top = plan.wards[0];
  drawChart(fc.wards.find((w) => w.ward_id === top.ward_id), fc.targets);
  drawAlloc(plan);
  const d = await api(`/api/dispatch/${top.ward_id}?${q}`);
  $("#smsText").textContent = d.sms;
  $("#smsCap").textContent = `SMS to ${top.ward_id}, ${d.sms_length} of 160 characters.`;
}

/* ------------------------------------------------------------ stress test */
async function runStress() {
  const btn = $("#runStress"), sum = $("#stressSum"), list = $("#stressList");
  btn.disabled = true; sum.textContent = "Running with every outbound connection blocked...";
  list.replaceChildren();
  try {
    const r = await api("/api/stress-test?scenario=peak");
    const ok = r.checks.filter((c) => c.passed).length;
    sum.textContent = `${r.passed ? "All checks passed" : "Some checks failed"}: ${ok} of ${r.checks.length} in ${r.elapsed_ms} ms, at 30% stock, 10 crews and a 3x surge.`;
    list.replaceChildren(...r.checks.map((c) => el("li", {}, el("span", { class: c.passed ? "pass" : "fail" }, c.passed ? "PASS" : "FAIL"), el("div", {}, c.check, el("small", {}, c.detail)))));
  } catch (e) { sum.textContent = `The stress test could not run: ${e.message}`; }
  btn.disabled = false;
}

async function init() {
  bindSeg();
  $("#runStress").addEventListener("click", runStress);
  try {
    state.status = await api("/api/status");
    drawFacts(state.status);
    await drawMap();
  } catch (e) { mapFailed(e); }
  try { await drawDecisions(); } catch (e) { $("#chartCap").textContent = `Unavailable: ${e.message}`; }
}
init();
