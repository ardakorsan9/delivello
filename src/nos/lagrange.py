"""Lagrangian upper bound on the score (math: docs/UPPER_BOUND.md).

Window-set packing problem (P), columns from chessboard.enumerate_truck:
    max  sum_t sum_{S in F_t} v_S y_tS
    s.t. sum_{S in F_t} y_tS <= 1                 for every truck t
         sum_t sum_{S in F_t, u in S} y_tS <= 1    for every window order u   (relaxed, multiplier mu_u >= 0)
         y_tS in {0, 1}
Dual function (separates by truck, each subproblem picks its best reduced column):
    L(mu) = sum_u mu_u + sum_t max(0, max_{S in F_t} (v_S - sum_{u in S} mu_u))
Weak duality: L(mu) >= OPT(P) for every mu >= 0. We minimise L by projected
subgradient with Polyak steps. v_S is the *nominal* value (no lateness discount),
so the bound also holds for lateness-scaled values.

Score bound:
    score <= 10 * (0.5 * F_ub + 0.2*100 + 0.15*100 + 0.15*100),
    F_ub = 100 * (value of all orders without windows + min_mu L(mu)) / value_total.
This module only reads; it does not change plans or other modules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .chessboard import enumerate_truck
from .evaluate import Model
from .simulator import WEIGHTS


@dataclass
class LagrangeBound:
    window_value_ub: float          # min_mu L(mu)
    window_value_lb: float          # best feasible packing found from the multipliers
    window_count_lb: int
    nonwindow_value: float
    value_total: float
    fulfillment_ub: float           # percent
    score_ub: float
    iterations: int
    columns: int
    complete: bool                  # enumeration not truncated -> bound is valid for (P) = real window problem
    history: list = field(default_factory=list)


def columns(m: Model, keep: int = 30, max_sets: int = 200000):
    """F_t for every truck: (truck, frozenset S, nominal value v_S)."""
    W = [o for o in range(m.n_orders) if m.o_tw[o][0] or m.o_tw[o][1]]
    cols, complete = [], True
    for t in range(m.n_trucks):
        ts = enumerate_truck(m, t, [u for u in W if m.can[u][t]], keep, max_sets)
        complete &= not ts.truncated
        for S in ts.sets:
            cols.append((t, S, sum(m.o_val[u] for u in S)))
    return W, cols, complete


def dual_value(mu: dict, cols, n_trucks: int):
    """L(mu) and the chosen column per truck (or None)."""
    best = [(0.0, None)] * n_trucks
    for t, S, v in cols:
        red = v - sum(mu[u] for u in S)
        if red > best[t][0]:
            best[t] = (red, S)
    return sum(mu.values()) + sum(r for r, _ in best), [S for _, S in best]


def greedy_primal(mu: dict, cols, n_trucks: int):
    """Feasible packing guided by the multipliers: best reduced value first, no order twice."""
    order = sorted(cols, key=lambda c: -(c[2] - sum(mu[u] for u in c[1])))
    used_t, used_o, value, count = set(), set(), 0.0, 0
    for t, S, v in order:
        if t in used_t or S & used_o:
            continue
        used_t.add(t)
        used_o |= S
        value += v
        count += len(S)
    return value, count


def lagrangian_bound(m: Model, iters: int = 3000, theta0: float = 2.0, keep: int = 30,
                     verbose: bool = False) -> LagrangeBound:
    W, cols, complete = columns(m, keep=keep)
    mu = {u: 0.0 for u in W}
    lb, lb_count = greedy_primal(mu, cols, m.n_trucks)
    ub, theta, since = math.inf, theta0, 0
    hist = []
    for k in range(iters):
        L, chosen = dual_value(mu, cols, m.n_trucks)
        if L < ub - 1e-9:
            ub, since = L, 0
        else:
            since += 1
            if since >= 50:  # standard Held-Karp schedule: halve the step after stalling
                theta, since = theta / 2, 0
        cnt = {u: 0 for u in W}
        for S in chosen:
            for u in S or ():
                cnt[u] += 1
        g = {u: 1 - cnt[u] for u in W}          # subgradient of L at mu
        norm2 = sum(x * x for x in g.values())
        if k % 25 == 0:
            v, c = greedy_primal(mu, cols, m.n_trucks)
            if v > lb:
                lb, lb_count = v, c
        hist.append((k, L, lb))
        if norm2 == 0 or ub - lb < 1e-6 or theta < 1e-6:
            break                                # g = 0: mu is optimal; or bound closed
        step = theta * (L - lb) / norm2          # Polyak step towards the best known primal
        mu = {u: max(0.0, mu[u] - step * g[u]) for u in W}
        if verbose and k % 200 == 0:
            print(f"  it {k:5d}  L(mu)={L:9.4f}  best UB={ub:9.4f}  LB={lb:9.4f}  theta={theta:.4f}")

    nonwin = sum(m.o_val[o] for o in range(m.n_orders) if o not in set(W))
    f_ub = 100 * min(m.value_total, nonwin + ub) / m.value_total
    score_ub = 10 * (WEIGHTS["fulfillment"] * f_ub + 100 * (WEIGHTS["cost_efficiency"]
                     + WEIGHTS["loaded_ratio"] + WEIGHTS["co2_efficiency"]))
    return LagrangeBound(ub, lb, lb_count, nonwin, m.value_total, f_ub, score_ub, k + 1,
                         len(cols), complete, hist)
