"""Collect reference API responses for simulator tests.

Builds a few probe plans on the unlimited scenarios (small, middle, big), sends
each to Simulate and Score, and stores scenario data + plan + responses in
tests/fixtures/<scenario>/<probe>.json. A local simulator must reproduce these.

Never touches scenario_competitive.

Usage:  uv run python scripts/collect_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

from nos.api import GruberAPI
from nos.data import DATA_DIR

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
SCENARIOS = ["scenario_small", "scenario_middle", "scenario_big"]


def compatible(order, truck) -> bool:
    req = order.get("required_truck_type")
    return (req is None or req == truck["type"]) and order["weight_kg"] <= truck["capacity_kg"]


def probes(trucks, orders, sample):
    t0 = trucks[0]
    own = [o for o in orders if compatible(o, t0)]

    # 1. organizer sample plan
    yield "sample", sample

    # 2. one truck, every compatible order one after another (long route: breaks, rests, lateness)
    yield "single_truck_sequential", {t0["id"]: [s for o in own for s in (
        {"action": "pickup", "order": o["id"]}, {"action": "delivery", "order": o["id"]})]}

    # 3. consolidation: pick up 3 orders, then deliver them (load changes, loaded/empty km)
    cons, load = [], 0
    for o in own:
        if load + o["weight_kg"] <= t0["capacity_kg"] and len(cons) < 3:
            cons.append(o)
            load += o["weight_kg"]
    yield "consolidation", {t0["id"]: [{"action": "pickup", "order": o["id"]} for o in cons]
                            + [{"action": "delivery", "order": o["id"]} for o in reversed(cons)]}

    # 4. round robin over all trucks, compatible orders only
    rr = {t["id"]: [] for t in trucks}
    for i, o in enumerate(orders):
        for k in range(len(trucks)):
            t = trucks[(i + k) % len(trucks)]
            if compatible(o, t):
                rr[t["id"]] += [{"action": "pickup", "order": o["id"]},
                                {"action": "delivery", "order": o["id"]}]
                break
    yield "round_robin_all", rr

    # 5. deliberate violations: delivery before pickup, duplicate, wrong type, capacity
    bad = [{"action": "delivery", "order": orders[0]["id"]},
           {"action": "pickup", "order": orders[0]["id"]},
           {"action": "pickup", "order": orders[1]["id"]},
           {"action": "pickup", "order": orders[1]["id"]},
           {"action": "delivery", "order": orders[1]["id"]}]
    wrong = next((o for o in orders if o.get("required_truck_type")
                  and o["required_truck_type"] != t0["type"]), None)
    if wrong:
        bad += [{"action": "pickup", "order": wrong["id"]}, {"action": "delivery", "order": wrong["id"]}]
    heavy = sorted(orders, key=lambda o: -o["weight_kg"])
    heavy_ok = [o for o in heavy if o.get("required_truck_type") in (None, t0["type"])][:4]
    bad += [{"action": "pickup", "order": o["id"]} for o in heavy_ok]
    bad += [{"action": "delivery", "order": o["id"]} for o in heavy_ok]
    bad += [{"action": "pickup", "order": "O999"}, {"action": "fly", "order": orders[2]["id"]}]
    yield "violations", {t0["id"]: bad, "T99": []}


def main() -> None:
    api = GruberAPI()
    for sid in SCENARIOS:
        folder = DATA_DIR / sid
        scen = {n: json.loads((folder / f"{n}.json").read_text())
                for n in ["cities", "trucks", "orders", "distance_matrix", "sample_plan"]}
        meta = json.loads((folder / "meta.json").read_text())
        out_dir = FIXTURES / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "scenario.json").write_text(json.dumps({**scen, "meta": meta}))
        for name, plan in probes(scen["trucks"], scen["orders"], scen["sample_plan"]):
            sim = api.simulate(sid, plan)
            score = api.score(sid, plan)
            (out_dir / f"{name}.json").write_text(json.dumps(
                {"plan": plan, "simulate": sim, "score": score}, indent=1))
            print(f"{sid:16s} {name:24s} score={score['score']:8.2f} "
                  f"violations={len(score['validation']['violations'])}")


if __name__ == "__main__":
    main()
