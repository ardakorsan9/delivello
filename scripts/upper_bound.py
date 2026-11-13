"""Lagrangian upper bound on the score, with independent cross-checks (offline).

For each scenario:
- Lagrangian dual bound on the window value, min_mu L(mu)          (nos.lagrange)
- the LP relaxation of the same packing model solved by GLOP        (must equal the dual bound:
  every truck subproblem has the integrality property, so the Lagrangian dual = LP bound)
- the integer optimum by CP-SAT                                     (must be <= both)
- the resulting score upper bound vs our current best score

Usage:  uv run python scripts/upper_bound.py [scenario ...] [--verbose]
"""

from __future__ import annotations

import sys

from ortools.linear_solver import pywraplp
from ortools.sat.python import cp_model

from nos.data import load_scenario
from nos.evaluate import Model
from nos.lagrange import columns, lagrangian_bound
from nos.plans import best_plan
from nos.simulator import simulate

ALL = ["scenario_middle", "scenario_big", "scenario_competitive"]


def lp_and_ip(m: Model, cols, W):
    lp = pywraplp.Solver.CreateSolver("GLOP")
    x = [lp.NumVar(0, 1, f"x{k}") for k in range(len(cols))]
    for t in range(m.n_trucks):
        lp.Add(sum(x[k] for k, c in enumerate(cols) if c[0] == t) <= 1)
    for u in W:
        lp.Add(sum(x[k] for k, c in enumerate(cols) if u in c[1]) <= 1)
    lp.Maximize(sum(c[2] * x[k] for k, c in enumerate(cols)))
    lp.Solve()
    lp_val = lp.Objective().Value()

    ip = cp_model.CpModel()
    y = [ip.NewBoolVar(f"y{k}") for k in range(len(cols))]
    for t in range(m.n_trucks):
        ip.Add(sum(y[k] for k, c in enumerate(cols) if c[0] == t) <= 1)
    for u in W:
        ip.Add(sum(y[k] for k, c in enumerate(cols) if u in c[1]) <= 1)
    ip.Maximize(sum(int(round(c[2] * 1000)) * y[k] for k, c in enumerate(cols)))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 60
    status = s.Solve(ip)
    return lp_val, s.ObjectiveValue() / 1000, s.StatusName(status)


def main() -> None:
    verbose = "--verbose" in sys.argv
    for sid in [a for a in sys.argv[1:] if not a.startswith("--")] or ALL:
        sc = load_scenario(sid)
        m = Model(sc)
        b = lagrangian_bound(m, verbose=verbose)
        W, cols, _ = columns(m)
        lp_val, ip_val, ip_status = lp_and_ip(m, cols, W)
        bp = best_plan(sid)
        cur = simulate(sc, bp["plan"]).score if bp else float("nan")
        print(f"\n{sid}: {len(W)} window orders, {b.columns} feasible window sets "
              f"(enumeration {'complete' if b.complete else 'TRUNCATED'})")
        print(f"  Lagrangian dual   min L(mu) = {b.window_value_ub:.4f}   ({b.iterations} subgradient steps)")
        print(f"  LP relaxation     (GLOP)    = {lp_val:.4f}   -> dual - LP = {b.window_value_ub - lp_val:+.4f}")
        print(f"  integer optimum   (CP-SAT)  = {ip_val:.4f}   [{ip_status}], greedy primal {b.window_value_lb:.4f}")
        print(f"  value: windowless {b.nonwindow_value:.1f} + window <= {b.window_value_ub:.3f} "
              f"of total {b.value_total:.1f} -> fulfillment <= {b.fulfillment_ub:.3f}%")
        print(f"  SCORE UPPER BOUND = {b.score_ub:.2f}   our best = {cur:.2f}   gap = {b.score_ub - cur:.2f} points")
        assert b.window_value_ub >= ip_val - 1e-6 and b.score_ub >= cur - 1e-6, "bound violated"


if __name__ == "__main__":
    main()
