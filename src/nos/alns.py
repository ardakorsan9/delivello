"""Adaptive Large Neighbourhood Search (Ropke & Pisinger 2006) on the official score.

Loop: destroy (remove q orders) -> repair (regret insertion) -> accept/reject.

- Destroy operators: random, worst (km per value), related (Shaw), route, and
  `free_truck`, which empties a truck that can serve a currently *unassigned*
  order on time, so the repair can place that order first (it has the fewest
  options, hence the largest regret).
- Operator choice: roulette wheel with adaptive weights (reward per segment).
- Acceptance: simulated annealing. The temperature is not a fixed cooling
  schedule but a PI controller that tracks a target acceptance rate of
  worsening moves (high early = explore, low late = exploit).
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from .construct import Insertion, regret_insertion
from .evaluate import Model

# rewards (Ropke & Pisinger): new global best / better than current / accepted worse
SIGMA_BEST, SIGMA_BETTER, SIGMA_ACCEPT = 33.0, 9.0, 13.0


@dataclass
class PITemperature:
    """SA temperature as the actuator of a PI loop on the acceptance rate.

    Process variable: exponential moving average of 'worse move accepted' (0/1).
    Set point: target rate, linearly from `start` to `end` over the run.
    Actuator: log T (keeps T positive; multiplicative steps).
    """
    T: float = 2.0
    kp: float = 0.5
    ki: float = 0.02
    start: float = 0.25
    end: float = 0.01
    ema: float = 0.25
    alpha: float = 0.05
    integral: float = 0.0
    t_min: float = 1e-2
    t_max: float = 200.0

    def target(self, progress: float) -> float:
        return self.start + (self.end - self.start) * min(1.0, progress)

    def update(self, accepted_worse: bool, progress: float) -> None:
        self.ema += self.alpha * (float(accepted_worse) - self.ema)
        e = self.target(progress) - self.ema
        self.integral = max(-50.0, min(50.0, self.integral + e))
        log_t = math.log(self.T) + self.kp * e + self.ki * self.integral
        self.T = min(self.t_max, max(self.t_min, math.exp(log_t)))


@dataclass
class ALNSResult:
    best: Insertion
    history: list[dict] = field(default_factory=list)
    op_stats: dict = field(default_factory=dict)
    iterations: int = 0
    # truck -> set of feasible routes seen in accepted / best solutions (for set partitioning)
    pool: dict = field(default_factory=dict)


class ALNS:
    def __init__(self, m: Model, seed: int = 0, topn: int = 12):
        self.m = m
        self.rng = random.Random(seed)
        self.topn = topn
        # trucks on which an order is feasible on its own (time windows, type, capacity)
        self.alone_ok = [[t for t in range(m.n_trucks) if m.can[o][t]
                          and m.eval_truck(t, [(o, True), (o, False)]).ok]
                         for o in range(m.n_orders)]
        self.destroy_ops = {
            "random": self.d_random, "worst": self.d_worst, "related": self.d_related,
            "route": self.d_route, "free_truck": self.d_free_truck,
        }
        self.repair_ops = {"regret2": 2, "regret3": 3, "greedy": 1}

    # ------------------------------------------------------------- destroy
    def d_random(self, s: Insertion, q: int) -> set[int]:
        a = list(s.assigned())
        return set(self.rng.sample(a, min(q, len(a))))

    def d_worst(self, s: Insertion, q: int) -> set[int]:
        m = self.m
        cost = []
        for t, r in enumerate(s.routes):
            if not r:
                continue
            base = s.evals[t].km
            for o in {o for o, _ in r}:
                e = m.eval_truck(t, [x for x in r if x[0] != o])
                cost.append(((base - e.km) / m.o_val[o], o))
        cost.sort(reverse=True)
        out = set()
        while cost and len(out) < q:
            k = int(len(cost) * self.rng.random() ** 3)  # biased towards the worst
            out.add(cost.pop(k)[1])
        return out

    def _related(self, a: int, b: int) -> float:
        m = self.m
        (pa, da), (pb, db) = m.o_city[a], m.o_city[b]
        return m.km[pa][pb] + m.km[da][db]

    def d_related(self, s: Insertion, q: int) -> set[int]:
        a = list(s.assigned())
        if not a:
            return set()
        seed = self.rng.choice(a)
        a.sort(key=lambda o: self._related(seed, o))
        out = set()
        while a and len(out) < q:
            k = int(len(a) * self.rng.random() ** 4)
            out.add(a.pop(k))
        return out

    def d_route(self, s: Insertion, q: int) -> set[int]:
        used = [t for t, r in enumerate(s.routes) if r]
        out: set[int] = set()
        self.rng.shuffle(used)
        for t in used:
            if out and len(out) >= q:
                break
            out |= {o for o, _ in s.routes[t]}
        return out

    def d_free_truck(self, s: Insertion, q: int) -> set[int]:
        assigned = s.assigned()
        missing = [o for o in range(self.m.n_orders) if o not in assigned and self.alone_ok[o]]
        if not missing:
            return self.d_related(s, q)
        u = self.rng.choice(missing)
        trucks = list(self.alone_ok[u])
        self.rng.shuffle(trucks)
        out: set[int] = set()
        for k, t in enumerate(trucks):  # empty every truck that could serve u (within budget)
            route = {o for o, _ in s.routes[t]}
            if k and len(out) + len(route) > 2 * q:
                break
            out |= route
        # plus orders related to u, so there is room to re-route around it
        rest = sorted(assigned - out, key=lambda o: self._related(u, o))
        out |= set(rest[:max(0, q - len(out))])
        return out

    # ------------------------------------------------------------- main loop
    def run(self, start: Insertion, time_limit: float = 60.0, q_frac=(0.05, 0.25),
            log_every: float = 5.0, verbose: bool = True) -> ALNSResult:
        m, rng = self.m, self.rng
        cur = start.copy()
        best = start.copy()
        cur_s = best_s = cur.score()
        temp = PITemperature()
        dw = {k: 1.0 for k in self.destroy_ops}
        rw = {k: 1.0 for k in self.repair_ops}
        seg_score = {k: 0.0 for k in (*dw, *rw)}
        seg_uses = {k: 0 for k in (*dw, *rw)}
        stats = {k: {"uses": 0, "best": 0} for k in (*dw, *rw)}
        hist = []
        pool: dict[int, set] = {t: set() for t in range(m.n_trucks)}

        def record(sol: Insertion) -> None:
            for t, r in enumerate(sol.routes):
                if r and len(pool[t]) < 5000:
                    pool[t].add(tuple(r))

        record(start)
        t0 = time.perf_counter()
        last_log = 0.0
        it = 0
        since_best = 0
        n_assigned = lambda s: len(s.assigned())  # noqa: E731
        while True:
            el = time.perf_counter() - t0
            if el >= time_limit:
                break
            progress = el / time_limit
            it += 1
            d = rng.choices(list(dw), weights=list(dw.values()))[0]
            r = rng.choices(list(rw), weights=list(rw.values()))[0]
            n_ass = n_assigned(cur)
            lo, hi = max(2, int(q_frac[0] * n_ass)), max(3, int(q_frac[1] * n_ass))
            q = rng.randint(lo, min(hi, 60))

            cand = cur.copy()
            removed = self.destroy_ops[d](cand, q)
            cand.remove(removed)
            todo = [o for o in range(m.n_orders) if o not in cand.assigned()]
            regret_insertion(m, k=self.repair_ops[r], orders=todo, ins=cand, topn=self.topn,
                             noise=0.2, rng=rng)
            new_s = cand.score()

            reward = 0.0
            worse_accepted = False
            if new_s > best_s + 1e-9:
                best, best_s = cand.copy(), new_s
                reward = SIGMA_BEST
                stats[d]["best"] += 1
                stats[r]["best"] += 1
                since_best = 0
            else:
                since_best += 1
            if new_s > cur_s + 1e-9:
                cur, cur_s = cand, new_s
                reward = max(reward, SIGMA_BETTER)
            elif new_s < cur_s - 1e-3:  # only meaningful deteriorations drive the PI loop
                if rng.random() < math.exp((new_s - cur_s) / temp.T):
                    cur, cur_s = cand, new_s
                    reward = SIGMA_ACCEPT
                    worse_accepted = True
                temp.update(worse_accepted, progress)
            if reward:  # accepted or new best: keep its routes
                record(cand)
            for k in (d, r):
                seg_score[k] += reward
                seg_uses[k] += 1
                stats[k]["uses"] += 1

            if it % 50 == 0:  # weight update per segment
                for w in (dw, rw):
                    for k in w:
                        if seg_uses[k]:
                            w[k] = max(0.05, 0.8 * w[k] + 0.2 * seg_score[k] / seg_uses[k])
                        seg_score[k], seg_uses[k] = 0.0, 0
            if since_best > 400:  # restart from the best
                cur, cur_s, since_best = best.copy(), best_s, 0

            hist.append({"it": it, "t": round(el, 2), "cur": round(cur_s, 3),
                         "best": round(best_s, 3), "T": round(temp.T, 4),
                         "acc": round(temp.ema, 3), "op": d, "rep": r})
            if verbose and el - last_log >= log_every:
                last_log = el
                print(f"  {el:6.1f}s it={it:6d} best={best_s:8.3f} cur={cur_s:8.3f} "
                      f"T={temp.T:7.3f} acc={temp.ema:.3f} orders={n_assigned(best)}/{m.n_orders}",
                      flush=True)
        return ALNSResult(best, hist, {"stats": stats, "destroy_w": dw, "repair_w": rw}, it, pool)
