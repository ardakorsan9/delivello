// Truck types from the data (hazmat / refrigerated / standard): a clear badge above every special truck
// and a legend row with the counts of the current scenario. Add-on loaded after player.js (and whatif.js):
// it only wraps the player's render() and adds to the legend, nothing in player.js is changed.
"use strict";

(function () {
  const TYPE = {
    hazmat: { sym: "⚠", label: "Hazmat", bg: "#ff8f1f", fg: "#1a1200" },
    refrigerated: { sym: "❄", label: "Refrigerated", bg: "#4fb8ff", fg: "#00182b" },
  };

  // legend row: badges + counts of the scenario on screen
  const style = document.createElement("style");
  style.textContent = `
    .types { display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 2px 0 12px; font-size: 13px; color: var(--muted); }
    .types span { display: inline-flex; align-items: center; gap: 6px; }
    .types b { color: var(--text); font-weight: 600; }
    .tbadge { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px;
              border-radius: 50%; font-size: 11px; font-weight: 700; line-height: 1; }`;
  document.head.appendChild(style);
  const legend = document.querySelector("#side .legend");
  const row = document.createElement("div");
  row.className = "types";
  if (legend) legend.insertBefore(row, document.getElementById("fuel-legend"));
  let rowFor = null;
  function legendRow() {
    if (!S || rowFor === S.sid) return;
    rowFor = S.sid;
    const n = { hazmat: 0, refrigerated: 0, standard: 0 };
    for (const t of S.d.trucks) n[t.type] = (n[t.type] || 0) + 1;
    row.innerHTML = ["hazmat", "refrigerated"].map((k) =>
      `<span><i class="tbadge" style="background:${TYPE[k].bg};color:${TYPE[k].fg}">${TYPE[k].sym}</i>${TYPE[k].label} <b>${n[k]}</b></span>`)
      .join("") + `<span>Standard <b>${n.standard}</b></span>`;
  }

  // badge above each special truck, drawn on the map after the player's own frame
  function badges(t) {
    ctx.save();
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    const r = Math.max(8, S.truckSize * 0.26);
    ctx.font = `bold ${Math.round(r * 1.25)}px system-ui, "Segoe UI Symbol", sans-serif`;
    for (const tr of S.trucks) {
      const k = TYPE[tr.type];
      if (!k) continue;
      const st = stateAt(S, tr, t);
      const x = st.xy[0], y = st.xy[1] - S.truckSize * 0.45 - r;
      ctx.globalAlpha = st.kind === "parked" ? 0.35 : st.done ? 0.6 : 1;
      ctx.fillStyle = k.bg; ctx.strokeStyle = "rgba(4, 28, 40, 0.85)"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill(); ctx.stroke();
      ctx.fillStyle = k.fg; ctx.fillText(k.sym, x, y + 0.5);
    }
    ctx.restore();
  }

  const playerRender = render;
  render = function (frac) {           // eslint-disable-line no-global-assign
    playerRender(frac);
    if (!S) return;
    legendRow();
    badges(Math.min(1, Math.max(0, frac)) * S.horizon);
  };
})();
