// NOS dispatch replay: plays results/<scenario>/dashboard.json (packed by scripts/build_web.py).
// URL options: ?scenario=scenario_big  ?duration=45 (seconds)  ?tour=1 (all four, 2:00)  ?clean=1 (no controls)
"use strict";

const ORDER = ["scenario_small", "scenario_middle", "scenario_big", "scenario_competitive"];
const LABEL = { scenario_small: "Small", scenario_middle: "Middle", scenario_big: "Big", scenario_competitive: "Competitive" };
const TOUR = { scenario_small: 18, scenario_middle: 22, scenario_big: 35, scenario_competitive: 45 }; // = 120 s
const TITLE_S = 1.6;        // title card at the start of each tour step
const CSS = getComputedStyle(document.documentElement);
const C = (n) => CSS.getPropertyValue(n).trim();

const DATA = window.NOS_DATA || {};
const scenarios = ORDER.filter((s) => DATA[s]);
const params = new URLSearchParams(location.search);
if (params.get("clean") === "1") document.body.classList.add("clean");

// ---------------------------------------------------------------- assets
const img = {};
for (const n of ["standard", "refrigerated", "hazmat"]) { img[n] = new Image(); img[n].src = `assets/truck_${n}.svg`; }
img.cargo = new Image(); img.cargo.src = "assets/cargo.svg";

// ---------------------------------------------------------------- geometry
const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");
let W = 0, H = 0, DPR = 1;

function merc(lat) { return Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)); }

function makeProjection(cities) {
  const lons = cities.map((c) => c.lon), ys = cities.map((c) => merc(c.lat));
  let x0 = Math.min(...lons), x1 = Math.max(...lons), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const padX = (x1 - x0) * 0.12 + 1.5, padY = (y1 - y0) * 0.12 + 0.03;
  x0 -= padX; x1 += padX; y0 -= padY; y1 += padY;
  const sx = W / ((x1 - x0) * Math.PI / 180), sy = H / (y1 - y0), s = Math.min(sx, sy);
  const ox = (W - s * (x1 - x0) * Math.PI / 180) / 2, oy = (H - s * (y1 - y0)) / 2;
  return (lon, lat) => [ox + s * (lon - x0) * Math.PI / 180, oy + s * (y1 - merc(lat))];
}

// ---------------------------------------------------------------- scenario model
function prepare(sid) {
  const d = DATA[sid];
  const project = makeProjection(d.cities);
  PROJECT = project; PATHS = {};
  const city = {};
  for (const c of d.cities) city[c.id] = { ...c, xy: project(c.lon, c.lat) };
  const n = d.trucks.length;
  const trucks = d.trucks.map((t, k) => {
    const hue = (k * 137.508) % 360;
    const segs = t.timeline;
    const starts = segs.map((s) => s.start);
    const km0 = [];            // cumulative km / empty km at each segment start
    const em0 = [];
    let km = 0, em = 0, heading = 0;
    const head = [];           // heading per segment (road tangent), carried through stops
    for (const s of segs) {
      km0.push(km); em0.push(em);
      if (s.kind === "drive") { km += s.km; if (!s.loaded) em += s.km; }
      if (s.from) heading = pointAt(getPath(city, s.from, s.to), s.kind === "drive" ? s.f1 : s.f)[2];
      head.push(heading);
    }
    return { ...t, color: `hsl(${hue} 85% 62%)`, segs, starts, km0, em0, head,
             end: segs.length ? segs[segs.length - 1].end : 0, kmTotal: km, emTotal: em };
  });
  const deliveries = [], events = [];
  for (const t of d.trucks) for (const s of t.stops) {
    events.push({ t: s.departure_min, city: s.city, kind: s.action });
    if (s.action === "delivery") deliveries.push(s.departure_min);
  }
  deliveries.sort((a, b) => a - b);
  events.sort((a, b) => a.t - b.t);
  const eventTimes = events.map((e) => e.t);
  const base = renderBase(d, city, trucks);
  return { sid, d, city, trucks, deliveries, events, eventTimes, base, horizon: d.time.horizon_min || 1, truckSize: n > 15 ? 30 : 36 };
}

