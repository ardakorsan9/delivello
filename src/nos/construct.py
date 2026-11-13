"""Construction heuristic: regret-k insertion on the official score.

Every unassigned order gets, for each compatible truck, its best (pickup,
delivery) insertion position. Each step inserts the order with the largest
regret (how much is lost if it does not get its best truck), so hard orders
(time windows, special truck types) are placed while there is still room.
Orders whose best insertion would lower the score stay unassigned.

The score is evaluated exactly (fast evaluator), not with a distance proxy, so
cost/CO2 saturation and the loaded-km ratio are handled correctly.
"""

from __future__ import annotations

import numpy as np

from .evaluate import EMPTY, Model, Stop, TruckEval

NEG = float("-inf")


class Insertion:
    def __init__(self, m: Model, routes: list[list[Stop]] | None = None):
        self.m = m
        self.routes = routes or [[] for _ in range(m.n_trucks)]
        self.evals = [m.eval_truck(t, r) for t, r in enumerate(self.routes)]
        self.tot = list(Model.totals(self.evals))

    def delta(self, t: int, new: TruckEval) -> float:
        old = self.evals[t]
        tot = self.tot
        return self.m.score_parts(tot[0] - old.km + new.km, tot[1] - old.loaded + new.loaded,
                                  tot[2] - old.cost + new.cost, tot[3] - old.co2 + new.co2,
                                  tot[4] - old.value + new.value, tot[5] - old.count + new.count) \
            - self.m.score_parts(*tot)

    def positions(self, t: int, o: int, topn: int | None) -> list[tuple[int, int]]:
        """(i, j) insertion positions; with topn only the topn with the smallest km increase.

        new route = r[:i] + [P] + r[i:j] + [D] + r[j:]. Vectorized: pickup cost A[i],
        delivery cost B[j] (i < j), adjacent pickup+delivery cost C[i] (i == j).
        """
        n = len(self.routes[t])
        if topn is None or (n + 1) * (n + 2) // 2 <= topn:
            return [(i, j) for i in range(n + 1) for j in range(i, n + 1)]
        m, r = self.m, self.routes[t]
        K = m.km_np
        pc, dc = m.o_city[o]
        city = np.fromiter((m.o_city[a][0 if p else 1] for a, p in r), dtype=np.int64, count=n)
        prev = np.concatenate(([m.t_start[t]], city))       # prev[k] = city before position k
        nxt_d = np.zeros(n + 1)                              # (succ - prev) correction, 0 at the end
        nxt_d[:n] = K[prev[:n], city]
        A = K[prev, pc] + np.append(K[pc, city] - nxt_d[:n], 0.0)
        B = K[prev, dc] + np.append(K[dc, city] - nxt_d[:n], 0.0)
        C = K[prev, pc] + K[pc, dc] + np.append(K[dc, city] - nxt_d[:n], 0.0)
        M = A[:, None] + B[None, :]
        M[np.tril_indices(n + 1)] = np.inf                   # need i < j
        M[np.diag_indices(n + 1)] = C
        flat = M.ravel()
        k = min(topn, flat.size)
        idx = np.argpartition(flat, k - 1)[:k]
        idx = idx[np.isfinite(flat[idx])]
        return [(int(x) // (n + 1), int(x) % (n + 1)) for x in idx]

    def candidates(self, t: int, o: int, topn: int | None = None) -> list[tuple[float, TruckEval, list[Stop]]]:
        """Feasible insertions of order o into truck t, best first (exact score delta)."""
        m, r = self.m, self.routes[t]
        out = []
        P, D = (o, True), (o, False)
        need = self.evals[t].count + 1
        for i, j in self.positions(t, o, topn):
            new = r[:i] + [P] + r[i:j] + [D] + r[j:]
            e = m.eval_truck(t, new, early_exit=True)
            if e.ok and e.count == need:
                out.append((self.delta(t, e), e, new))
        out.sort(key=lambda x: -x[0])
        return out

    def remove(self, orders: set[int]) -> None:
        """Take these orders out of whatever routes they are on."""
        for t, r in enumerate(self.routes):
            if any(o in orders for o, _ in r):
                new = [s for s in r if s[0] not in orders]
                self.apply(t, self.m.eval_truck(t, new), new)

    def assigned(self) -> set[int]:
        return {o for r in self.routes for o, _ in r}

    def copy(self) -> "Insertion":
        c = Insertion.__new__(Insertion)
        c.m, c.routes, c.evals, c.tot = self.m, [list(r) for r in self.routes], list(self.evals), list(self.tot)
        return c

    def apply(self, t: int, e: TruckEval, route: list[Stop]) -> None:
        old = self.evals[t]
        for k, (a, b) in enumerate(zip((old.km, old.loaded, old.cost, old.co2, old.value, old.count),
                                       (e.km, e.loaded, e.cost, e.co2, e.value, e.count))):
            self.tot[k] += b - a
        self.routes[t] = route
        self.evals[t] = e

    def score(self) -> float:
        return self.m.score_parts(*self.tot)


def regret_insertion(m: Model, k: int = 2, orders: list[int] | None = None,
                     ins: Insertion | None = None, topn: int | None = None,
                     noise: float = 0.0, rng=None) -> Insertion:
    """Insert `orders` (default: all) into `ins` by regret-k.

    topn limits positions per (order, truck) to the topn cheapest by km (fast mode
    for ALNS); noise > 0 perturbs the choice key (diversification).
    """
    ins = ins or Insertion(m)
    todo = set(range(m.n_orders) if orders is None else orders)
    # cache[o][t] = (eval, route) of the best insertion of o into t's *current* route
    cache: dict[int, dict[int, tuple[TruckEval, list[Stop]]]] = {}

    def refresh(o: int, t: int) -> None:
        c = ins.candidates(t, o, topn)
        if c:
            cache[o][t] = (c[0][1], c[0][2])
        else:
            cache[o].pop(t, None)

    for o in todo:
        cache[o] = {}
        for t in range(m.n_trucks):
            if m.can[o][t]:
                refresh(o, t)

    while todo:
        best_key, pick = NEG, None
        for o in todo:
            # deltas are recomputed against the current totals (cheap, no re-simulation)
            ds = sorted(((ins.delta(t, e), t) for t, (e, _) in cache[o].items()), reverse=True)
            if not ds or ds[0][0] <= 0:
                continue
            regret = sum(ds[0][0] - d for d, _ in ds[1:k]) if len(ds) >= k else float("inf")
            if noise:
                regret *= 1 + noise * (rng.random() - 0.5)
            key = (regret, ds[0][0])
            if best_key is NEG or key > best_key:
                best_key, pick = key, (o, ds[0][1])
        if pick is None:
            break
        o, t = pick
        e, route = cache[o][t]
        ins.apply(t, e, route)
        todo.discard(o)
        del cache[o]
        for o2 in todo:
            if m.can[o2][t]:
                refresh(o2, t)
    return ins


def anchored_construction(m: Model, assignment: dict[int, int], k: int = 2) -> Insertion:
    """Place time-window orders on the trucks a global assignment chose (e.g. the
    CP-SAT bound), hardest first, then fill in all other orders by regret-k."""
    ins = Insertion(m)
    # fewest alternatives first: tight windows decide the start of the routes
    order = sorted(assignment, key=lambda u: (m.o_tw[u][0] or m.o_tw[u][1])[1]
                   if (m.o_tw[u][0] or m.o_tw[u][1]) else 0)
    for u in order:
        t = assignment[u]
        c = ins.candidates(t, u)
        if c:
            ins.apply(t, c[0][1], c[0][2])
    rest = [o for o in range(m.n_orders) if o not in ins.assigned()]
    return regret_insertion(m, k=k, orders=rest, ins=ins)
