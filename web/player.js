// NOS dispatch replay: plays results/<scenario>/dashboard.json (packed by scripts/build_web.py).
// URL options: ?scenario=scenario_big  ?duration=45 (seconds)  ?tour=1 (all four, 2:00)  ?clean=1 (no controls)
//
// Everything on screen is computed from the plan data at the current minute:
// - the score is the official formula on what has happened so far (value delivered, km, loaded km,
//   cost, CO2), so it reaches the final score exactly when the last truck finishes;
// - the bubbles (CO2 score, time-window orders served, empty km) fill up as the trucks work;
// - truck sprite = fuel class from the truck's CO2 per km (lowest third electric, middle LNG,
//   highest diesel); top view while driving, side view while stopped; tractor alone while empty,
//   trailer hooked on behind it while loaded.
"use strict";

const ORDER = ["scenario_small", "scenario_middle", "scenario_big", "scenario_competitive"];
const LABEL = { scenario_small: "Small", scenario_middle: "Middle", scenario_big: "Big", scenario_competitive: "Competitive" };
// tour for the demo video: 70 s of Competitive only, leaving room for the 50 s emergency video in a
// 2-minute demo. ?tour=full plays all four scenarios in 2:00 as before.
const TOUR_FULL = { scenario_small: 18, scenario_middle: 22, scenario_big: 35, scenario_competitive: 45 }; // = 120 s
const TOUR_SHORT = { scenario_competitive: 70 };                                                          // = 70 s
const TOUR = new URLSearchParams(location.search).get("tour") === "full" ? TOUR_FULL : TOUR_SHORT;
const TITLE_S = 5;          // title card at the start of each tour step
const RESULT_S = 4;         // results card at the end of each tour step
const W8 = { F: 0.5, C: 0.2, R: 0.15, G: 0.15 };   // official score weights
const DATA = window.NOS_DATA || {};
const scenarios = ORDER.filter((s) => DATA[s]);
const params = new URLSearchParams(location.search);

// theme: dark (default, GRUBER slide palette) or light (?theme=light, D key); canvas colours come from the CSS tokens
if (params.get("theme") !== "light") document.documentElement.dataset.theme = "dark";
const C = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
let COL = {};
function readColours() { COL = { muted: C("--muted"), brk: C("--break"), rst: C("--rest"), text: C("--text"), city: C("--city") }; }
readColours();
if (params.get("clean") === "1") document.body.classList.add("clean");

// ---------------------------------------------------------------- fuel classes (from the data)
const FUELS = ["electric", "lng", "diesel"];
const FUEL_LABEL = { electric: "Electric", lng: "LNG", diesel: "Diesel" };
const allCo2 = scenarios.flatMap((s) => DATA[s].trucks.map((t) => t.co2_per_km)).sort((a, b) => a - b);
const Q1 = allCo2[Math.floor(allCo2.length / 3)] ?? 0, Q2 = allCo2[Math.floor((2 * allCo2.length) / 3)] ?? 0;
const fuelOf = (co2) => (co2 < Q1 ? "electric" : co2 < Q2 ? "lng" : "diesel");

// ---------------------------------------------------------------- assets
const img = {};
for (const f of FUELS) for (const k of ["truck", "cab", "side", "tractor"]) { const n = `${k}_${f}`; img[n] = new Image(); img[n].src = `assets/${n}.png`; }
// images are rasterised once at the drawn size: scaling a big image every frame is slow
const sprite = {};
function sprites(L) {
  const H = L / 2.8, sc = 2 * (window.devicePixelRatio || 1);
  for (const [k, im] of Object.entries(img)) {
    if (!im.complete || !im.naturalWidth) { sprite[k] = null; continue; }
    const h = k.startsWith("side") || k.startsWith("tractor") ? L / 2.15 : H;   // side views: same length as the top view
    const w = (im.naturalWidth / im.naturalHeight) * h;
    const c = document.createElement("canvas");
    c.width = Math.ceil(w * sc); c.height = Math.ceil(h * sc);
    const g = c.getContext("2d"); g.imageSmoothingQuality = "high";
    g.drawImage(im, 0, 0, c.width, c.height);
    sprite[k] = { c, w, h };
  }
}
for (const k of Object.keys(img)) img[k].onload = () => S && sprites(S.truckSize);

