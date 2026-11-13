"""Upper bound on fulfillment: which time-window orders can be served at all?

We bound the fulfillment through the time-window orders.

For time-window orders we build a conflict structure:
- alone[u]  : trucks that serve u on time starting empty (<= 60 min late)
- pair(u,v,t): truck t, starting empty, can serve u and v together in some
  interleaving of their 4 stops (6 orders of P/D)
Adding other stops to a route only delays the later stops (up to a small
break-credit effect, see `slack`), so if u and v conflict on t they can never
share t. CP-SAT then maximises the served window value subject to: each order on
at most one truck, conflicting pairs never on the same truck. Because only pairs
are checked, the result is an upper bound (a relaxation), not a plan.

`slack` (minutes) loosens the on-time check to keep the bound safe against the
non-monotone break rule (an extra 30-min stop can save a 45-min break).
"""

from __future__ import annotations

from itertools import combinations

from ortools.sat.python import cp_model

from .evaluate import Model
from .simulator import LATE_GRACE_MIN

INTERLEAVINGS = [  # stop orders for orders a, b (P = pickup)
    ("Pa", "Da", "Pb", "Db"), ("Pa", "Pb", "Da", "Db"), ("Pa", "Pb", "Db", "Da"),
    ("Pb", "Db", "Pa", "Da"), ("Pb", "Pa", "Db", "Da"), ("Pb", "Pa", "Da", "Db"),
]


def _ok(m: Model, t: int, stops, slack: int) -> bool:
    """On time within LATE_GRACE_MIN + slack and capacity respected."""
    return m.eval_truck(t, stops, early_exit=True, grace=LATE_GRACE_MIN + slack).ok


def window_bound(m: Model, slack: int = 0, time_limit: float = 30.0) -> dict:
    W = [o for o in range(m.n_orders) if m.o_tw[o][0] or m.o_tw[o][1]]
    alone = {u: [t for t in range(m.n_trucks) if m.can[u][t]
                 and _ok(m, t, [(u, True), (u, False)], slack)] for u in W}
    conflicts = []
    for u, v in combinations(W, 2):
        for t in set(alone[u]) & set(alone[v]):
            st = {"Pa": (u, True), "Da": (u, False), "Pb": (v, True), "Db": (v, False)}
            if not any(_ok(m, t, [st[x] for x in seq], slack) for seq in INTERLEAVINGS):
                conflicts.append((u, v, t))

    mdl = cp_model.CpModel()
    x = {(u, t): mdl.NewBoolVar(f"x{u}_{t}") for u in W for t in alone[u]}
    for u in W:
        mdl.Add(sum(x[u, t] for t in alone[u]) <= 1)
    for u, v, t in conflicts:
        mdl.Add(x[u, t] + x[v, t] <= 1)
    SCALE = 100
    mdl.Maximize(sum(int(m.o_val[u] * SCALE) * x[k] for k in x for u in [k[0]]))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    status = solver.Solve(mdl)
    served = [u for u in W if any(solver.Value(x[u, t]) for t in alone[u])]
    lost = [u for u in W if u not in served]
    value_lost = sum(m.o_val[u] for u in lost)
    # the bound is the LP/CP upper bound on served value, so use the solver's bound
    best_bound_value = solver.BestObjectiveBound() / SCALE
    window_value = sum(m.o_val[u] for u in W)
    return {
        "status": solver.StatusName(status),
        "window_orders": len(W),
        "never_feasible": [u for u in W if not alone[u]],
        "conflicts": len(conflicts),
        "conflict_list": conflicts,
        "max_served": len(served),
        "must_lose": lost,
        "min_value_lost": max(0.0, window_value - best_bound_value),
        "max_fulfillment": 100 * (m.value_total - max(0.0, window_value - best_bound_value)) / m.value_total,
        "alone": alone,
        # one optimal "chessboard" placement: window order -> truck
        "assignment": {u: t for u in W for t in alone[u] if solver.Value(x[u, t])},
    }
