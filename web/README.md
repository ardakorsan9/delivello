# NOS dispatch replay (demo video)

An offline player for the final plans: map, moving trucks, a red cargo box while loaded, breaks
and rests, and KPIs. No server and no internet are needed.

## Build the data (after any new best plan)
```bash
uv run python scripts/export_dashboard.py scenario_small scenario_middle scenario_big scenario_competitive
uv run python scripts/build_web.py
```

## Open
Double-click `web/index.html`. From Windows, open
`\\wsl.localhost\Ubuntu-24.04\home\ardak\projects\nos\web\index.html`.

URL options (append to the address):
| Option | Effect |
|---|---|
| `?tour=1` | all four scenarios, 2:00 in total (18 + 22 + 35 + 45 s) |
| `?scenario=scenario_big&duration=45` | one scenario, played in 45 s |
| `&clean=1` | hide the control bar (for recording) |

Keys: Space play/pause · ←/→ seek · 1–4 scenario · T tour · R restart · H hide controls.

## Record 2 minutes
1. Open `index.html?tour=1&clean=1` in Chrome and press F11 for full screen (1920×1080).
2. Start the recording (Windows: `Win + Alt + R`, or OBS), then press R to restart the tour.
3. Stop after 2:00. Save the video under `~/veri` (E: drive), not in the repo.

## Designer assets
Replace the files in `web/assets/` and keep the same names:
- `truck_standard.svg`, `truck_refrigerated.svg`, `truck_hazmat.svg`: top view, **nose pointing right**,
  about 2:1 aspect ratio. The player rotates them along the route.
- `cargo.svg`: the red delivery box drawn behind a loaded truck (square).

PNG files work too: change the extension in `player.js` (`assets/truck_${n}.svg`). Colours are the
CSS variables at the top of `style.css`.
