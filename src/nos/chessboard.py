"""The "chessboard": jointly optimal placement of the time-window orders.

Fulfillment is decided mainly by the time-window orders; the other orders are
inserted afterwards by regret insertion.

1. For every truck, enumerate the sets of window orders it can serve together,
   starting empty, all stops at most 60 min late (bottom-up: a feasible route of
   S + {v} minus v is a feasible route of S, so every feasible set is reached by
   inserting v into a feasible route of S). Up to `keep` routes per set are kept
   (earliest finish first), so very large neighbourhoods are truncated: the
   enumeration is then a strong lower bound, not a proof.
2. CP-SAT picks at most one set per truck, every order at most once, maximising
   the served value (lateness-scaled), with a tiny km tie-break.
3. The chosen window routes seed a plan; all other orders are inserted by regret.

`lagrange.py` turns the same columns into a Lagrangian upper bound
(docs/UPPER_BOUND.md); the enumeration is complete for all scenarios, so the
window part is optimal up to the break-credit caveat described there.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from .construct import Insertion, regret_insertion
from .evaluate import Model, Stop


@dataclass
class TruckSets:
    truck: int
    candidates: list[int]
    sets: dict[frozenset, list[tuple[float, float, list[Stop]]]] = field(default_factory=dict)
    truncated: bool = False


def _insertions(route: list[Stop], v: int):
    n = len(route)
    for i in range(n + 1):
        for j in range(i, n + 1):
            yield route[:i] + [(v, True)] + route[i:j] + [(v, False)] + route[j:]


def enumerate_truck(m: Model, t: int, candidates: list[int], keep: int = 30,
                    max_sets: int = 200000, grace: int = 60) -> TruckSets:
    ts = TruckSets(t, candidates)
    level: dict[frozenset, list] = {}
    for u in candidates:
        e = m.eval_truck(t, [(u, True), (u, False)], early_exit=True, grace=grace)
        if e.ok and (e.count == 1 or grace > 60):
            level[frozenset([u])] = [(e.value, e.finish, [(u, True), (u, False)])]
    ts.sets.update(level)
    candidates = sorted(next(iter(S)) for S in level)  # only orders this truck serves alone
    ts.candidates = candidates
    while level:
        nxt: dict[frozenset, list] = {}
        for S, routes in level.items():
            for v in candidates:
                if v in S or v < max(S):  # canonical extension order avoids duplicates
                    continue
                key = S | {v}
                found = nxt.setdefault(key, [])
                for _, _, r in routes:
                    for new in _insertions(r, v):
                        e = m.eval_truck(t, new, early_exit=True, grace=grace)
                        if e.ok and (e.count == len(key) or grace > 60):
                            found.append((e.value, e.finish, new))
                if not found:
                    del nxt[key]
                else:
                    # best value first, then earliest finish (leaves most room for later stops)
                    found.sort(key=lambda x: (-x[0], x[1]))
                    nxt[key] = found[:keep]
            if len(ts.sets) + len(nxt) > max_sets:
                ts.truncated = True
                break
        ts.sets.update(nxt)
        if ts.truncated:
            break
        level = nxt
    return ts


@dataclass
class ChessboardResult:
    plan: Insertion
    assignment: dict[int, frozenset]   # truck -> chosen window set
    window_value: float
    window_served: int
    window_total: int
    status: str
    truncated_trucks: list[int]
    n_sets: int
    seconds: float


def solve(m: Model, keep: int = 30, max_sets: int = 200000, time_limit: float = 60.0,
          fill_k: int = 3, verbose: bool = True, grace: int = 60) -> ChessboardResult:
    """grace > 60 is only a robustness check of the bound (the plan is then not valid)."""
    t0 = time.perf_counter()
    W = [o for o in range(m.n_orders) if m.o_tw[o][0] or m.o_tw[o][1]]
    boards = []
    for t in range(m.n_trucks):
        cand = [u for u in W if m.can[u][t]]
        ts = enumerate_truck(m, t, cand, keep, max_sets, grace)
        boards.append(ts)
        if verbose:
            big = max((len(s) for s in ts.sets), default=0)
            print(f"  {m.truck_ids[t]}: {len(cand):2d} window candidates, {len(ts.sets):6d} feasible sets, "
                  f"largest {big}{' (truncated)' if ts.truncated else ''}", flush=True)

    mdl = cp_model.CpModel()
    y = {}
    for ts in boards:
        for k, (S, routes) in enumerate(ts.sets.items()):
            y[ts.truck, k] = (mdl.NewBoolVar(f"y{ts.truck}_{k}"), S, routes[0])
        mdl.Add(sum(v for (t, _), (v, _, _) in y.items() if t == ts.truck) <= 1)
    by_order: dict[int, list] = {}
    for (t, k), (var, S, _) in y.items():
        for u in S:
            by_order.setdefault(u, []).append(var)
    for u, vs in by_order.items():
        mdl.Add(sum(vs) <= 1)
    # value dominates; km only breaks ties (1 value unit = 1e6, 1 km = 1)
    def set_value(S, best):  # robustness mode counts full value even beyond 60 min late
        return best[0] if grace == 60 else sum(m.o_val[u] for u in S)
    mdl.Maximize(sum(int(set_value(S, best) * 1_000_000) * var - int(m.eval_truck(t, best[2]).km) * var
                     for (t, _), (var, S, best) in y.items()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 4
    status = solver.Solve(mdl)

    ins = Insertion(m)
    assignment = {}
    for (t, _), (var, S, best) in y.items():
        if solver.Value(var):
            assignment[t] = S
            ins.apply(t, m.eval_truck(t, best[2]), list(best[2]))
    served = {u for S in assignment.values() for u in S}
    rest = [o for o in range(m.n_orders) if o not in served]
    regret_insertion(m, k=fill_k, orders=rest, ins=ins)
    return ChessboardResult(
        plan=ins, assignment=assignment,
        window_value=sum(m.o_val[u] for u in served), window_served=len(served),
        window_total=len(W), status=solver.StatusName(status),
        truncated_trucks=[ts.truck for ts in boards if ts.truncated],
        n_sets=sum(len(ts.sets) for ts in boards), seconds=time.perf_counter() - t0)
