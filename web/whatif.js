// NOS what-if add-on: a truck breaks down mid-plan and NOS replans (data: scripts/disruption.py).
// Loaded after player.js on whatif.html; it only reads the player's state and draws on its own layer,
// so index.html / player.js are unchanged. URL: whatif.html?case=1..4 (plus the player's own options).
"use strict";

const WF = window.NOS_WHATIF;
const WIDX = window.NOS_WHATIF_INDEX || [];
const PAUSE_S = 2.8;                       // the plan stops at the breakdown while NOS replans
const wcanvas = document.getElementById("wf-layer");
const wctx = wcanvas.getContext("2d");
// wLastT starts at the player's start position, so even a long first frame (slow load) still
// counts as running into the breakdown
let wPaused = false, wShownAt = null, wDone = false, wLastT = (Math.min(1, played / duration)) * S.horizon;

// rescue cargo waiting in the breakdown city until a helper truck collects it
const rescuePick = [];
for (const t of S.d.trucks) for (const s of t.stops)
  if (s.action === "pickup" && WF.onboard.includes(s.order)) rescuePick.push({ t: s.departure_min, truck: t.id });
const helperSet = new Set(WF.helpers);

function clock(min) {
  const day = 1 + Math.floor((min + 360) / 1440), mm = Math.floor(min + 360) % 1440;
  return `Day ${day}, ${String(Math.floor(mm / 60)).padStart(2, "0")}:${String(mm % 60).padStart(2, "0")}`;
}

// ---- side panel: planned vs no reaction vs NOS replan
function compareCard() {
  const rows = [["Planned (no breakdown)", WF.score_planned, "plan"], ["No reaction", WF.score_no_reaction, "bad"],
                ["Delivello replan", WF.score_nos, "good"]];
  const lo = 850, hi = 940, pct = (v) => Math.max(2, 100 * (v - lo) / (hi - lo));
  document.getElementById("wf-compare").innerHTML = rows.map(([n, v, c]) =>
    `<div class="wf-row ${c}"><span>${n}</span><div><i style="width:${pct(v)}%"></i></div><b>${v.toFixed(2)}</b></div>`).join("") +
    `<p class="note">${WF.saved} of ${WF.onboard.length + WF.waiting.length} affected orders saved · replanned in ${WF.replan_seconds} s · ` +
    `${WF.orders_nos} vs ${WF.orders_no_reaction} orders delivered</p>`;
}

function banner(stage) {
  const b = document.getElementById("wf-banner");
  if (stage === 0) { b.className = "hidden"; return; }
  const n = WF.onboard.length + WF.waiting.length;
  b.className = stage === 1 ? "alert" : "ok";
  document.getElementById("wf-title").textContent = stage === 1
    ? `⚠ ${WF.kind}: ${WF.truck} stopped in ${WF.city_name}`
    : `✓ Delivello replanned in ${WF.replan_seconds} s`;
  document.getElementById("wf-sub").textContent = stage === 1
    ? `${clock(WF.t)} · ${WF.onboard.length} orders on board, ${WF.waiting.length} waiting · replanning…`
    : `${WF.saved} / ${n} orders saved by ${WF.helpers.length} trucks (${WF.helpers.join(", ")})` +
      (WF.lost.length ? ` · ${WF.lost.length} cannot be saved in time` : "");
}

// ---- map layer
function wResize() {                       // the layer copies the map canvas's exact box and resolution
  const r = canvas.getBoundingClientRect(), p = canvas.offsetParent.getBoundingClientRect();
  Object.assign(wcanvas.style, { left: `${r.left - p.left}px`, top: `${r.top - p.top}px`,
                                 width: `${r.width}px`, height: `${r.height}px` });
  if (wcanvas.width !== canvas.width || wcanvas.height !== canvas.height) {
    wcanvas.width = canvas.width; wcanvas.height = canvas.height;
  }
}

