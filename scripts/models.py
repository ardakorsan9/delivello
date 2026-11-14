"""Model comparison: every candidate window-packing model, its Lagrangian bound, and its real score.

Score structure (docs/UPPER_BOUND.md): with cost and CO2 capped at 100,
    score = 350 + 500 * value / V + 150 * loaded / km           (C, G = 100)
All remaining empty km sits in the window routes (first legs), so a column (truck t, window set S,
route r) is described by its value v and its empty km e. Linearising the loaded ratio around the
current plan (Dinkelbach step, beta = d score / d empty km) gives the full-score column weight
    w(S, r) = alpha * v - beta * e,   alpha = 500 / V,  beta = 150 * loaded / km^2.

Models (each one is a packing of window sets onto trucks, solved by CP-SAT):
  A  value          max value, km tie-break                      (the current chessboard)
  B  value+empty    max value, then min empty km of window routes (new tie-break)
  C  full score     max sum alpha*v - beta*e                     (new: may trade value for km)
  D1..Dk            the k next-best packings of model C           (no-good cuts: all alternatives)
Every model gets a Lagrangian bound on its own packing objective (projected subgradient), then a
plan: window routes -> regret insertion of all other orders -> parallel ALNS -> exact simulator.

Usage:  uv run python scripts/models.py [scenario ...] [--alt 8] [--seconds 40] [--workers 4]
Writes results/<scenario>/models.json; a better valid plan also goes to best.json (archive()).
Never submits to the API.
"""

from __future__ import annotations

import argparse
import json
import math
import time

from ortools.sat.python import cp_model

from nos.chessboard import enumerate_truck
from nos.construct import Insertion, regret_insertion
from nos.data import load_scenario
from nos.evaluate import Model
from nos.lagrange import lagrangian_bound
from nos.pipeline import parallel_alns, routes_from_plan
from nos.plans import RESULTS_DIR, archive, best_plan
from nos.simulator import simulate

ALL = ["scenario_middle", "scenario_big", "scenario_competitive"]
SCALE = 1_000_000


# ------------------------------------------------------------------ columns
def build_columns(m: Model, keep: int = 30):
    """One entry per (truck, window set): the value-best route and the empty-km-best route."""
    W = [o for o in range(m.n_orders) if m.o_tw[o][0] or m.o_tw[o][1]]
    cols = []
    for t in range(m.n_trucks):
        ts = enumerate_truck(m, t, [u for u in W if m.can[u][t]], keep)
        for S, routes in ts.sets.items():
            evs = [(m.eval_truck(t, r), r) for _, _, r in routes]
            evs = [(e, r) for e, r in evs if e.ok]
            if not evs:
                continue
            cols.append({"t": t, "S": S, "routes": evs})
    return W, cols


def column_weight(col, model: str, alpha: float, beta: float):
    """(integer objective, chosen route, value, empty km) of a column under a model."""
    if model == "A":
        e, r = max(col["routes"], key=lambda x: (x[0].value, -x[0].km))
        obj = int(e.value * SCALE) - int(e.km)
    elif model == "B":
        e, r = max(col["routes"], key=lambda x: (x[0].value, -(x[0].km - x[0].loaded), -x[0].km))
        obj = int(e.value * SCALE) - int(1000 * (e.km - e.loaded)) - int(e.km)
    else:  # C: linearised full score
        e, r = max(col["routes"], key=lambda x: alpha * x[0].value - beta * (x[0].km - x[0].loaded))
        obj = int(SCALE * (alpha * e.value - beta * (e.km - e.loaded)))
    return obj, r, e.value, e.km - e.loaded


