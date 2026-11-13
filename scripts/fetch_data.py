"""Download every scenario from the GRUBER API into data/<scenario>/.

The server regenerates all scenarios on restart, so each download stores a
fingerprint (hash of orders + trucks). If the fingerprint changes, the server
was restarted and any saved plans are no longer valid.

Usage:  uv run python scripts/fetch_data.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from nos.api import GruberAPI

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def fingerprint(*parts) -> str:
    blob = json.dumps(parts, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def main() -> None:
    api = GruberAPI()
    scenarios = api.scenarios()
    print(f"{len(scenarios)} scenarios on the server\n")

    for s in scenarios:
        sid = s["id"]
        out = DATA_DIR / sid
        out.mkdir(parents=True, exist_ok=True)

        data = {
            "cities": api.cities(sid),
            "trucks": api.trucks(sid),
            "orders": api.orders(sid),
            "distance_matrix": api.distance_matrix(sid),
            "sample_plan": api.sample_plan(sid),
        }
        fp = fingerprint(data["orders"], data["trucks"])

        old_meta = out / "meta.json"
        if old_meta.exists():
            old_fp = json.loads(old_meta.read_text()).get("fingerprint")
            if old_fp != fp:
                print(f"  !! {sid}: data changed since last download (server restart?)")

        for name, content in data.items():
            (out / f"{name}.json").write_text(json.dumps(content, indent=1))
        meta = {
            "scenario": s,
            "fingerprint": fp,
            "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (out / "meta.json").write_text(json.dumps(meta, indent=1))

        n_tw = sum(1 for o in data["orders"] if o.get("pickup_window") or o.get("delivery_window"))
        print(f"  {sid:22s} cities={len(data['cities']):3d} trucks={len(data['trucks']):3d} "
              f"orders={len(data['orders']):4d} time_windows={n_tw:3d}  fp={fp}")

    print(f"\nSaved to {DATA_DIR}")


if __name__ == "__main__":
    main()