// ---------------------------------------------------------------- geometry
const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");
let W = 0, H = 0, DPR = 1;

// map zoom / pan: screen = VIEW.x + VIEW.z * fitted position
let VIEW = { z: 1, x: 0, y: 0 };
function merc(lat) { return Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)); }

function makeProjection(cities) {
  const lons = cities.map((c) => c.lon), ys = cities.map((c) => merc(c.lat));
  let x0 = Math.min(...lons), x1 = Math.max(...lons), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const padX = (x1 - x0) * 0.12 + 1.5, padY = (y1 - y0) * 0.12 + 0.03;
  x0 -= padX; x1 += padX; y0 -= padY; y1 += padY;
  const sx = W / ((x1 - x0) * Math.PI / 180), sy = H / (y1 - y0), s = Math.min(sx, sy);
  const ox = (W - s * (x1 - x0) * Math.PI / 180) / 2, oy = (H - s * (y1 - y0)) / 2;
  return (lon, lat) => [VIEW.x + VIEW.z * (ox + s * (lon - x0) * Math.PI / 180), VIEW.y + VIEW.z * (oy + s * (y1 - merc(lat)))];
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
    return { ...t, color: `hsl(${hue} 85% 62%)`, fuel: fuelOf(t.co2_per_km), segs, starts, km0, em0, head,
             end: segs.length ? segs[segs.length - 1].end : 0, kmTotal: km, emTotal: em };
  });
  // deliveries in time order with the value they bring (lateness-scaled as in the official score)
  const ord = Object.fromEntries(d.orders.map((o) => [o.id, o]));
  const isWin = (o) => !!(o.pickup_window || o.delivery_window);
  const dl = [], events = [];
  for (const t of d.trucks) for (const s of t.stops) {
    events.push({ t: s.departure_min, city: s.city, kind: s.action });
    if (s.action !== "delivery") continue;
    const o = ord[s.order], late = s.late_min || 0;
    if (late > 60) continue;
    dl.push({ t: s.departure_min, v: o.value * (1 - 0.5 * late / 60), w: isWin(o) ? 1 : 0 });
  }
  dl.sort((a, b) => a.t - b.t);
  const delivT = dl.map((x) => x.t), delivV = [0], delivW = [0];
  for (const x of dl) { delivV.push(delivV[delivV.length - 1] + x.v); delivW.push(delivW[delivW.length - 1] + x.w); }
  events.sort((a, b) => a.t - b.t);
  const eventTimes = events.map((e) => e.t);
  const ref = d.orders.reduce((a, o) => a + o.direct_km, 0) / d.orders.length;   // reference km per order
  const formula = { V: d.kpis.value_total, ref, minCost: Math.min(...d.trucks.map((t) => t.cost_per_km)),
                    minCo2: Math.min(...d.trucks.map((t) => t.co2_per_km)), viol: d.kpis.violations || 0 };
  const base = renderBase(d, city);
  return { sid, d, city, trucks, delivT, delivV, delivW, events, eventTimes, base, formula,
           winTotal: d.orders.filter(isWin).length,
           horizon: d.time.horizon_min || 1, truckSize: n > 15 ? 35 : 42 };
}

// official score of everything that has happened up to now
function liveScore(S, x) {
  const f = S.formula, k = upper(S.delivT, x.t), count = k, value = S.delivV[k];
  const refKm = f.ref * count;
  const F = 100 * value / f.V;
  const Cc = x.cost ? 100 * Math.min(1, refKm * f.minCost / x.cost) : 0;
  const G = x.co2 ? 100 * Math.min(1, refKm * f.minCo2 / x.co2) : 0;
  const R = x.km ? 100 * (x.km - x.em) / x.km : 0;
  const score = 10 * (W8.F * F + W8.C * Cc + W8.R * R + W8.G * G) - (x.t >= S.horizon ? 20 * f.viol : 0);
  return { score: Math.max(0, score), F, C: Cc, R, G, count, win: S.delivW[k] };
}

