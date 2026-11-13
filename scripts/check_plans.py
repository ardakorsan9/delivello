"""Check every stored best plan against all GRUBER rules, offline (no API calls).

For each scenario with results/<scenario>/best.json:
- the plan belongs to the current data (fingerprint)
- the exact simulator reports 0 violations (all 10 rule codes of the docs)
- independent re-checks: valid ids/actions, one truck per order, pickup before
  delivery, every pickup delivered, capacity at every moment, truck type, and no
  stop more than 60 min late (otherwise the order is lost)
- score and how far it is from the Lagrangian upper bound (lagrange.py)

Usage:  uv run python scripts/check_plans.py [scenario ...]
"""

from __future__ import annotations

import sys

from nos.lagrange import lagrangian_bound
from nos.data import load_scenario
from nos.evaluate import Model
from nos.plans import best_plan
from nos.simulator import simulate

ALL = ["scenario_small", "scenario_middle", "scenario_big", "scenario_competitive"]


def independent_checks(sc, plan) -> list[str]:
    errs = []
    seen: dict[str, str] = {}
    for tid, stops in plan.items():
        truck = sc.trucks.get(tid)
        if truck is None:
            errs.append(f"unknown truck {tid}")
            continue
        load, picked, done = 0, set(), set()
        for s in stops:
            o = sc.orders.get(s.get("order"))
            if o is None or s.get("action") not in ("pickup", "delivery"):
                errs.append(f"{tid}: bad stop {s}")
                continue
            if seen.setdefault(o.id, tid) != tid:
                errs.append(f"{o.id} on {seen[o.id]} and {tid}")
            if o.required_truck_type and o.required_truck_type != truck.type:
                errs.append(f"{o.id} needs {o.required_truck_type}, {tid} is {truck.type}")
            if s["action"] == "pickup":
                if o.id in picked:
                    errs.append(f"{o.id} picked twice")
                picked.add(o.id)
                load += o.weight_kg
                if load > truck.capacity_kg:
                    errs.append(f"{tid}: load {load} > {truck.capacity_kg} at {o.id}")
            else:
                if o.id not in picked:
                    errs.append(f"{o.id} delivered before pickup")
                if o.id in done:
                    errs.append(f"{o.id} delivered twice")
                done.add(o.id)
                load -= o.weight_kg
        for oid in picked - done:
            errs.append(f"{oid} picked but not delivered")
    return errs


def main() -> int:
    bad = 0
    for sid in sys.argv[1:] or ALL:
        sc = load_scenario(sid)
        b = best_plan(sid)
        if not b:
            print(f"{sid}: no best.json")
            continue
        plan = b["plan"]
        fp_ok = b["meta"].get("fingerprint") == sc.fingerprint
        res = simulate(sc, plan)
        errs = independent_checks(sc, plan)
        late = [(s["order"], s["late_min"]) for t in res.trucks for s in t["schedule"] if s["late_min"] > 60]
        bound = lagrangian_bound(Model(sc))
        s = res.simulate
        ok = fp_ok and not res.violations and not errs and not late
        bad += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {sid}: score {res.score:.2f}  orders {s['orders_fulfilled']}/{s['orders_total']}  "
              f"trucks used {len(plan)}  violations {len(res.violations)}  late>60 {len(late)}  "
              f"data {'current' if fp_ok else 'STALE'}")
        print(f"      score upper bound {bound.score_ub:.2f} (gap {bound.score_ub - res.score:.2f})  "
              f"fulfillment {res.breakdown['fulfillment']} (upper bound {bound.fulfillment_ub:.2f})  "
              f"cost {res.breakdown['cost_efficiency']}  loaded {res.breakdown['loaded_ratio']}  "
              f"co2 {res.breakdown['co2_efficiency']}  late_penalty {res.breakdown['late_penalty']}")
        for e in (errs + [f"late {o} {mn} min" for o, mn in late])[:10]:
            print("      ! " + e)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
