# Delivello dispatch replay (demo video)

An offline player for the final plans: map, trucks driving along the real roads, a short fading
trail, breaks and rests, and KPIs. No server and no internet are needed.

Everything is computed from the plan at the current minute: the score is the official formula on
what has happened so far (value delivered, km, loaded km, cost, CO2), so it reaches the final score
exactly when the last truck finishes. The side panel shows the four score parts and the share of the
proven ceiling; the results card ("Every delivery. A clearer picture.") shows at the end.
Light theme by default; `?theme=dark` or the D key switches to the dark green theme.

## Build the data (after any new best plan)
```bash
uv run python scripts/export_dashboard.py scenario_small scenario_middle scenario_big scenario_competitive
uv run python scripts/build_web.py
```
If the plans now drive a city pair that has no road geometry yet, run
`uv run python scripts/build_web.py --roads`. It fetches only the missing pairs from OSRM (1 per
second) and caches them in `web/data/roads_cache.json`. Pairs without geometry are drawn as
straight lines.

## Open
Double-click `web/index.html`. From Windows, open
`\\wsl.localhost\Ubuntu-24.04\home\ardak\projects\nos\web\index.html`.

URL options (append to the address):
| Option | Effect |
|---|---|
| `?tour=1` | demo tour, 1:10: Competitive only (leaves 50 s for the emergency video) |
| `?tour=full` | all four scenarios, 2:00 in total (18 + 22 + 35 + 45 s) |
| `?scenario=scenario_big&duration=45` | one scenario, played in 45 s |
| `&clean=1` | hide the control bar (for recording) |
| `&fps=1` | show the frame rate in the top-right corner (should be ~60) |
| `&at=0.5` | start at that fraction of the timeline (`&at=1.02` = results card) |
| `&pause=1` | start paused |
| `&theme=light` | light theme (dark, in the GRUBER slide colours, is the default; D switches) |

Keys: Space play/pause · ←/→ seek · 1–4 scenario · T tour · R restart · H hide controls ·
+/− zoom · 0 reset zoom. Mouse: wheel zooms at the cursor, drag moves the map, double-click resets.

## Record 2 minutes
1. Open `index.html?tour=1&clean=1` in Chrome and press F11 for full screen (1920×1080).
2. Start the recording (Windows: `Win + Alt + R`, or OBS), then press R to restart the tour.
3. Stop after 1:10 (or 2:00 with `?tour=full`). Save the video under `~/veri` (E: drive), not in the repo.

## Designer assets
`web/assets/*.png` are cut from the designer's renders (diesel / LNG / electric):
- `truck_<fuel>.png`: top view with trailer, nose right, drawn on the map while the truck is **loaded**;
- `cab_<fuel>.png`: the tractor alone (same top view), drawn while it drives **empty** (the trailer
  appears behind the cab at a pickup). The player turns them along the road;
- `side_<fuel>.png` / `tractor_<fuel>.png`: side views, drawn while the truck is stopped (stop, wait,
  break, rest, done), loaded / empty; `side_` is also the legend image. `iso_<fuel>.png`: 3/4 view, for slides.

Fuel class = the truck's `co2_per_km`: lowest third of all fleets electric, middle LNG, highest diesel.
A blue dot marks refrigerated trucks, an orange dot hazmat. Colours are the CSS variables at the top
of `style.css`.

## Emergency what-if page (`whatif.html`)
A truck breaks down mid-plan and Delivello replans the rest. Same map and player; `whatif.js` and `whatif.css`
add the alert, the breakdown marker, the helper trucks and the "planned / no reaction / Delivello replan"
comparison. `index.html` and `player.js` are not changed by it.

```bash
uv run python scripts/disruption.py scan                                  # rank candidate breakdowns
uv run python scripts/disruption.py build scenario_competitive T20:5 T02:7 T09:5 T21:5
uv run python scripts/disruption.py roads                                 # road geometry for the new legs
```
Open `whatif.html?case=1&duration=45&clean=1` (cases 1–4 = the order given to `build`). Playback stops at the
breakdown for ~3 s (red alert, then green "replanned"), then continues with the replanned plan.
`⚠ Emergency` jumps to 2 s before the breakdown. The scenarios are realistic vehicle breakdowns, not
recorded Gruber incidents; the page says so.

Rules of the model: nothing before the breakdown changes; cargo on the broken truck must be collected in
its city within 24 h; no order is picked up before dispatch knows (the breakdown minute); no truck may
finish later than the original plan. Every replanned plan is checked with the exact simulator.