// label with an outline in the colour underneath it: dark text on land, light text on the dark sea
// (the background is sampled from the base map before any label is drawn, so no white boxes on the sea)
function hexRgb(h) { const n = parseInt(h.replace("#", "").slice(0, 6), 16); return [n >> 16, (n >> 8) & 255, n & 255]; }
function onSea(g, x, y) {
  const p = g.getImageData(Math.round(x * DPR), Math.round(y * DPR), 1, 1).data, s = hexRgb(C("--sea"));
  return Math.abs(p[0] - s[0]) + Math.abs(p[1] - s[1]) + Math.abs(p[2] - s[2]) < 40;
}
function halo(g, text, x, y, sea) {
  g.lineJoin = "round"; g.lineWidth = 3.5;
  g.strokeStyle = C(sea ? "--sea" : "--land"); g.strokeText(text, x, y);
  g.fillStyle = sea ? "#dbe7f7" : C("--muted"); g.fillText(text, x, y);
}

function renderBase(d, city) {
  const off = document.createElement("canvas");
  off.width = W * DPR; off.height = H * DPR;
  const g = off.getContext("2d");
  g.scale(DPR, DPR);
  g.fillStyle = C("--sea"); g.fillRect(0, 0, W, H);
  const project = makeProjection(d.cities);
  g.fillStyle = C("--land"); g.strokeStyle = C("--border"); g.lineWidth = 1;
  for (const ring of window.NOS_EUROPE || []) {
    g.beginPath();
    ring.forEach(([lon, lat], i) => { const [x, y] = project(lon, lat); i ? g.lineTo(x, y) : g.moveTo(x, y); });
    g.closePath(); g.fill(); g.stroke();
  }
  g.font = "12px system-ui, sans-serif"; g.textBaseline = "middle";
  const labels = Object.values(city).map((c) => {          // sample every label's background first
    const x = c.xy[0] + 6, y = c.xy[1] - 8, w = g.measureText(c.name).width;
    return { c, x, y, sea: x + w / 2 >= 0 && x + w / 2 < W && y >= 0 && y < H && onSea(g, x + w / 2, y) };
  });
  for (const { c, x, y, sea } of labels) {
    g.fillStyle = COL.city; g.beginPath(); g.arc(c.xy[0], c.xy[1], 3.2, 0, 7); g.fill();
    halo(g, c.name, x, y, sea);
  }
  // attribution on a small panel-coloured plate so it reads over land and sea alike
  const credit = "Roads © OpenStreetMap contributors (OSRM) · Map: Natural Earth";
  g.font = "11px system-ui, sans-serif"; g.textBaseline = "bottom";
  const cw = g.measureText(credit).width;
  g.globalAlpha = 0.85; g.fillStyle = C("--panel"); g.fillRect(4, H - 24, cw + 12, 20); g.globalAlpha = 1;
  g.fillStyle = C("--muted"); g.fillText(credit, 10, H - 8);
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
  const i1 = Math.min(p.pts.length - 1, upper(p.cum, f1 * p.L));
  for (let i = upper(p.cum, f0 * p.L); i < i1; i++) g.lineTo(p.pts[i][0], p.pts[i][1]);  // only interior points
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
  // service segments carry the load *before* the stop: show the trailer from the start of a pickup
  const loaded = s.kind === "service" ? s.action === "pickup" || s.loaded : s.loaded;
  return { xy, heading, loaded, kind: s.kind, action: s.action, km, em, seg: i };
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
        ctx.strokeStyle = s.loaded ? tr.color : COL.muted;
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
  // trucks + running totals for the live score
  let km = 0, em = 0, cost = 0, co2 = 0, active = 0;
  for (const tr of S.trucks) {
    const st = stateAt(S, tr, t);
    km += st.km; em += st.em; cost += st.km * tr.cost_per_km; co2 += st.km * tr.co2_per_km;
    if (!st.done && st.kind !== "idle") active++;
    tr.st = st;
    drawTruck(S, tr, st);
  }
  return { t, km, em, cost, co2, active };
}