# ------------------------------------------------------------------ Lagrange on a weighted packing
def lagrange_weighted(weights, sets, trucks, W, iters: int = 3000):
    """min_mu L(mu) = sum mu + sum_t max(0, max_S (w_S - mu(S))) and a greedy primal."""
    n_t = max(trucks) + 1
    mu = {u: 0.0 for u in W}

    def dual(mu):
        best = [(0.0, None)] * n_t
        for k, (w, S, t) in enumerate(zip(weights, sets, trucks)):
            red = w - sum(mu[u] for u in S)
            if red > best[t][0]:
                best[t] = (red, k)
        return sum(mu.values()) + sum(r for r, _ in best), [k for _, k in best]

    def greedy(mu):
        idx = sorted(range(len(weights)), key=lambda k: -(weights[k] - sum(mu[u] for u in sets[k])))
        ut, uo, val = set(), set(), 0.0
        for k in idx:
            if trucks[k] in ut or sets[k] & uo or weights[k] <= 0:
                continue
            ut.add(trucks[k])
            uo |= sets[k]
            val += weights[k]
        return val

    ub, lb, theta, since = math.inf, greedy(mu), 2.0, 0
    for k in range(iters):
        L, chosen = dual(mu)
        if L < ub - 1e-9:
            ub, since = L, 0
        else:
            since += 1
            if since >= 50:
                theta, since = theta / 2, 0
        cnt = {u: 0 for u in W}
        for c in chosen:
            if c is not None:
                for u in sets[c]:
                    cnt[u] += 1
        g = {u: 1 - cnt[u] for u in W}
        n2 = sum(x * x for x in g.values())
        if k % 25 == 0:
            lb = max(lb, greedy(mu))
        if n2 == 0 or ub - lb < 1e-9 or theta < 1e-7:
            break
        step = theta * (L - lb) / n2
        mu = {u: max(0.0, mu[u] - step * g[u]) for u in W}
    return ub, lb, k + 1


# ------------------------------------------------------------------ packing models
def solve_packings(m: Model, cols, model: str, alpha: float, beta: float, n_solutions: int = 1,
                   time_limit: float = 30.0):
    """Best packing, then the next ones with no-good cuts (each a different set of columns)."""
    data = [column_weight(c, model, alpha, beta) for c in cols]
    mdl = cp_model.CpModel()
    y = [mdl.NewBoolVar(f"y{k}") for k in range(len(cols))]
    for t in range(m.n_trucks):
        mdl.Add(sum(y[k] for k, c in enumerate(cols) if c["t"] == t) <= 1)
    by_o: dict[int, list] = {}
    for k, c in enumerate(cols):
        for u in c["S"]:
            by_o.setdefault(u, []).append(y[k])
    for vs in by_o.values():
        mdl.Add(sum(vs) <= 1)
    mdl.Maximize(sum(d[0] * y[k] for k, d in enumerate(data)))
    out = []
    for _ in range(n_solutions):
        s = cp_model.CpSolver()
        s.parameters.max_time_in_seconds = time_limit
        s.parameters.num_workers = 4
        st = s.Solve(mdl)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break
        chosen = [k for k in range(len(cols)) if s.Value(y[k])]
        out.append({"cols": chosen, "obj": s.ObjectiveValue() / SCALE, "status": s.StatusName(st),
                    "value": sum(data[k][2] for k in chosen), "empty": sum(data[k][3] for k in chosen),
                    "routes": {cols[k]["t"]: data[k][1] for k in chosen}})
        # no-good cut: at least one chosen column must change
        mdl.Add(sum(y[k] for k in chosen) <= len(chosen) - 1)
    return out, data


def plan_from_packing(m: Model, routes: dict) -> Insertion:
    ins = Insertion(m)
    for t, r in routes.items():
        ins.apply(t, m.eval_truck(t, r), list(r))
    served = {o for r in routes.values() for o, _ in r}
    regret_insertion(m, k=3, orders=[o for o in range(m.n_orders) if o not in served], ins=ins)
    return ins


