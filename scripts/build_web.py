"""Package data for the offline demo player in web/ (open web/index.html directly, no server).

  uv run python scripts/build_web.py                      # scenario data from results/*/dashboard.json
  uv run python scripts/build_web.py --basemap ne.geojson # (once) Europe outline from Natural Earth

Writes web/data/<scenario>.js (window.NOS_DATA[...] = dashboard) and, with
--basemap, web/data/europe.js (simplified country rings, public-domain Natural Earth 1:50m).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "data"
SCENARIOS = ["scenario_small", "scenario_middle", "scenario_big", "scenario_competitive"]
BBOX = (-25.0, 33.0, 50.0, 72.0)  # lon_min, lat_min, lon_max, lat_max


def simplify(ring, tol=0.04):
    out = [ring[0]]
    for p in ring[1:]:
        if abs(p[0] - out[-1][0]) > tol or abs(p[1] - out[-1][1]) > tol:
            out.append(p)
    return [[round(x, 2), round(y, 2)] for x, y in out]


def basemap(path: Path) -> None:
    gj = json.loads(path.read_text())
    rings = []
    for f in gj["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            ring = poly[0]  # outer ring only; holes are irrelevant at this scale
            xs, ys = [p[0] for p in ring], [p[1] for p in ring]
            if max(xs) < BBOX[0] or min(xs) > BBOX[2] or max(ys) < BBOX[1] or min(ys) > BBOX[3]:
                continue
            r = simplify(ring)
            if len(r) >= 4:
                rings.append(r)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "europe.js").write_text("window.NOS_EUROPE=" + json.dumps(rings, separators=(",", ":")) + ";\n")
    print(f"europe.js: {len(rings)} rings, {(OUT / 'europe.js').stat().st_size / 1024:.0f} KB")


def scenarios() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for sid in SCENARIOS:
        f = ROOT / "results" / sid / "dashboard.json"
        if not f.exists():
            print(f"{sid}: no dashboard.json (run scripts/export_dashboard.py)")
            continue
        js = f"window.NOS_DATA=window.NOS_DATA||{{}};window.NOS_DATA[{json.dumps(sid)}]={f.read_text()};\n"
        (OUT / f"{sid}.js").write_text(js)
        print(f"{sid}.js: {len(js) / 1024:.0f} KB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--basemap", type=Path, help="Natural Earth admin-0 countries GeoJSON")
    a = ap.parse_args()
    if a.basemap:
        basemap(a.basemap)
    scenarios()


if __name__ == "__main__":
    main()