function drawTruck(S, tr, st) {
  // top view, turned along the road: tractor alone while empty, the trailer hooks on behind it at a pickup
  const L = S.truckSize, Hh = L / 2.8;
  ctx.save();
  ctx.translate(st.xy[0], st.xy[1]);
  ctx.globalAlpha = st.kind === "parked" ? 0.35 : st.done ? 0.6 : 1;
  if (st.kind === "break" || st.kind === "rest") {
    ctx.strokeStyle = st.kind === "break" ? COL.brk : COL.rst;
    ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(0, 0, L * 0.6, 0, 7); ctx.stroke();
  }
  if (st.kind !== "drive") {                      // stopped (stop, wait, break, rest, done): side view, upright
    if (Math.cos(st.heading) > 0) ctx.scale(-1, 1); // the side renders face left; mirror so the cab faces the way it came
    const sv = sprite[`${st.loaded ? "side" : "tractor"}_${tr.fuel}`];
    if (sv) ctx.drawImage(sv.c, -L / 2, -sv.h / 2, sv.w, sv.h);
    if (sv && tr.type !== "standard") {
      ctx.fillStyle = tr.type === "hazmat" ? "#ff9f1c" : "#5ec8ff";
      ctx.beginPath(); ctx.arc(-L / 2 + sv.h * 0.35, -sv.h / 2 - 4, Math.max(2.5, Hh * 0.2), 0, 7); ctx.fill();
    }
    ctx.restore();
    return;
  }
  ctx.rotate(st.heading);
  if (Math.cos(st.heading) < 0) ctx.scale(1, -1);  // driving west: keep the sprite upright, not upside down
  const sp = sprite[`${st.loaded ? "truck" : "cab"}_${tr.fuel}`];
  const front = L / 2;                            // nose stays at the same spot, the trailer extends behind
  if (sp) ctx.drawImage(sp.c, front - sp.w, -sp.h / 2, sp.w, sp.h);
  if (tr.type !== "standard") {                   // refrigerated / hazmat badge on the cab roof
    ctx.fillStyle = tr.type === "hazmat" ? "#ff9f1c" : "#5ec8ff";
    ctx.beginPath(); ctx.arc(front - Hh * 0.55, 0, Math.max(2.5, Hh * 0.2), 0, 7); ctx.fill();
  }
  ctx.restore();
}

// ---------------------------------------------------------------- side panel (DOM)
const $ = (id) => document.getElementById(id);
const fmt = (x) => Math.round(x).toLocaleString("en-US");
const shown = {};
function setText(id, v) { if (shown[id] !== v) { shown[id] = v; $(id).textContent = v; } }  // avoid per-frame DOM writes
function setStyle(id, prop, v) { const k = id + "." + prop; if (shown[k] !== v) { shown[k] = v; $(id).style.setProperty(prop, v); } }

function updatePanel(S, x, live) {
  for (const [id, v] of [["c-F", live.F], ["c-C", live.C], ["c-R", live.R], ["c-G", live.G]]) {
    setStyle(id, "width", `${v.toFixed(1)}%`); setText(id + "-v", v.toFixed(0));
  }
  const pct = 100 * live.score / S.ceiling;
  setStyle("ceil-bar", "width", `${Math.min(100, pct).toFixed(1)}%`);
  setText("ceil-v", `${pct.toFixed(1)} %`);
}

// results card: one big score and three numbers, from the final data
function resultsCard(S) {
  const k = S.d.kpis;
  $("rc-scen").textContent = `${LABEL[S.sid]} · ${S.d.cities.length} cities · ${S.d.trucks.length} trucks · ${S.d.orders.length} orders`;
  $("rc-score").textContent = k.score.toFixed(2);
  $("rc-ceil").textContent = `${(100 * k.score / S.ceiling).toFixed(1)} % of the proven best possible score`;
  $("rc-deliv").textContent = `${k.orders_fulfilled} / ${k.orders_total}`;
  $("rc-empty").textContent = `${(100 * k.empty_km / k.total_km).toFixed(1)} %`;
  $("rc-co2").textContent = `${k.breakdown.co2_efficiency.toFixed(0)} / 100`;
}

