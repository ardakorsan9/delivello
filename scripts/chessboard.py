"""Solve the time-window "chessboard" exactly-ish, compare with the upper bound, archive.

Usage:  uv run python scripts/chessboard.py scenario_big [--keep 3] [--max-sets 20000]
Never sends anything to the API.
"""
import argparse

from nos.bounds import window_bound
from nos.chessboard import solve
from nos.data import load_scenario
from nos.evaluate import Model
from nos.plans import archive
from nos.simulator import simulate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--keep", type=int, default=3)
    ap.add_argument("--max-sets", type=int, default=20000)
    a = ap.parse_args()
    sc = load_scenario(a.scenario)
    m = Model(sc)
    b = window_bound(m)
    print(f"{a.scenario}: upper bound {b['max_served']}/{b['window_orders']} window orders "
          f"(pairwise conflicts {b['conflicts']})")
    r = solve(m, b["conflict_list"], keep=a.keep, max_sets=a.max_sets)
    plan = m.to_plan(r.plan.routes)
    sim = simulate(sc, plan)
    print(f"chessboard: {r.window_served}/{r.window_total} window orders, CP-SAT {r.status}, "
          f"{r.n_sets} sets, truncated trucks {[m.truck_ids[t] for t in r.truncated_trucks]}, {r.seconds:.0f}s")
    print(f"plan: score {sim.score:.2f}, orders {sim.simulate['orders_fulfilled']}/{m.n_orders}, "
          f"violations {len(sim.violations)}, breakdown {sim.breakdown}")
    proven = r.window_served >= b["max_served"] and not r.truncated_trucks
    print("window part OPTIMAL (lower bound = upper bound)" if r.window_served >= b["max_served"]
          else f"gap: {b['max_served'] - r.window_served} window orders between plan and bound",
          "" if proven or r.window_served < b["max_served"] else "(enumeration truncated)")
    if archive(plan, a.scenario, sim.score, fingerprint=sc.fingerprint, source="chessboard",
               valid=not sim.violations):
        print(f"-> new best in results/{a.scenario}/best.json")


if __name__ == "__main__":
    main()
