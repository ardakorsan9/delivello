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

    def candidates(self, t: int, o: int) -> list[tuple[float, TruckEval, list[Stop]]]:
        """All feasible insertions of order o into truck t, best first."""
        m, r = self.m, self.routes[t]
        out = []
        n = len(r)
        P, D = (o, True), (o, False)
        for i in range(n + 1):
            head = r[:i] + [P]
            for j in range(i, n + 1):
                new = head + r[i:j] + [D] + r[j:]
                e = m.eval_truck(t, new)
                if e.ok and e.count == self.evals[t].count + 1:
                    out.append((self.delta(t, e), e, new))
        out.sort(key=lambda x: -x[0])
        return out

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
                     ins: Insertion | None = None) -> Insertion:
    ins = ins or Insertion(m)
    todo = set(range(m.n_orders) if orders is None else orders)
    # cache[o][t] = (eval, route) of the best insertion of o into t's *current* route
    cache: dict[int, dict[int, tuple[TruckEval, list[Stop]]]] = {}

    def refresh(o: int, t: int) -> None:
        c = ins.candidates(t, o)
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