# ------------------------------------------------------------------ main
def run_scenario(sid: str, n_alt: int, seconds: float, workers: int) -> dict:
    sc = load_scenario(sid)
    m = Model(sc)
    stored = best_plan(sid)
    ref = Insertion(m, routes_from_plan(m, stored["plan"])) if stored else None
    tot = Model.totals(ref.evals) if ref else Model.totals([])
    km, loaded = tot[0] or 1.0, tot[1] or 1.0
    alpha, beta = 500 / m.value_total, 150 * loaded / km ** 2
    print(f"\n{sid}: alpha = {alpha:.3f} pts / value unit, beta = {beta:.5f} pts / empty km")

    t0 = time.perf_counter()
    W, cols = build_columns(m)
    nonwin = sum(m.o_val[o] for o in range(m.n_orders) if o not in set(W))
    print(f"  {len(W)} window orders, {len(cols)} columns ({time.perf_counter() - t0:.0f}s)")
    glob = lagrangian_bound(m)
    print(f"  global Lagrangian bound (rigorous, R=100): score <= {glob.score_ub:.2f}")

    specs = [("A", "A  value (current chessboard)", 1), ("B", "B  value + min empty km", 1),
             ("C", "C  full score (Dinkelbach)", 1 + n_alt)]
    rows = []
    for model, label, n in specs:
        packs, data = solve_packings(m, cols, model, alpha, beta, n)
        w = [d[0] / SCALE for d in data]
        ub, lb, its = lagrange_weighted(w, [c["S"] for c in cols], [c["t"] for c in cols], W)
        if model == "C":   # objective in score points -> estimated score bound of this model
            model_ub = 350 + alpha * nonwin + 150 + ub
        else:              # same feasible packings as the global bound, value objective -> same bound
            model_ub = glob.score_ub
        print(f"  model {model}: Lagrange L(mu) = {ub:.4f} (primal {lb:.4f}, {its} steps) "
              f"-> model bound {model_ub:.2f}")
        for i, p in enumerate(packs):
            name = label if i == 0 else f"D{i} alternative #{i} of model C"
            start = plan_from_packing(m, p["routes"])
            s0 = start.score()
            best = start
            if seconds > 0:
                cand, _, _, _ = parallel_alns(m, sid, start, seconds, workers, seed0=100 * i,
                                              log=lambda *_: None)
                if cand.score() > best.score():
                    best = cand
            plan = m.to_plan(best.routes)
            sim = simulate(sc, plan)
            ok = not sim.violations and abs(sim.score - best.score()) < 0.011
            b = sim.breakdown
            row = {"model": name, "window_value": round(p["value"], 3), "window_empty_km": round(p["empty"]),
                   "packing_obj": round(p["obj"], 4), "start": round(s0, 3), "score": sim.score,
                   "valid": ok, "fulfillment": b["fulfillment"], "loaded": b["loaded_ratio"],
                   "cost": b["cost_efficiency"], "co2": b["co2_efficiency"],
                   "model_bound": round(model_ub, 2) if i == 0 else None}
            rows.append(row)
            print(f"    {name:34s} window value {p['value']:7.3f}  empty {p['empty']:6.0f} km  "
                  f"start {s0:8.2f} -> {sim.score:8.2f} {'OK' if ok else 'INVALID'}")
            if ok:
                if archive(plan, sid, sim.score, fingerprint=sc.fingerprint, source=f"model_{model}{i}",
                           valid=True):
                    print("      -> new best in best.json")

    ref_score = simulate(sc, stored["plan"]).score if stored else None
    win = max((r for r in rows if r["valid"]), key=lambda r: r["score"])
    res = {"scenario": sid, "alpha": alpha, "beta": beta, "global_bound": round(glob.score_ub, 2),
           "stored_best_before": ref_score, "rows": rows, "winner": win["model"]}
    (RESULTS_DIR / sid / "models.json").write_text(json.dumps(res, indent=1))
    print(f"  WINNER: {win['model'].strip()}  {win['score']:.2f}   (stored best before: {ref_score}, "
          f"global bound {glob.score_ub:.2f})")
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="*")
    ap.add_argument("--alt", type=int, default=8, help="alternative packings of model C")
    ap.add_argument("--seconds", type=float, default=40, help="ALNS seconds per model (0 = none)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    for sid in a.scenarios or ALL:
        run_scenario(sid, a.alt, a.seconds, a.workers)


if __name__ == "__main__":
    main()