function renderBase(d, city, trucks) {
  const off = document.createElement("canvas");
  off.width = W * DPR; off.height = H * DPR;
  const g = off.getContext("2d");
  g.scale(DPR, DPR);
  g.fillStyle = C("--bg"); g.fillRect(0, 0, W, H);
  const project = makeProjection(d.cities);
  g.fillStyle = C("--land"); g.strokeStyle = C("--border"); g.lineWidth = 1;
  for (const ring of window.NOS_EUROPE || []) {
    g.beginPath();
    ring.forEach(([lon, lat], i) => { const [x, y] = project(lon, lat); i ? g.lineTo(x, y) : g.moveTo(x, y); });
    g.closePath(); g.fill(); g.stroke();
  }
  // cities
  g.font = "12px system-ui, sans-serif"; g.textBaseline = "middle";
  for (const c of Object.values(city)) {
    g.fillStyle = "#d7defa"; g.beginPath(); g.arc(c.xy[0], c.xy[1], 3.2, 0, 7); g.fill();
    g.fillStyle = C("--muted"); g.fillText(c.name, c.xy[0] + 6, c.xy[1] - 8);
  }
  g.font = "11px system-ui, sans-serif"; g.fillStyle = C("--muted"); g.textBaseline = "bottom";
  g.fillText("Roads © OpenStreetMap contributors (OSRM) · Map: Natural Earth", 10, H - 8);
  return off;
}

// ---- road geometry: a leg from -> to follows the OSRM road polyline (straight line if none)
let PROJECT = null, PATHS = {};
function getPath(city, from, to) {
  const key = from + ">" + to;
  if (PATHS[key]) return PATHS[key];
  const raw = (window.NOS_ROADS || {})[from < to ? from + "|" + to : to + "|" + from];
  let pts = raw && raw.length >= 2 ? raw.map(([lon, lat]) => PROJECT(lon, lat)) : [city[from].xy, city[to].xy];
  if (raw && from > to) pts.reverse();
  pts[0] = city[from].xy; pts[pts.length - 1] = city[to].xy;   // snap the ends onto the city dots
  const cum = [0];
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  return (PATHS[key] = { pts, cum, L: cum[cum.length - 1] || 1 });
}
function pointAt(p, f) {      // [x, y, heading] at fraction f of the road length
  const d = Math.min(Math.max(f, 0), 1) * p.L;
  let i = Math.max(1, upper(p.cum, d));
  if (i >= p.pts.length) i = p.pts.length - 1;
  const a = p.pts[i - 1], b = p.pts[i], seg = (p.cum[i] - p.cum[i - 1]) || 1, u = (d - p.cum[i - 1]) / seg;
  return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, Math.atan2(b[1] - a[1], b[0] - a[0])];
}
function lerp(city, s, f) { return pointAt(getPath(city, s.from, s.to), f); }
function line(g, city, s, f0, f1) {
  const p = getPath(city, s.from, s.to), a = pointAt(p, f0), b = pointAt(p, f1);
  g.beginPath(); g.moveTo(a[0], a[1]);
  for (let i = 1; i < p.pts.length - 1; i++) {
    const r = p.cum[i] / p.L;
    if (r > f0 && r < f1) g.lineTo(p.pts[i][0], p.pts[i][1]);
  }
  g.lineTo(b[0], b[1]); g.stroke();
}
function upper(arr, x) { let lo = 0, hi = arr.length; while (lo < hi) { const m = (lo + hi) >> 1; arr[m] <= x ? lo = m + 1 : hi = m; } return lo; }

