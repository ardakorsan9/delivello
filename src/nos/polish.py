"""Set-partitioning polish over a route pool, with Dinkelbach for the loaded ratio.

ALNS visits many good routes per truck; the best plan rarely combines the best
of them. CP-SAT picks at most one pooled route per truck such that
- every order is served at most once,
- the served value is at least the incumbent's (fulfillment never drops),
- total cost / CO2 stay below the incumbent's reference (efficiency stays capped at 100),
and maximises the loaded-km ratio L/T. A ratio is not linear, so Dinkelbach's
method solves max L - lambda*T repeatedly with lambda <- L/T until the optimum of
that problem is 0 (then L/T is maximal over the pool). Sartori & Buriol (2020)
report set partitioning over a route pool as the best matheuristic step.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from .construct import Insertion
from .evaluate import Model

KM = 10        # km scaled to integers (0.1 km)
VAL = 10_000   # value scaled to integers


def set_partition(m: Model, pool: dict[int, set], incumbent: Insertion, rounds: int = 6,
                  time_limit: float = 20.0, verbose: bool = True) -> Insertion:
    routes = []  # (truck, route, eval, orders)
    for t in range(m.n_trucks):
        seen = set(pool.get(t, set()))
        if incumbent.routes[t]:
            seen.add(tuple(incumbent.routes[t]))
        for r in seen:
            e = m.eval_truck(t, list(r))
            if e.ok and e.count == len(r) // 2:
                routes.append((t, list(r), e, {o for o, _ in r}))
    if verbose:
        print(f"  pool: {len(routes)} feasible routes over {m.n_trucks} trucks")

    km0, loaded0, cost0, co2_0, value0, count0 = Model.totals(incumbent.evals)
    ref_km = m.ref_km_per_order * count0
    cost_cap = max(cost0, ref_km * m.min_cost)   # keep cost_efficiency where it is (100 if capped)
    co2_cap = max(co2_0, ref_km * m.min_co2)
    best = incumbent
    best_score = incumbent.score()
    lam = loaded0 / km0 if km0 else 0.0
    inc_key = {(t, tuple(r)) for t, r in enumerate(incumbent.routes) if r}

    for it in range(rounds):
        mdl = cp_model.CpModel()
        z = [mdl.NewBoolVar(f"z{k}") for k in range(len(routes))]
        for t in range(m.n_trucks):
            mdl.Add(sum(z[k] for k, rt in enumerate(routes) if rt[0] == t) <= 1)
        cover: dict[int, list] = {}
        for k, rt in enumerate(routes):
            for o in rt[3]:
                cover.setdefault(o, []).append(z[k])
        for vs in cover.values():
            mdl.Add(sum(vs) <= 1)
        mdl.Add(sum(int(round(rt[2].value * VAL)) * z[k] for k, rt in enumerate(routes))
                >= int(round(value0 * VAL)) - 1)
        mdl.Add(sum(int(rt[2].cost * 100) * z[k] for k, rt in enumerate(routes)) <= int(cost_cap * 100))
        mdl.Add(sum(int(rt[2].co2 * 100) * z[k] for k, rt in enumerate(routes)) <= int(co2_cap * 100))
        mdl.Maximize(sum(int(round((rt[2].loaded - lam * rt[2].km) * KM)) * z[k]
                         for k, rt in enumerate(routes)))
        for k, rt in enumerate(routes):  # warm start from the incumbent
            mdl.AddHint(z[k], (rt[0], tuple(rt[1])) in inc_key)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.num_workers = 4
        status = solver.Solve(mdl)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break
        sol = Insertion(m)
        for k, rt in enumerate(routes):
            if solver.Value(z[k]):
                sol.apply(rt[0], rt[2], list(rt[1]))
        km, loaded = sol.tot[0], sol.tot[1]
        s = sol.score()
        if verbose:
            print(f"  dinkelbach {it}: lambda={lam:.5f} -> loaded ratio {loaded / km:.5f}, "
                  f"score {s:.3f} ({solver.StatusName(status)})")
        if s > best_score + 1e-9:
            best, best_score = sol, s
        new_lam = loaded / km if km else lam
        if new_lam <= lam + 1e-7:
            break
        lam = new_lam
    return best