function wDraw(t, now) {
  wResize();
  wctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  wctx.clearRect(0, 0, W, H);
  if (t < WF.t) return;
  const city = S.city[WF.city].xy, pulse = 0.5 + 0.5 * Math.sin(now / 180);
  // broken truck: red pulsing ring and a cross
  wctx.strokeStyle = `rgba(229, 57, 53, ${0.55 + 0.45 * pulse})`; wctx.lineWidth = 4;
  wctx.beginPath(); wctx.arc(city[0], city[1], 26 + 6 * pulse, 0, 7); wctx.stroke();
  wctx.fillStyle = "#e53935"; wctx.font = "bold 22px Montserrat, system-ui"; wctx.textAlign = "center"; wctx.textBaseline = "middle";
  wctx.fillText("⚠", city[0], city[1] - 44);
  // cargo still waiting in the breakdown city
  const waiting = rescuePick.filter((p) => p.t > t).length;
  if (waiting) {
    wctx.fillStyle = "#e53935"; wctx.font = "bold 13px Montserrat, system-ui";
    wctx.fillText(`${waiting} order${waiting > 1 ? "s" : ""} waiting for pickup`, city[0], city[1] + 44);
  }
  // helper trucks: amber rings for a while after the replan
  if (t < WF.t + 0.25 * S.horizon) {
    const a = 1 - (t - WF.t) / (0.25 * S.horizon);
    wctx.strokeStyle = `rgba(255, 179, 0, ${a})`; wctx.lineWidth = 3;
    for (const tr of S.trucks) {
      if (!helperSet.has(tr.id)) continue;
      const st = stateAt(S, tr, t);
      wctx.beginPath(); wctx.arc(st.xy[0], st.xy[1], 20, 0, 7); wctx.stroke();
    }
  }
}

// ---- the breakdown moment: stop the clock, alert, then show the replan and continue
function wFrame(now) {
  if (S && S.d) {
    const frac = Math.min(1, played / duration), t = frac * S.horizon;
    const crossed = wLastT !== null && wLastT < WF.t && t >= WF.t;   // only when playback runs into it
    wLastT = t;
    if (!wDone && crossed && playing) {
      wDone = true; wPaused = true; playing = false;
      played = (WF.t / S.horizon) * duration;          // hold exactly at the breakdown
      wShownAt = now; banner(1);
    }
    if (wPaused && now - wShownAt > PAUSE_S * 1000 * 0.45) banner(2);
    if (wPaused && now - wShownAt > PAUSE_S * 1000) { wPaused = false; playing = true; }
    if (t < WF.t - 1) { if (wDone && !wPaused) { wDone = false; banner(0); } }   // seeked back: arm again
    if (!wPaused && wDone && t > WF.t + 0.3 * S.horizon) banner(0);
    wDraw(Math.min(t, S.horizon), now);
  }
  requestAnimationFrame(wFrame);
}

// ---- controls: Emergency = jump to 2 s before the breakdown and play
document.getElementById("b-emergency").onclick = () => {
  played = Math.max(0, (WF.t / S.horizon) * duration - 2); wDone = false; banner(0); playing = true;
};
const sel = document.getElementById("s-case");
sel.innerHTML = WIDX.map((c) => `<option value="${c.n}">${c.truck} · ${c.city} · day ${c.day}</option>`).join("");
sel.value = String(new URLSearchParams(location.search).get("case") || 1);
sel.onchange = (e) => { const p = new URLSearchParams(location.search); p.set("case", e.target.value); location.search = p.toString(); };

document.getElementById("wf-label").textContent = `${WF.kind} · ${WF.label}`;
compareCard();

// ---- intro card: shown for INTRO_S seconds when the page starts at the beginning, plan held meanwhile
const INTRO_S = 4.5;
(function intro() {
  if (played > 0.5) return;                       // started mid-plan (?at=...): no intro
  const n = WF.onboard.length + WF.waiting.length;
  document.getElementById("wf-i-eyebrow").textContent = "Emergency scenario · Competitive · 25 trucks · 200 orders";
  document.getElementById("wf-i-title").textContent = "What if a truck breaks down?";
  document.getElementById("wf-i-sub").textContent =
    `On day ${WF.day}, truck ${WF.truck} stops in ${WF.city_name} with ${WF.onboard.length} orders on board ` +
    `and ${WF.waiting.length} more still to collect. Watch Delivello replan the rest of the fleet in seconds ` +
    (WF.saved === n ? `and save all ${n} orders.` : `and save ${WF.saved} of these ${n} orders.`);
  document.getElementById("wf-i-note").textContent =
    "Realistic scenario, not a recorded incident. Everything before the breakdown stays as it happened.";
  const box = document.getElementById("wf-intro");
  box.classList.remove("hidden");
  const wasPlaying = playing;
  playing = false;
  setTimeout(() => { box.classList.add("hidden"); playing = wasPlaying || true; }, INTRO_S * 1000);
})();
wResize();
window.addEventListener("resize", () => setTimeout(wResize, 0));
requestAnimationFrame(wFrame);