// state of one truck at minute t
function stateAt(S, tr, t) {
  if (!tr.segs.length) return { xy: S.city[tr.start_city].xy, heading: 0, loaded: false, kind: "parked", km: 0, em: 0, done: true };
  const i = upper(tr.starts, t) - 1;
  if (i < 0) return { xy: S.city[tr.start_city].xy, heading: tr.head[0], loaded: false, kind: "idle", km: 0, em: 0 };
  const s = tr.segs[i];
  if (t >= tr.end) {
    const last = tr.segs[tr.segs.length - 1];
    return { xy: S.city[last.city || last.to].xy, heading: tr.head[tr.segs.length - 1], loaded: false, kind: "done",
             km: tr.kmTotal, em: tr.emTotal, done: true };
  }
  const u = (t - s.start) / Math.max(1, s.end - s.start);
  let xy, km = tr.km0[i], em = tr.em0[i];
  let heading = tr.head[i];
  if (s.kind === "drive") {
    const f = s.f0 + (s.f1 - s.f0) * u;
    const q = lerp(S.city, s, f); xy = [q[0], q[1]]; heading = q[2];
    km += s.km * u; if (!s.loaded) em += s.km * u;
  } else if (s.kind === "break" || s.kind === "rest") { const q = lerp(S.city, s, s.f); xy = [q[0], q[1]]; heading = q[2]; }
  else xy = S.city[s.city].xy;
  // service segments carry the load *before* the stop: show the box from the start of a pickup
  const loaded = s.kind === "service" ? s.action === "pickup" || s.loaded : s.loaded;
  return { xy, heading, loaded, kind: s.kind, km, em, seg: i };
}

// ---------------------------------------------------------------- drawing
function draw(S, t) {
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  ctx.drawImage(S.base, 0, 0, W, H);
  // short fading trail behind each truck: loaded solid in truck colour, empty dashed grey
  const TRAIL = S.horizon * 0.05, PIECES = 4;
  ctx.lineWidth = 3; ctx.lineCap = "round";
  for (const tr of S.trucks) {
    for (let k = upper(tr.starts, t) - 1; k >= 0 && tr.segs[k].end > t - TRAIL; k--) {
      const s = tr.segs[k];
      if (s.kind !== "drive") continue;
      const tA = Math.max(s.start, t - TRAIL), tB = Math.min(s.end, t);
      for (let q = 0; q < PIECES; q++) {       // split so the fade is smooth along long legs
        const a = tA + (tB - tA) * q / PIECES, b = tA + (tB - tA) * (q + 1) / PIECES;
        if (b <= a) continue;
        const fr = (x) => s.f0 + (s.f1 - s.f0) * (x - s.start) / Math.max(1, s.end - s.start);
        ctx.globalAlpha = Math.max(0, 1 - (t - b) / TRAIL);
        ctx.strokeStyle = s.loaded ? tr.color : C("--muted");
        ctx.setLineDash(s.loaded ? [] : [6, 6]);
        line(ctx, S.city, s, fr(a), fr(b));
      }
    }
  }
  ctx.globalAlpha = 1;
  ctx.setLineDash([]);
  // pickup / delivery pulses (last ~2% of the horizon)
  const win = S.horizon * 0.02;
  for (let k = upper(S.eventTimes, t) - 1; k >= 0 && S.events[k].t > t - win; k--) {
    const e = S.events[k], a = 1 - (t - e.t) / win, xy = S.city[e.city].xy;
    ctx.strokeStyle = e.kind === "delivery" ? `rgba(67,209,139,${a})` : `rgba(229,72,77,${a})`;
    ctx.lineWidth = 2.5; ctx.beginPath(); ctx.arc(xy[0], xy[1], 6 + 18 * (1 - a), 0, 7); ctx.stroke();
  }
  // trucks
  let km = 0, em = 0;
  for (const tr of S.trucks) {
    const st = stateAt(S, tr, t);
    km += st.km; em += st.em;
    drawTruck(S, tr, st);
  }
  return { km, em };
}

