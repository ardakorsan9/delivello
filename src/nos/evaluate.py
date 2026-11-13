"""Fast incremental evaluation for the optimizer.

`simulator.simulate` reproduces the API in full detail (violations, schedules).
The optimizer only ever builds *valid* plans, so here a truck route is a list of
(order_index, is_pickup) stops evaluated on integer arrays, and a plan's score is
computed from per-truck aggregates. tests/test_evaluate.py checks that this agrees
with `simulate` on random valid plans.

The score is a function of five sums (km, loaded km, cost, co2, value, count), so
changing one truck only needs that truck's route re-evaluated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .data import Scenario
from .simulator import (BREAK_AFTER, BREAK_MIN, LATE_GRACE_MIN, REST_AFTER, REST_MIN,
                        SERVICE_MIN, SPEED_KMH, WEIGHTS)

INF = 10**9
Stop = tuple[int, bool]  # (order index, is_pickup)


@dataclass(frozen=True)
class TruckEval:
    km: float = 0.0
    loaded: float = 0.0
    cost: float = 0.0
    co2: float = 0.0
    value: float = 0.0     # value fulfilled (after lateness)
    count: int = 0         # orders fulfilled
    ok: bool = True        # capacity respected and no stop more than 60 min late
    finish: int = 0


EMPTY = TruckEval()


class Model:
    """Scenario compiled to index-based arrays."""

    def __init__(self, sc: Scenario):
        self.sc = sc
        self.order_ids = list(sc.orders)
        self.truck_ids = list(sc.trucks)
        orders = [sc.orders[o] for o in self.order_ids]
        trucks = [sc.trucks[t] for t in self.truck_ids]
        self.dist = sc.dist
        self.drive = [[math.ceil(d * 60 / SPEED_KMH) for d in row] for row in sc.dist.tolist()]
        self.km = sc.dist.tolist()
        ci = sc.idx
        self.o_city = [(ci[o.pickup_city], ci[o.delivery_city]) for o in orders]
        self.o_w = [o.weight_kg for o in orders]
        self.o_val = [o.value for o in orders]
        self.o_tw = [((o.pickup_window.start, o.pickup_window.end) if o.pickup_window else None,
                      (o.delivery_window.start, o.delivery_window.end) if o.delivery_window else None)
                     for o in orders]
        self.t_start = [ci[t.start_city] for t in trucks]
        self.t_cap = [t.capacity_kg for t in trucks]
        self.t_cost = [t.cost_per_km for t in trucks]
        self.t_co2 = [t.co2_per_km for t in trucks]
        self.can = [[o.required_truck_type in (None, t.type) and o.weight_kg <= t.capacity_kg
                     for t in trucks] for o in orders]
        self.n_orders, self.n_trucks = len(orders), len(trucks)
        self.value_total = sum(self.o_val)
        direct = sum(self.km[a][b] for a, b in self.o_city)
        self.ref_km_per_order = direct / self.n_orders
        self.min_cost = min(self.t_cost)
        self.min_co2 = min(self.t_co2)

    # ---------------------------------------------------------------- truck
    def eval_truck(self, t: int, stops: list[Stop]) -> TruckEval:
        if not stops:
            return EMPTY
        km_m, dr_m = self.km, self.drive
        o_city, o_w, o_tw = self.o_city, self.o_w, self.o_tw
        city = self.t_start[t]
        cap = self.t_cap[t]
        now = cont = daily = off = 0
        load = 0
        on = 0  # orders on board
        km = loaded = 0.0
        late = {}
        ok = True
        for o, pick in stops:
            target = o_city[o][0 if pick else 1]
            d = km_m[city][target]
            if d:
                rem = dr_m[city][target]
                while rem > 0:
                    if daily >= REST_AFTER:
                        p = REST_MIN - off
                        now += p if p > 0 else 0
                        cont = daily = 0
                    elif cont >= BREAK_AFTER:
                        p = BREAK_MIN - off
                        now += p if p > 0 else 0
                        cont = 0
                    off = 0
                    step = min(rem, BREAK_AFTER - cont, REST_AFTER - daily)
                    now += step
                    cont += step
                    daily += step
                    rem -= step
                km += d
                if on:
                    loaded += d
                city = target
            win = o_tw[o][0 if pick else 1]
            if win is not None:
                if now < win[0]:
                    w = win[0] - now
                    now += w
                    off += w
                    if off >= BREAK_MIN:
                        cont = 0
                    if off >= REST_MIN:
                        daily = 0
                elif now > win[1]:
                    lt = now - win[1]
                    if lt > LATE_GRACE_MIN:
                        ok = False
                    if lt > late.get(o, 0):
                        late[o] = lt
            now += SERVICE_MIN
            off += SERVICE_MIN
            if off >= BREAK_MIN:
                cont = 0
            if off >= REST_MIN:
                daily = 0
            if pick:
                load += o_w[o]
                on += 1
                if load > cap:
                    ok = False
            else:
                load -= o_w[o]
                on -= 1
        value = 0.0
        count = 0
        for o, pick in stops:
            if not pick:
                lt = late.get(o, 0)
                if lt <= LATE_GRACE_MIN:
                    value += self.o_val[o] * (1 - 0.5 * lt / LATE_GRACE_MIN)
                    count += 1
        return TruckEval(km, loaded, km * self.t_cost[t], km * self.t_co2[t], value, count, ok, now)

    # ---------------------------------------------------------------- plan
    def score_parts(self, km, loaded, cost, co2, value, count) -> float:
        ref_km = self.ref_km_per_order * count
        s = WEIGHTS["fulfillment"] * 100 * value / self.value_total
        if cost:
            s += WEIGHTS["cost_efficiency"] * 100 * min(1.0, ref_km * self.min_cost / cost)
            s += WEIGHTS["co2_efficiency"] * 100 * min(1.0, ref_km * self.min_co2 / co2)
            s += WEIGHTS["loaded_ratio"] * 100 * loaded / km
        return 10 * s

    def score(self, evals: list[TruckEval]) -> float:
        return self.score_parts(*self.totals(evals))

    @staticmethod
    def totals(evals: list[TruckEval]) -> tuple:
        km = loaded = cost = co2 = value = 0.0
        count = 0
        for e in evals:
            km += e.km
            loaded += e.loaded
            cost += e.cost
            co2 += e.co2
            value += e.value
            count += e.count
        return km, loaded, cost, co2, value, count

    def to_plan(self, routes: list[list[Stop]]) -> dict:
        return {self.truck_ids[t]: [{"action": "pickup" if p else "delivery",
                                     "order": self.order_ids[o]} for o, p in r]
                for t, r in enumerate(routes) if r}