// ---------------------------------------------------------------- playback
let S = null, sid = null, duration = 45, t0 = performance.now(), played = 0, playing = true, tour = null;

function load(id) {
  sid = id; S = prepare(id); S.ceiling = (S.d.bounds || {}).score_upper_bound || 1000;
  sprites(S.truckSize); resultsCard(S); $("s-scen").value = id;
  $("k-scen").textContent = `${LABEL[id]} · ${S.d.trucks.length} trucks`;
  $("ceil-note").textContent = `of ${S.ceiling.toFixed(2)}, the computed upper bound`;
}

function frame(now) {
  if (playing) played += (now - t0) / 1000;
  t0 = now;
  if (tour) {
    let acc = 0, step = -1;
    for (let i = 0; i < tour.length; i++) { if (played < acc + TOUR[tour[i]]) { step = i; break; } acc += TOUR[tour[i]]; }
    if (step < 0) { step = tour.length - 1; acc -= TOUR[tour[step]]; }   // tour finished: hold the last frame
    if (tour[step] !== sid) { resetView(false); load(tour[step]); }
    const local = Math.min(played - acc, TOUR[sid]);
    $("title-card").classList.toggle("hidden", local > TITLE_S);
    if (local <= TITLE_S) { $("tc-title").textContent = LABEL[sid]; $("tc-sub").textContent = $("k-scen").textContent; }
    render(Math.min(1, Math.max(0, (local - TITLE_S) / (TOUR[sid] - TITLE_S - RESULT_S))));
    $("results").classList.toggle("hidden", local < TOUR[sid] - RESULT_S);
    if (played >= tour.reduce((a, s) => a + TOUR[s], 0)) playing = false;
  } else {
    $("title-card").classList.add("hidden");
    render(Math.min(1, played / duration));
    $("results").classList.toggle("hidden", played < duration + 0.3);
    if (played >= duration + 0.3) playing = false;
  }
  requestAnimationFrame(frame);
}

function render(frac) {
  const t = frac * S.horizon;
  const x = draw(S, t);
  const live = liveScore(S, x);
  const day = 1 + Math.floor((t + 360) / 1440), mm = Math.floor(t + 360) % 1440;
  setText("k-clock", `Day ${day} · ${String(Math.floor(mm / 60)).padStart(2, "0")}:${String(mm % 60).padStart(2, "0")}`);
  setText("k-deliv", `${live.count} / ${S.d.orders.length}`);
  setText("k-empty", x.km ? `${(100 * x.em / x.km).toFixed(1)} %` : "–");
  setText("k-score", live.score.toFixed(2));
  updatePanel(S, x, live);
  const sv = String(Math.round(frac * 1000));
  if (shown.seek !== sv) { shown.seek = sv; $("seek").value = sv; }
  if (FPS) drawFps();
}

// optional frame-rate readout: ?fps=1
const FPS = params.get("fps") === "1";
let fpsT = performance.now(), fpsN = 0, fpsV = 0;
function drawFps() {
  fpsN++;
  const now = performance.now();
  if (now - fpsT >= 500) { fpsV = (1000 * fpsN) / (now - fpsT); fpsN = 0; fpsT = now; }
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  ctx.fillStyle = COL.text; ctx.font = "14px system-ui"; ctx.textBaseline = "top";
  ctx.fillText(`${fpsV.toFixed(0)} fps`, W - 70, 10);
}

function resize() {
  DPR = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  W = r.width; H = r.height;
  canvas.width = W * DPR; canvas.height = H * DPR;
  if (sid) load(sid);
}

function startTour() { tour = scenarios.filter((s) => TOUR[s]); played = 0; playing = true; }
function toggleTheme() {
  const r = document.documentElement;
  if (r.dataset.theme === "dark") delete r.dataset.theme; else r.dataset.theme = "dark";
  readColours(); resize();
}
function setScenario(id) { tour = null; resetView(false); load(id); played = 0; playing = true; }