function drawTruck(S, tr, st) {
  const L = S.truckSize, Hh = L / 2;
  ctx.save();
  ctx.translate(st.xy[0], st.xy[1]);
  ctx.globalAlpha = st.kind === "parked" ? 0.35 : st.done ? 0.6 : 1;
  if (st.kind === "break" || st.kind === "rest") {
    ctx.strokeStyle = st.kind === "break" ? C("--break") : C("--rest");
    ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(0, 0, L * 0.62, 0, 7); ctx.stroke();
  }
  ctx.rotate(st.heading);
  if (st.loaded && img.cargo.complete) ctx.drawImage(img.cargo, -L * 0.5 - Hh * 0.9, -Hh * 0.45, Hh * 0.9, Hh * 0.9);
  ctx.fillStyle = tr.color;                       // colour tag identifying the truck
  ctx.fillRect(-L / 2, -Hh / 2 - 4, L, 3);
  const im = img[tr.type] || img.standard;
  if (im.complete) ctx.drawImage(im, -L / 2, -Hh / 2, L, Hh);
  ctx.restore();
}

function drawSpark(S, frac) {
  const c = document.getElementById("spark"), g = c.getContext("2d"), h = S.d.search_history;
  g.clearRect(0, 0, c.width, c.height);
  if (!h || h.length < 2) { g.fillStyle = C("--muted"); g.font = "13px system-ui"; g.fillText("no search history for this scenario", 4, 46); return; }
  const lo = Math.min(...h.map((p) => p.best)), hi = Math.max(...h.map((p) => p.best)), T = h[h.length - 1].t || 1;
  const X = (p) => 4 + (c.width - 8) * p.t / T, Y = (v) => c.height - 14 - (c.height - 28) * (v - lo) / Math.max(1e-6, hi - lo);
  g.strokeStyle = C("--score"); g.lineWidth = 2; g.beginPath();
  const upto = Math.max(1, Math.floor(h.length * frac));
  h.slice(0, upto).forEach((p, i) => i ? g.lineTo(X(p), Y(p.best)) : g.moveTo(X(p), Y(p.best)));
  g.stroke();
  g.fillStyle = C("--muted"); g.font = "11px system-ui";
  g.fillText(lo.toFixed(2), 4, c.height - 2); g.fillText(hi.toFixed(2), c.width - 50, 11);
}

function sidePanel(S) {
  const st = S.d.stages || [], max = Math.max(...st.map((s) => s.score), 1000);
  document.getElementById("stages").innerHTML = st.map((s, i) =>
    `<div class="stage ${i === st.length - 1 ? "final" : ""}"><div class="name">${s.name.split(" (")[0]}<b>${s.score.toFixed(1)}</b></div>` +
    `<div class="bar"><i style="width:${Math.max(0, 100 * s.score / max)}%"></i></div></div>`).join("");
  const b = S.d.bounds || {}, k = S.d.kpis, ub = b.score_upper_bound;
  document.getElementById("bound").innerHTML = ub ?
    `Our score <b>${k.score.toFixed(2)}</b> · upper bound <b>${ub.toFixed(2)}</b> (Lagrangian relaxation)` +
    `<div class="gauge"><i style="width:${100 * k.score / 1000}%"></i><u style="left:${100 * ub / 1000}%"></u></div>` +
    `Time-window orders: <b>${b.window_served}/${b.window_orders}</b> served, at most <b>${b.window_max}</b> possible.` : "";
}

// ---------------------------------------------------------------- playback
let S = null, sid = null, duration = 45, t0 = performance.now(), played = 0, playing = true, tour = null;
const $ = (id) => document.getElementById(id);
const fmt = (x) => Math.round(x).toLocaleString("en-US");

function load(id) {
  sid = id; S = prepare(id); sidePanel(S); $("s-scen").value = id;
  $("k-scen").textContent = `${LABEL[id]} · ${S.d.trucks.length} trucks · ${S.d.orders.length} orders`;
  $("k-score").textContent = S.d.kpis.score.toFixed(2);
}

