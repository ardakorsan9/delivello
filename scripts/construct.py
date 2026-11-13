"""Build a plan with regret insertion, check it with the exact simulator, archive it.

Usage:  uv run python scripts/construct.py scenario_small [scenario_middle ...]
Never sends anything to the API.
"""
import sys
import time

from nos.construct import regret_insertion
from nos.data import load_scenario
from nos.evaluate import Model
from nos.plans import archive
from nos.simulator import simulate


def main() -> None:
    for sid in sys.argv[1:] or ["scenario_small", "scenario_middle", "scenario_big"]:
        sc = load_scenario(sid)
        m = Model(sc)
        t0 = time.perf_counter()
        tw = [o for o in range(m.n_orders) if m.o_tw[o][0] or m.o_tw[o][1]]
        rest = [o for o in range(m.n_orders) if o not in tw]
        runs = []
        for k in (2, 3):
            runs.append((f"regret{k}", regret_insertion(m, k=k)))
            ins = regret_insertion(m, k=k, orders=tw)
            runs.append((f"regret{k}_twfirst", regret_insertion(m, k=k, orders=rest, ins=ins)))
        for name, ins in runs:
            print(f"   {name:16s} {ins.score():7.2f}")
        name, ins = max(runs, key=lambda r: r[1].score())
        dt = time.perf_counter() - t0
        plan = m.to_plan(ins.routes)
        res = simulate(sc, plan)
        b = res.breakdown
        print(f"{sid:16s} {name} score={res.score:7.2f} (fast={ins.score():7.2f}) {dt:5.1f}s "
              f"orders={res.simulate['orders_fulfilled']}/{res.simulate['orders_total']} "
              f"trucks={len(plan)} fulfil={b['fulfillment']} cost={b['cost_efficiency']} "
              f"loaded={b['loaded_ratio']} co2={b['co2_efficiency']} viol={len(res.violations)}")
        new_best = archive(plan, sid, res.score, fingerprint=sc.fingerprint, source=name,
                           valid=not res.violations)
        if new_best:
            print(f"{'':16s} -> new best in results/{sid}/best.json")


if __name__ == "__main__":
    main()
