"""Improve a scenario's plan with ALNS, verify it with the exact simulator, archive it.

Starts from results/<scenario>/best.json when it belongs to the current data
(same fingerprint), otherwise from regret insertion. Only a better valid plan
replaces best.json, so a run can never make the stored result worse.
Writes the search history to results/<scenario>/alns_history.json (dashboard).
Never sends anything to the API.

Usage:  uv run python scripts/optimize.py scenario_big --seconds 300 [--seed 1] [--fresh]
"""

from __future__ import annotations

import argparse
import json

from nos.alns import ALNS
from nos.construct import Insertion, regret_insertion
from nos.data import load_scenario
from nos.evaluate import Model
from nos.plans import RESULTS_DIR, archive, best_plan
from nos.polish import set_partition
from nos.simulator import simulate


def load_pool(path, fingerprint, n_trucks):
    pool = {t: set() for t in range(n_trucks)}
    if path.exists():
        d = json.loads(path.read_text())
        if d.get("fingerprint") == fingerprint:
            for t, rs in d["pool"].items():
                pool[int(t)] |= {tuple((o, bool(p)) for o, p in r) for r in rs}
    return pool


def save_pool(path, fingerprint, pool):
    path.write_text(json.dumps({"fingerprint": fingerprint,
                                "pool": {t: [list(map(list, r)) for r in rs] for t, rs in pool.items()}}))


def routes_from_plan(m: Model, plan: dict) -> list:
    oi = {o: k for k, o in enumerate(m.order_ids)}
    routes = [[] for _ in range(m.n_trucks)]
    for tid, stops in plan.items():
        t = m.truck_ids.index(tid)
        routes[t] = [(oi[s["order"]], s["action"] == "pickup") for s in stops]
    return routes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--topn", type=int, default=12)
    ap.add_argument("--fresh", action="store_true", help="ignore best.json, start from construction")
    ap.add_argument("--no-polish", action="store_true", help="skip the set-partitioning polish")
    a = ap.parse_args()

    sc = load_scenario(a.scenario)
    m = Model(sc)
    stored = best_plan(a.scenario)
    if stored and not a.fresh and stored["meta"].get("fingerprint") == sc.fingerprint:
        start = Insertion(m, routes_from_plan(m, stored["plan"]))
        src = f"best.json ({stored['meta']['score']})"
    else:
        start = max((regret_insertion(m, k=k) for k in (2, 3)), key=lambda s: s.score())
        src = "regret insertion"
    print(f"{a.scenario}: start {start.score():.2f} from {src}, "
          f"{len(start.assigned())}/{m.n_orders} orders, {a.seconds:.0f}s, seed {a.seed}")

    res = ALNS(m, seed=a.seed, topn=a.topn).run(start, time_limit=a.seconds) if a.seconds > 0 else None
    final = res.best if res else start
    pool_file = RESULTS_DIR / a.scenario / "route_pool.json"
    pool = load_pool(pool_file, sc.fingerprint, m.n_trucks)
    if res:
        for t, rs in res.pool.items():
            pool[t] |= rs
        save_pool(pool_file, sc.fingerprint, pool)
    if not a.no_polish:
        print("\nset partitioning polish:")
        final = set_partition(m, pool, final)
    plan = m.to_plan(final.routes)
    sim = simulate(sc, plan)
    b = sim.breakdown
    print(f"\nresult {sim.score:.2f} (fast {final.score():.2f}), {res.iterations if res else 0} iterations, "
          f"orders {sim.simulate['orders_fulfilled']}/{m.n_orders}, violations {len(sim.violations)}")
    print(f"  fulfillment {b['fulfillment']}  cost {b['cost_efficiency']}  loaded {b['loaded_ratio']}  "
          f"co2 {b['co2_efficiency']}  late_penalty {b['late_penalty']}")
    if res:
        print("  operators:", {k: v for k, v in res.op_stats["stats"].items()})
    if archive(plan, a.scenario, sim.score, fingerprint=sc.fingerprint, source=f"alns_s{a.seed}",
               valid=not sim.violations, extra={"iterations": res.iterations if res else 0,
                                                "seconds": a.seconds}):
        print(f"  -> new best in results/{a.scenario}/best.json")
    if not res:
        return
    out = RESULTS_DIR / a.scenario / "alns_history.json"
    out.write_text(json.dumps({"seed": a.seed, "start": start.score(), "history": res.history[::max(1, len(res.history) // 2000)]}))


if __name__ == "__main__":
    main()