function frame(now) {
  if (playing) played += (now - t0) / 1000;
  t0 = now;
  if (tour) {
    let acc = 0, step = -1;
    for (let i = 0; i < tour.length; i++) { if (played < acc + TOUR[tour[i]]) { step = i; break; } acc += TOUR[tour[i]]; }
    if (step < 0) { step = tour.length - 1; acc -= TOUR[tour[step]]; }   // tour finished: hold the last frame
    if (tour[step] !== sid) load(tour[step]);
    const local = Math.min(played - acc, TOUR[sid]);
    $("title-card").classList.toggle("hidden", local > TITLE_S);
    if (local <= TITLE_S) { $("tc-title").textContent = LABEL[sid]; $("tc-sub").textContent = $("k-scen").textContent; }
    render(Math.max(0, (local - TITLE_S) / (TOUR[sid] - TITLE_S)));
    if (played >= Object.values(TOUR).reduce((a, b) => a + b, 0)) playing = false;
  } else {
    $("title-card").classList.add("hidden");
    render(Math.min(1, played / duration));
    if (played >= duration) playing = false;
  }
  requestAnimationFrame(frame);
}

function render(frac) {
  const t = frac * S.horizon;
  const { km, em } = draw(S, t);
  const day = 1 + Math.floor((t + 360) / 1440), mm = Math.floor(t + 360) % 1440;
  $("k-clock").textContent = `Day ${day} · ${String(Math.floor(mm / 60)).padStart(2, "0")}:${String(mm % 60).padStart(2, "0")}`;
  $("k-deliv").textContent = `${upper(S.deliveries, t)} / ${S.d.orders.length}`;
  $("k-km").textContent = fmt(km);
  $("k-empty").textContent = km ? `${(100 * em / km).toFixed(1)} %` : "–";
  $("seek").value = Math.round(frac * 1000);
  drawSpark(S, frac);
}

function resize() {
  DPR = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  W = r.width; H = r.height;
  canvas.width = W * DPR; canvas.height = H * DPR;
  if (sid) load(sid);
}

function startTour() { tour = scenarios.slice(); played = 0; playing = true; }
function setScenario(id) { tour = null; load(id); played = 0; playing = true; }

// ---------------------------------------------------------------- UI
for (const s of scenarios) $("s-scen").insertAdjacentHTML("beforeend", `<option value="${s}">${LABEL[s]}</option>`);
$("s-scen").onchange = (e) => setScenario(e.target.value);
$("s-dur").onchange = (e) => { duration = +e.target.value; };
$("b-play").onclick = () => { playing = !playing; };
$("b-tour").onclick = startTour;
$("seek").oninput = (e) => { const f = e.target.value / 1000; tour = null; played = f * duration; };
window.addEventListener("keydown", (e) => {
  if (e.key === " ") { playing = !playing; e.preventDefault(); }
  else if (e.key === "ArrowRight") played = Math.min(duration, played + duration * 0.05);
  else if (e.key === "ArrowLeft") played = Math.max(0, played - duration * 0.05);
  else if (e.key >= "1" && e.key <= "4" && scenarios[+e.key - 1]) setScenario(scenarios[+e.key - 1]);
  else if (e.key === "t" || e.key === "T") startTour();
  else if (e.key === "r" || e.key === "R") { played = 0; playing = true; }
  else if (e.key === "h" || e.key === "H") { document.body.classList.toggle("clean"); setTimeout(resize, 50); }
});
window.addEventListener("resize", resize);

if (!scenarios.length) {
  document.body.innerHTML = "<p style='padding:40px'>No scenario data. Run: uv run python scripts/build_web.py</p>";
} else {
  duration = +(params.get("duration") || duration);
  $("s-dur").value = String(duration);
  resize();
  load(params.get("scenario") && DATA[params.get("scenario")] ? params.get("scenario") : scenarios[scenarios.length - 1]);
  if (params.get("tour") === "1") startTour();
  requestAnimationFrame(frame);
}