// ---------------------------------------------------------------- zoom & pan (wheel, drag, +/- buttons, 0 = reset)
let rebuildQueued = false;
function rebuild() {                     // re-project cities, roads and the base map at the new zoom (stays sharp)
  if (rebuildQueued || !sid) return;
  rebuildQueued = true;
  requestAnimationFrame(() => { rebuildQueued = false; const keep = S.trucks.map((t) => t.st); S = prepare(sid);
    S.trucks.forEach((t, k) => { t.st = keep[k]; }); });
}
function zoomAt(mx, my, factor) {
  const z = Math.min(12, Math.max(1, VIEW.z * factor)), f = z / VIEW.z;
  VIEW = z === 1 ? { z: 1, x: 0, y: 0 } : { z, x: mx - (mx - VIEW.x) * f, y: my - (my - VIEW.y) * f };
  rebuild(); setText("zoom-level", `${VIEW.z.toFixed(1)}×`);
}
function resetView(redraw = true) { VIEW = { z: 1, x: 0, y: 0 }; setText("zoom-level", "1.0×"); if (redraw) rebuild(); }
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const r = canvas.getBoundingClientRect();
  zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0015));
}, { passive: false });
let drag = null;
canvas.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY }; canvas.setPointerCapture(e.pointerId); canvas.style.cursor = "grabbing"; });
canvas.addEventListener("pointermove", (e) => {
  if (!drag || VIEW.z === 1) return;
  VIEW.x += e.clientX - drag.x; VIEW.y += e.clientY - drag.y; drag = { x: e.clientX, y: e.clientY }; rebuild();
});
canvas.addEventListener("pointerup", () => { drag = null; canvas.style.cursor = ""; });
canvas.addEventListener("dblclick", () => resetView());
$("z-in").onclick = () => zoomAt(W / 2, H / 2, 1.5);
$("z-out").onclick = () => zoomAt(W / 2, H / 2, 1 / 1.5);
$("z-reset").onclick = () => resetView();

// ---------------------------------------------------------------- UI
for (const s of scenarios) $("s-scen").insertAdjacentHTML("beforeend", `<option value="${s}">${LABEL[s]}</option>`);
$("fuel-legend").innerHTML = FUELS.map((f) => `<div><img src="assets/side_${f}.png" alt="${FUEL_LABEL[f]} truck"><span>${FUEL_LABEL[f]}</span></div>`).join("");
$("b-theme").onclick = toggleTheme;
$("s-scen").onchange = (e) => setScenario(e.target.value);
$("s-dur").onchange = (e) => { duration = +e.target.value; };
$("b-play").onclick = () => { if (!tour && played >= duration) played = 0; playing = !playing; };
$("b-tour").onclick = startTour;
$("seek").oninput = (e) => { const f = e.target.value / 1000; tour = null; played = f * duration; };
window.addEventListener("keydown", (e) => {
  if (e.key === " ") { if (!tour && played >= duration) played = 0; playing = !playing; e.preventDefault(); }
  else if (e.key === "ArrowRight") played = Math.min(duration, played + duration * 0.05);
  else if (e.key === "ArrowLeft") { played = Math.max(0, Math.min(duration, played) - duration * 0.05); }
  else if (e.key >= "1" && e.key <= "4" && scenarios[+e.key - 1]) setScenario(scenarios[+e.key - 1]);
  else if (e.key === "t" || e.key === "T") startTour();
  else if (e.key === "r" || e.key === "R") { played = 0; playing = true; }
  else if (e.key === "d" || e.key === "D") toggleTheme();
  else if (e.key === "+" || e.key === "=") zoomAt(W / 2, H / 2, 1.5);
  else if (e.key === "-") zoomAt(W / 2, H / 2, 1 / 1.5);
  else if (e.key === "0") resetView();
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
  if (params.get("tour") === "1" || params.get("tour") === "full") startTour();
  if (params.get("at")) played = Math.min(1.02, Math.max(0, +params.get("at"))) * duration;  // ?at=0.5: start halfway
  if (params.get("pause") === "1") playing = false;
  if (params.get("zoom")) zoomAt(W / 2, H / 2, +params.get("zoom"));   // ?zoom=3: start zoomed in at the centre
  requestAnimationFrame(frame);
}
