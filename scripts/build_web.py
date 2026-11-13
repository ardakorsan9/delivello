"""Package data for the offline demo player in web/ (open web/index.html directly, no server).

  uv run python scripts/build_web.py                      # scenario data from results/*/dashboard.json
  uv run python scripts/build_web.py --basemap ne.geojson # (once) Europe outline from Natural Earth
  uv run python scripts/build_web.py --roads              # road geometry for every driven city pair

Writes web/data/<scenario>.js (window.NOS_DATA[...] = dashboard) and, with
--basemap, web/data/europe.js (simplified country rings, public-domain Natural Earth 1:50m).
With --roads, web/data/roads.js: the road geometry of every city pair the plans drive,
fetched once from the public OSRM demo server (1 request/s, only city coordinates are
sent) and cached in web/data/roads_cache.json. Map data (c) OpenStreetMap contributors.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
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


OSRM = "https://router.project-osrm.org/route/v1/driving/{},{};{},{}?overview=simplified&geometries=geojson"


def roads() -> None:
    cities, pairs = {}, set()
    for sid in SCENARIOS:
        f = ROOT / "results" / sid / "dashboard.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        cities.update({c["id"]: (c["lon"], c["lat"]) for c in d["cities"]})
        for t in d["trucks"]:
            for g in t["timeline"]:
                if g["kind"] == "drive":
                    pairs.add(tuple(sorted((g["from"], g["to"]))))
    cache_f = OUT / "roads_cache.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    todo = [p for p in sorted(pairs) if "|".join(p) not in cache]
    print(f"roads: {len(pairs)} pairs, {len(todo)} to fetch (~{len(todo)} s)")
    for k, (a, b) in enumerate(todo):
        url = OSRM.format(*cities[a], *cities[b])
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nos-demo/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.loads(r.read())
            coords = res["routes"][0]["geometry"]["coordinates"] if res.get("code") == "Ok" else None
        except Exception as e:  # network hiccup: keep going, the pair falls back to a straight line
            print(f"  {a}-{b}: {e}")
            coords = None
        if coords:
            cache["|".join((a, b))] = [[round(x, 3), round(y, 3)] for x, y in coords]
        if k % 25 == 0:
            cache_f.write_text(json.dumps(cache, separators=(",", ":")))
            print(f"  {k}/{len(todo)}", flush=True)
        time.sleep(1.0)
    cache_f.write_text(json.dumps(cache, separators=(",", ":")))
    used = {k: v for k, v in cache.items() if tuple(k.split("|")) in pairs}
    (OUT / "roads.js").write_text("window.NOS_ROADS=" + json.dumps(used, separators=(",", ":")) + ";\n")
    print(f"roads.js: {len(used)}/{len(pairs)} pairs with road geometry, "
          f"{(OUT / 'roads.js').stat().st_size / 1024:.0f} KB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--basemap", type=Path, help="Natural Earth admin-0 countries GeoJSON")
    ap.add_argument("--roads", action="store_true", help="fetch/refresh road geometry (OSRM)")
    a = ap.parse_args()
    if a.basemap:
        basemap(a.basemap)
    if a.roads:
        roads()
    scenarios()


if __name__ == "__main__":
    main()
