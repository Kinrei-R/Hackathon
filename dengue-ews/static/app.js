"use strict";
const TIERS = ["Low", "Medium", "High", "Critical"];
const COLORS = { Low: "#8fbaa9", Medium: "#ecc94b", High: "#e07a3c", Critical: "#a1233a" };
const $ = (s) => document.querySelector(s);
const state = { boot: null, idx: 0, h: 3, city: "All cities", ward: null, view: "forecast", val: null };
const cache = new Map(); // client-side response cache: one network call per unique query

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (n, d = 1) => Number(n).toFixed(d);
const day = (iso) => new Date(iso + "T00:00:00Z");
const longDate = (iso) => day(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const addDays = (iso, n) => new Date(day(iso).getTime() + n * 864e5);
const iso = (d) => d.toISOString().slice(0, 10);
const shortWard = (id) => id.replace(/_?Ward_?/i, " ").replace("_", " ").trim();
const tileLabel = (id) => id.split("_").pop();

async function api(path) {
  if (cache.has(path)) return cache.get(path);
  const p = fetch(path).then((r) => { if (!r.ok) throw new Error(path + " " + r.status); return r.json(); });
  cache.set(path, p);
  p.catch(() => cache.delete(path));
  return p;
}
const origin = () => state.boot.origins[state.idx];

/* ---------- controls ---------- */
function setupControls() {
  const b = state.boot, sl = $("#origin-slider");
  sl.max = b.origins.length - 1;
  state.idx = b.origins.length - 1;
  sl.value = state.idx;
  let timer;
  sl.addEventListener("input", () => { state.idx = +sl.value; $("#origin-label").textContent = longDate(origin()); clearTimeout(timer); timer = setTimeout(refresh, 120); });
  $("#prev").onclick = () => move(-1);
  $("#next").onclick = () => move(1);
  const presets = [["Latest week", b.latest_origin], ["Monsoon onset 2025", "2025-06-02"], ["Peak 2025", "2025-08-04"], ["Peak 2024", "2024-08-05"], ["Dry season 2025", "2025-02-03"]];
  $("#presets").innerHTML = presets.map(([l, d]) => `<button data-d="${d}">${l}</button>`).join("");
  $("#presets").onclick = (e) => { const d = e.target.dataset.d; if (d) goTo(d); };
  $("#horizon").onclick = (e) => {
    const h = e.target.dataset.h; if (!h) return;
    state.h = +h;
    document.querySelectorAll("#horizon button").forEach((x) => x.classList.toggle("on", x.dataset.h === h));
    refresh();
  };
  $("#city").innerHTML = b.cities.map((c) => `<option>${esc(c)}</option>`).join("");
  $("#city").onchange = (e) => { state.city = e.target.value; renderBoard(state.fc); };
  $("#legend").innerHTML = TIERS.map((t, i) => {
    const th = b.tiers.thresholds, lo = i === 0 ? 0 : th[i - 1], range = i === 3 ? `${lo}+` : `${lo} to <${th[i]}`;
    return `<li><span class="sw" style="background:${COLORS[t]}"></span>${t}<small>${range} cases</small></li>`;
  }).join("");
  document.querySelectorAll(".tabs button").forEach((t) => (t.onclick = () => switchView(t.dataset.view)));
  $("#trained").textContent = "Model trained " + b.trained_at.slice(0, 10) + ".";
}
function move(d) { state.idx = Math.min(Math.max(state.idx + d, 0), state.boot.origins.length - 1); $("#origin-slider").value = state.idx; refresh(); }
function goTo(d) {
  const o = state.boot.origins; let i = o.length - 1;
  while (i > 0 && o[i] > d) i--;
  state.idx = i; $("#origin-slider").value = i; refresh();
}
function switchView(v) {
  state.view = v;
  $("#view-forecast").hidden = v !== "forecast";
  $("#view-validation").hidden = v !== "validation";
  document.querySelectorAll(".tabs button").forEach((t) => t.setAttribute("aria-selected", t.dataset.view === v));
  if (v === "validation") renderValidation();
}

/* ---------- forecast view ---------- */
async function refresh() {
  $("#origin-label").textContent = longDate(origin());
  try {
    state.fc = await api(`/api/forecast?origin=${origin()}&horizon=${state.h}`);
  } catch (e) { $("#summary").innerHTML = `<p>Could not load the forecast. Check that the server is running and reload.</p>`; return; }
  $("#target-note").textContent = `Risk for the week of ${longDate(state.fc.target_date)}` + (state.fc.is_latest ? " (future, no outcome yet)." : ".");
  renderBoard(state.fc);
  if (state.ward) loadWard(state.ward);
}

function renderBoard(fc) {
  if (!fc) return;
  const wards = fc.wards.filter((w) => state.city === "All cities" || w.city === state.city);
  const counts = Object.fromEntries(TIERS.map((t) => [t, 0]));
  wards.forEach((w) => counts[w.tier]++);
  const n = wards.length, hot = counts.High + counts.Critical;
  $("#summary").innerHTML =
    `<p>${hot === 0 ? "No wards" : hot + " of " + n + " wards"} expected at High or Critical risk in the week of ${longDate(fc.target_date)}.</p>` +
    `<div class="bar" role="img" aria-label="${TIERS.map((t) => counts[t] + " " + t).join(", ")}">` +
    TIERS.filter((t) => counts[t]).map((t) => `<div style="flex:${counts[t]};background:${COLORS[t]};color:${t === "High" || t === "Critical" ? "#fff" : "#17262b"}">${counts[t]} ${t}</div>`).join("") + `</div>`;

  const byCity = {};
  wards.slice().sort((a, b) => a.ward_id.localeCompare(b.ward_id)).forEach((w) => (byCity[w.city] = byCity[w.city] || []).push(w));
  $("#board").innerHTML = Object.keys(byCity).sort().map((c) =>
    `<div class="city"><h3>${esc(c)}</h3><div class="tiles">` +
    byCity[c].map((w) => `<button class="tile t-${w.tier}" data-w="${w.ward_id}" aria-pressed="${w.ward_id === state.ward}" aria-label="${esc(shortWard(w.ward_id))}: ${w.tier} risk, about ${fmt(w.predicted_cases)} cases expected">` +
      `<small>${esc(tileLabel(w.ward_id))}</small><b>${fmt(w.predicted_cases, w.predicted_cases >= 10 ? 0 : 1)}</b></button>`).join("") + `</div></div>`).join("");
  $("#board").onclick = (e) => { const t = e.target.closest("[data-w]"); if (t) selectWard(t.dataset.w); };

  const hasActual = wards.some((w) => w.actual_cases !== null);
  $("#rank").innerHTML = `<tr><th>Ward</th><th>City</th><th>Tier</th><th class="num">Expected cases</th><th class="num">80% range</th><th>Could reach</th>${hasActual ? '<th class="num">Actual</th>' : ""}</tr>` +
    wards.slice(0, 8).map((w) => `<tr data-w="${w.ward_id}" tabindex="0"><td>${esc(shortWard(w.ward_id))}</td><td>${esc(w.city)}</td><td><span class="chip t-${w.tier}">${w.tier}</span></td>` +
      `<td class="num">${fmt(w.predicted_cases)}</td><td class="num">${fmt(w.low, 0)} to ${fmt(w.high, 0)}</td><td>${w.worst_case_tier}</td>${hasActual ? `<td class="num">${w.actual_cases} <span class="chip t-${w.actual_tier}">${w.actual_tier}</span></td>` : ""}</tr>`).join("");
  $("#rank").onclick = (e) => { const t = e.target.closest("[data-w]"); if (t) selectWard(t.dataset.w); };
  $("#rank").onkeydown = (e) => { if (e.key === "Enter") { const t = e.target.closest("[data-w]"); if (t) selectWard(t.dataset.w); } };
}

function selectWard(id) { state.ward = id; document.querySelectorAll(".tile").forEach((t) => t.setAttribute("aria-pressed", t.dataset.w === id)); loadWard(id); }

async function loadWard(id) {
  let d;
  try { d = await api(`/api/ward/${id}?origin=${origin()}&horizon=${state.h}`); }
  catch (e) { $("#detail").innerHTML = `<p class="empty">Could not load ${esc(id)}.</p>`; return; }
  if (state.ward !== id) return;
  const f = d.horizons[state.h];
  const sentence = `About ${fmt(f.predicted_cases, 0)} cases expected in the week of ${longDate(f.target_date)} (80% range ${fmt(f.low, 0)} to ${fmt(f.high, 0)}).` +
    (f.worst_case_tier !== f.tier ? ` The upper end would be ${f.worst_case_tier}.` : "");
  const maxAbs = Math.max(...d.drivers.map((x) => Math.abs(x.contribution)), 0.01);
  $("#detail").innerHTML =
    `<h3>${esc(shortWard(d.ward_id))}, ${esc(d.city)}</h3>` +
    `<p class="headline"><span class="chip t-${f.tier}">${f.tier}</span> ${sentence}</p>` +
    `<div class="fan">${[2, 3, 4].map((h) => { const x = d.horizons[h]; return `<button data-h="${h}" aria-pressed="${h === state.h}"><small>${h} weeks ahead</small><b>${fmt(x.predicted_cases, 0)}</b> <span class="chip t-${x.tier}">${x.tier}</span></button>`; }).join("")}</div>` +
    `<h4>Cases and the rainfall behind them</h4>${timeline(d)}` +
    `<div class="key"><span>&#9644; reported cases</span><span>&#9679; forecast with 80% range</span><span>&#9670; what happened next</span><span>shaded: last 5 weeks of rain, the model's closest lags</span></div>` +
    `<h4>What is driving this score (cases per week vs. an average ward-week)</h4>` +
    d.drivers.map((x) => { const w = Math.abs(x.contribution) / maxAbs * 50, pos = x.contribution >= 0;
      return `<div class="drv"><span>${esc(x.driver)}</span><div class="track"><div class="fill" style="left:${pos ? 50 : 50 - w}%;width:${w}%;background:${pos ? "var(--pos)" : "var(--neg)"}"></div></div><span class="v">${pos ? "+" : ""}${fmt(x.contribution, 1)}</span></div>`; }).join("") +
    `<p class="hint">Orange raises expected cases, blue lowers them. Values are exact Shapley contributions of each factor group.</p>` +
    `<h4>Key readings</h4><table class="facts">${d.facts.map((x) => `<tr><td>${esc(x.label)}</td><td class="num">${x.value} ${x.unit}</td><td class="num">typical ${x.typical}</td></tr>`).join("")}</table>`;
  $("#detail").querySelector(".fan").onclick = (e) => { const b = e.target.closest("[data-h]"); if (!b) return; state.h = +b.dataset.h; document.querySelectorAll("#horizon button").forEach((x) => x.classList.toggle("on", x.dataset.h === String(state.h))); refresh(); };
}

/* ---------- ward timeline chart (inline SVG) ---------- */
function timeline(d) {
  const W = 420, padL = 34, padR = 12, H1 = 170, H2 = 70, gap = 18;
  const start = addDays(d.origin, -15 * 7).getTime(), end = addDays(d.origin, 4 * 7).getTime();
  const x = (isoDate) => padL + ((day(isoDate).getTime() - start) / (end - start)) * (W - padL - padR);
  const hs = [2, 3, 4].map((h) => ({ h, ...d.horizons[h] }));
  const yMax = Math.max(4, ...d.history.map((p) => p.cases), ...hs.map((p) => p.high), ...d.realised_after_origin.map((p) => p.cases)) * 1.08;
  const y = (v) => 8 + (1 - v / yMax) * (H1 - 24);
  const rMax = Math.max(50, ...d.history.map((p) => p.rain_mm)) * 1.05;
  const bw = Math.max(3, (W - padL - padR) / 20 - 2);
  let s = `<svg viewBox="0 0 ${W} ${H1 + gap + H2 + 20}" role="img" aria-label="Weekly cases, forecast, and rainfall for ${esc(d.ward_id)}">`;
  for (let i = 0; i <= 4; i++) { const v = (yMax / 4) * i; s += `<line x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}" stroke="#e2e9ea"/><text x="${padL - 5}" y="${y(v) + 4}" text-anchor="end">${fmt(v, 0)}</text>`; }
  const pts = d.history.map((p) => `${x(p.date)},${y(p.cases)}`).join(" ");
  s += `<polyline points="${pts}" fill="none" stroke="#17262b" stroke-width="2"/>`;
  s += `<line x1="${x(d.origin)}" x2="${x(d.origin)}" y1="4" y2="${H1 - 14}" stroke="#5a6b70" stroke-dasharray="3 3"/><text x="${x(d.origin) - 4}" y="12" text-anchor="end">forecast made</text>`;
  hs.forEach((p) => {
    const cx = x(iso(addDays(d.origin, p.h * 7))), sel = p.h === state.h;
    s += `<line x1="${cx}" x2="${cx}" y1="${y(p.low)}" y2="${y(p.high)}" stroke="${COLORS[p.tier]}" stroke-width="${sel ? 6 : 4}" stroke-linecap="round" opacity=".55"/>`;
    s += `<circle cx="${cx}" cy="${y(p.predicted_cases)}" r="${sel ? 6 : 4.5}" fill="${COLORS[p.tier]}" stroke="#17262b" stroke-width="${sel ? 2 : 1}"/>`;
  });
  d.realised_after_origin.forEach((p) => { const cx = x(p.date), cy = y(p.cases); s += `<path d="M${cx} ${cy - 5}l5 5l-5 5l-5 -5z" fill="#fff" stroke="#17262b" stroke-width="1.5"/>`; });
  // rainfall panel
  const top = H1 + gap, ry = (v) => top + H2 - (v / rMax) * H2;
  const wx0 = x(iso(addDays(d.origin, -4 * 7))) - bw / 2 - 1, wx1 = x(d.origin) + bw / 2 + 1;
  s += `<rect x="${wx0}" y="${top}" width="${wx1 - wx0}" height="${H2}" fill="#dcebf1"/>`;
  s += `<text x="${padL - 5}" y="${top + 8}" text-anchor="end">${fmt(rMax, 0)}</text><text x="${padL - 5}" y="${top + H2}" text-anchor="end">0</text><text x="${W - padR}" y="${top - 5}" text-anchor="end">rainfall, mm per week</text>`;
  d.history.forEach((p) => { s += `<rect x="${x(p.date) - bw / 2}" y="${ry(p.rain_mm)}" width="${bw}" height="${top + H2 - ry(p.rain_mm)}" fill="#3d8aa0"/>`; });
  let last = "";
  d.history.forEach((p) => { const m = day(p.date).toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" }); if (m !== last) { s += `<text x="${x(p.date)}" y="${top + H2 + 14}" text-anchor="middle">${m}</text>`; last = m; } });
  return s + "</svg>";
}

/* ---------- validation view ---------- */
async function renderValidation() {
  const el = $("#view-validation");
  if (!state.val) { el.innerHTML = `<p class="empty">Loading validation results...</p>`; state.val = await api("/api/validation"); }
  const v = state.val, m = v.metrics, o = m.overall, sp = v.split;
  const pct = (x) => (x * 100).toFixed(0) + "%";
  const base = m.baselines;
  const rows = [["This model (weather lags + ward vulnerability)", o], ["Ward seasonal average (no weather)", base.ward_seasonal_mean], ["Last week's cases carried forward", base.persistence_last_week_cases], ["Same model plus case history (ablation)", base.ablation_plus_case_history_model]];
  el.innerHTML =
    `<p class="note">Held-out test: forecasts whose target week falls in 2024 to 2025 (${sp.n_test.toLocaleString()} ward-weeks, all lead times). The model never saw these weeks; 2023 was used only to choose the number of trees, and tier cut points come from the training years.</p>` +
    `<div class="cards">${[["MAE", fmt(o.mae, 2) + " cases"], ["RMSE", fmt(o.rmse, 2) + " cases"], ["R-squared", fmt(o.r2, 2)], ["Tier correct", pct(o.tier_accuracy)], ["Within one tier", pct(o.tier_within_one)], ["High+ recall", pct(o.high_or_critical_recall)], ["High+ precision", pct(o.high_or_critical_precision)], ["Range coverage (80% target)", pct(o.interval_80_coverage)]]
      .map(([k, val]) => `<div class="card"><b>${val}</b><span>${k}</span></div>`).join("")}</div>` +
    `<div class="two"><div class="card"><h2>Compared with simpler approaches</h2><table><tr><th>Approach</th><th class="num">MAE</th><th class="num">RMSE</th></tr>${rows.map(([n, r]) => `<tr><td>${n}</td><td class="num">${fmt(r.mae, 2)}</td><td class="num">${fmt(r.rmse, 2)}</td></tr>`).join("")}</table>` +
    `<p class="note">Case history adds nothing once weather lags are in, so production uses weather and ward traits only. That keeps the warning independent of delayed hospital reports.</p>` +
    `<h2 style="margin-top:14px">Accuracy by lead time</h2><table><tr><th>Lead time</th><th class="num">MAE</th><th class="num">RMSE</th><th class="num">Tier correct</th><th class="num">Coverage</th></tr>${Object.entries(m.by_horizon).map(([h, r]) => `<tr><td>${h} weeks</td><td class="num">${fmt(r.mae, 2)}</td><td class="num">${fmt(r.rmse, 2)}</td><td class="num">${pct(r.tier_accuracy)}</td><td class="num">${pct(r.interval_80_coverage)}</td></tr>`).join("")}</table>` +
    `<p class="note">The range is wider than 80% in practice (${pct(o.interval_80_coverage)} covered): weekly counts are zero-inflated, so the 10th and 90th percentile models are cautious. Treat it as a conservative range.</p></div>` +
    `<div class="card"><h2>Why lags matter: cases vs. rainfall k weeks earlier (correlation)</h2><div id="lagchart"></div><p class="note">Correlation peaks about three weeks after rain, matching mosquito breeding plus incubation time. Same-week rain is a much weaker signal.</p></div></div>` +
    `<div class="card"><h2>Predicted vs. actual cases over the test period</h2><div class="controls"><select id="vcity">${Object.keys(m.series["3"]).map((c) => `<option>${esc(c)}</option>`).join("")}</select><select id="vh">${[2, 3, 4].map((h) => `<option value="${h}" ${h === 3 ? "selected" : ""}>${h} weeks ahead</option>`).join("")}</select></div><div id="vchart"></div><p class="note">Weekly totals across the selected wards, each forecast made ${"2 to 4"} weeks before its target week.</p></div>` +
    `<div class="card"><h2>Risk tier confusion matrix</h2><div class="controls"><select id="cmh">${[2, 3, 4].map((h) => `<option value="${h}" ${h === 3 ? "selected" : ""}>${h} weeks ahead</option>`).join("")}</select></div><div id="cm"></div><p class="note">Rows are the tier that actually occurred, columns the tier predicted. Most errors are one tier off.</p></div>`;
  drawLag(v.lag_correlations);
  const draw = () => drawSeries(m.series[$("#vh").value][$("#vcity").value]);
  $("#vcity").onchange = draw; $("#vh").onchange = draw; draw();
  const cm = () => { const M = m.confusion[$("#cmh").value], mx = Math.max(...M.flat());
    $("#cm").innerHTML = `<table class="cm"><tr><th></th>${TIERS.map((t) => `<th>Pred. ${t}</th>`).join("")}</tr>${M.map((r, i) => `<tr><th>Actual ${TIERS[i]}</th>${r.map((c, j) => `<td style="background:rgba(29,90,115,${(c / mx * 0.85).toFixed(2)});color:${c / mx > 0.45 ? "#fff" : "inherit"}">${c.toLocaleString()}</td>`).join("")}</tr>`).join("")}</table>`; };
  $("#cmh").onchange = cm; cm();
}

function drawLag(lc) {
  const ks = Object.keys(lc), vals = ks.map((k) => lc[k]), mx = Math.max(...vals), W = 420, H = 190, pl = 34, bw = (W - pl - 10) / ks.length;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Correlation by rainfall lag in weeks">`;
  ks.forEach((k, i) => { const h = (lc[k] / 0.9) * (H - 40), best = lc[k] === mx;
    s += `<rect x="${pl + i * bw + 4}" y="${H - 24 - h}" width="${bw - 8}" height="${h}" fill="${best ? "#a1233a" : "#3d8aa0"}"/><text x="${pl + i * bw + bw / 2}" y="${H - 8}" text-anchor="middle">${k}</text><text x="${pl + i * bw + bw / 2}" y="${H - 28 - h}" text-anchor="middle">${lc[k].toFixed(2)}</text>`; });
  $("#lagchart").innerHTML = s + `<text x="${W - 10}" y="12" text-anchor="end">weeks of lag</text></svg>`;
}

function drawSeries(ser) {
  const W = 760, H = 240, pl = 40, pr = 10, n = ser.length, mx = Math.max(...ser.map((p) => Math.max(p.actual, p.predicted))) * 1.08;
  const x = (i) => pl + (i / (n - 1)) * (W - pl - pr), y = (v) => 10 + (1 - v / mx) * (H - 36);
  const line = (key, col, w) => `<polyline fill="none" stroke="${col}" stroke-width="${w}" points="${ser.map((p, i) => x(i) + "," + y(p[key])).join(" ")}"/>`;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Predicted versus actual weekly cases">`;
  for (let i = 0; i <= 4; i++) { const v = (mx / 4) * i; s += `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" stroke="#e2e9ea"/><text x="${pl - 5}" y="${y(v) + 4}" text-anchor="end">${fmt(v, 0)}</text>`; }
  let last = "";
  ser.forEach((p, i) => { const m = p.date.slice(0, 7); if (m !== last && (m.endsWith("01") || m.endsWith("07"))) { s += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${m}</text>`; } last = m; });
  s += line("actual", "#17262b", 2) + line("predicted", "#e07a3c", 2) +
    `<text x="${W - pr}" y="12" text-anchor="end" fill="#17262b">dark: actual, orange: predicted</text></svg>`;
  $("#vchart").innerHTML = s;
}

/* ---------- boot ---------- */
(async function init() {
  try { state.boot = await api("/api/bootstrap"); }
  catch (e) { document.body.insertAdjacentHTML("afterbegin", `<p style="padding:20px">The API is not reachable. Start the server with <code>python app.py</code>.</p>`); return; }
  setupControls();
  await refresh();
  const top = state.fc.wards[0];
  if (top) selectWard(top.ward_id);
})();
