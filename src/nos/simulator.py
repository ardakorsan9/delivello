"""Local re-implementation of the GRUBER Simulate + Score endpoints.

Goal: reproduce the official API output exactly (see docs/RULES.md and the
recorded responses in tests/fixtures/), so the optimizer can evaluate millions of
plans offline without spending API calls.

Time model per truck (state machine):
- `cont`  = driving minutes since the last 45-min break (or rest)
- `daily` = driving minutes since the last 11-h rest
A leg is driven in pieces; whenever more driving is needed and `daily` hit 540 an
11-h rest is inserted, else if `cont` hit 270 a 45-min break is inserted
(both mid-leg). Off-driving time between two legs (waiting + service, summed
over consecutive stops in the same city) of >= 45 min counts as a break.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .data import Scenario

SPEED_KMH = 70
SERVICE_MIN = 30
BREAK_AFTER, BREAK_MIN = 270, 45
REST_AFTER, REST_MIN = 540, 660
LATE_GRACE_MIN = 60
VIOLATION_PENALTY = 20
WEIGHTS = {"fulfillment": 0.50, "cost_efficiency": 0.20, "loaded_ratio": 0.15, "co2_efficiency": 0.15}


def driving_min(km: float) -> int:
    return math.ceil(km * 60 / SPEED_KMH)


@dataclass
class _Clock:
    """Driver clock: current minute plus the break/rest counters."""
    t: int = 0
    cont: int = 0
    daily: int = 0
    driving: int = 0
    pauses: int = 0  # break + rest minutes inserted while driving
    off: int = 0     # non-driving minutes (service/wait) since the last drive

    def drive(self, minutes: int) -> None:
        remaining = minutes
        while remaining > 0:
            # a pause that fell due at the end of the previous leg already
            # started at arrival: the stop's service/wait time counts toward it
            if self.daily >= REST_AFTER:
                self._pause(max(0, REST_MIN - self.off), rest=True)
            elif self.cont >= BREAK_AFTER:
                self._pause(max(0, BREAK_MIN - self.off), rest=False)
            self.off = 0
            step = min(remaining, BREAK_AFTER - self.cont, REST_AFTER - self.daily)
            self.t += step
            self.cont += step
            self.daily += step
            self.driving += step
            remaining -= step

    def _pause(self, minutes: int, rest: bool) -> None:
        self.t += minutes
        self.pauses += minutes
        self.cont = 0
        if rest:
            self.daily = 0

    def idle(self, minutes: int) -> None:
        """Waiting or service at a stop. All off-driving time since the last leg
        adds up: >= 45 min counts as a break (API-verified: two same-city
        services = 60 min reset the counter). The >= 660 rest reset is assumed."""
        self.t += minutes
        self.off += minutes
        if self.off >= BREAK_MIN:
            self.cont = 0
        if self.off >= REST_MIN:
            self.daily = 0


@dataclass
class _OrderState:
    truck: str
    picked: bool = False
    delivered: bool = False
    rejected: bool = False
    late: int = 0          # max lateness (min) over its stops
    type_ok: bool = True


@dataclass
class SimResult:
    simulate: dict
    violations: list[dict]
    score: float
    breakdown: dict
    trucks: list[dict] = field(default_factory=list)


def _viol(rule: str, truck: str, order: str | None) -> dict:
    return {"rule": rule, "truck": truck, "order": order}


def simulate(sc: Scenario, plan: dict[str, list[dict]]) -> SimResult:
    violations: list[dict] = []
    owner: dict[str, str] = {}          # order -> first truck that uses it
    states: dict[str, _OrderState] = {}
    truck_reports: list[dict] = []

    for tid, stops in plan.items():
        truck = sc.trucks.get(tid)
        if truck is None:
            violations.append(_viol("unknown_truck", tid, None))
            continue
        clock = _Clock()
        city = truck.start_city
        route = [city]
        load = 0
        max_load = 0
        on_board: set[str] = set()
        km_tot = km_loaded = 0.0
        load_km = 0.0  # kg*km, for utilization
        late_sum = 0
        schedule = []

        for stop in stops:
            action, oid = stop.get("action"), stop.get("order")
            order = sc.orders.get(oid)
            if order is None:
                violations.append(_viol("unknown_order", tid, oid))
                continue
            if action not in ("pickup", "delivery"):
                violations.append(_viol("unknown_action", tid, oid))
                continue
            if owner.setdefault(oid, tid) != tid:
                violations.append(_viol("order_assigned_multiple_times", tid, oid))
                continue
            st = states.setdefault(oid, _OrderState(tid))

            wrong_type = bool(order.required_truck_type) and order.required_truck_type != truck.type
            if action == "pickup":
                if st.picked or st.rejected:
                    violations.append(_viol("duplicate_pickup", tid, oid))
                    continue
                if wrong_type:
                    violations.append(_viol("truck_type_mismatch", tid, oid))
                    st.type_ok = False
                if load + order.weight_kg > truck.capacity_kg:
                    violations.append(_viol("capacity_exceeded", tid, oid))
                    st.rejected = True
                    continue
                target, window = order.pickup_city, order.pickup_window
            else:
                if st.delivered:
                    violations.append(_viol("duplicate_delivery", tid, oid))
                    continue
                if st.rejected:
                    continue  # delivery of a rejected pickup is ignored
                if not st.picked:
                    if wrong_type:  # the API also flags the type on an early delivery
                        violations.append(_viol("truck_type_mismatch", tid, oid))
                    violations.append(_viol("delivery_before_pickup", tid, oid))
                    continue
                target, window = order.delivery_city, order.delivery_window

            # drive
            km = sc.km(city, target)
            if km:
                clock.drive(driving_min(km))
                km_tot += km
                if on_board:
                    km_loaded += km
                    load_km += km * load
                route.append(target)
            city = target
            arrival = clock.t
            wait = late = 0
            if window is not None:
                if arrival < window.start:
                    wait = window.start - arrival
                    clock.idle(wait)
                elif arrival > window.end:
                    late = arrival - window.end
            clock.idle(SERVICE_MIN)
            st.late = max(st.late, late)
            late_sum += late
            schedule.append({"action": action, "order": oid, "city": target, "arrival_min": arrival,
                             "wait_min": wait, "late_min": late, "departure_min": clock.t})

            if action == "pickup":
                st.picked = True
                on_board.add(oid)
                load += order.weight_kg
                max_load = max(max_load, load)
            else:
                st.delivered = True
                on_board.discard(oid)
                load -= order.weight_kg

        for oid in on_board:
            violations.append(_viol("pickup_without_delivery", tid, oid))

        truck_reports.append({
            "truck": tid, "route": route, "total_km": km_tot, "loaded_km": km_loaded,
            "empty_km": km_tot - km_loaded, "cost": round(km_tot * truck.cost_per_km, 2),
            "co2": round(km_tot * truck.co2_per_km, 2), "max_load_kg": max_load,
            "utilization": round(load_km / (truck.capacity_kg * km_tot), 4) if km_tot else 0.0,
            "finish_min": clock.t, "driving_min": clock.driving,
            "break_and_rest_min": clock.pauses, "schedule": schedule,
            "_util_km": load_km / truck.capacity_kg, "_late": late_sum,
        })

    # --- order outcomes ---
    value_total = sum(o.value for o in sc.orders.values())
    fulfilled = 0
    value_ok = value_lost = 0.0
    late_orders = too_late = 0
    late_min_total = penalized_late = 0
    for oid, st in states.items():
        o = sc.orders[oid]
        if not st.delivered or not st.type_ok:
            continue
        if st.late > 0:
            late_orders += 1
        if st.late > LATE_GRACE_MIN:
            too_late += 1
            continue
        frac = 1 - 0.5 * st.late / LATE_GRACE_MIN
        fulfilled += 1
        value_ok += o.value * frac
        value_lost += o.value * (1 - frac)
        penalized_late += st.late

    total_km = sum(t["total_km"] for t in truck_reports)
    loaded_km = sum(t["loaded_km"] for t in truck_reports)
    total_cost = round(sum(t["cost"] for t in truck_reports), 2)
    total_co2 = round(sum(t["co2"] for t in truck_reports), 2)
    # fleet utilization = km-weighted mean of per-truck utilization
    util = round(sum(t["_util_km"] for t in truck_reports) / total_km, 4) if total_km else 0.0
    late_min_total = sum(t["_late"] for t in truck_reports)  # over all executed stops
    for t in truck_reports:
        del t["_util_km"], t["_late"]

    sim = {
        "total_km": total_km, "loaded_km": loaded_km, "empty_km": total_km - loaded_km,
        "total_cost": total_cost, "total_co2": total_co2,
        "orders_fulfilled": fulfilled, "orders_total": len(sc.orders),
        "value_fulfilled": round(value_ok, 4), "value_lost_to_lateness": round(value_lost, 4),
        "value_total": value_total, "truck_utilization": util,
        "orders_late": late_orders, "orders_too_late": too_late,
        "total_late_min": late_min_total, "penalized_late_min": penalized_late,
    }

    # --- score ---
    direct = sum(sc.km(o.pickup_city, o.delivery_city) for o in sc.orders.values())
    ref_km = direct * fulfilled / len(sc.orders)
    ref_cost = ref_km * min(t.cost_per_km for t in sc.trucks.values())
    ref_co2 = ref_km * min(t.co2_per_km for t in sc.trucks.values())
    comp = {
        "fulfillment": 100 * value_ok / value_total if value_total else 0.0,
        "cost_efficiency": 100 * min(1.0, ref_cost / total_cost) if total_cost else 0.0,
        "loaded_ratio": 100 * loaded_km / total_km if total_km else 0.0,
        "co2_efficiency": 100 * min(1.0, ref_co2 / total_co2) if total_co2 else 0.0,
    }
    penalty = VIOLATION_PENALTY * len(violations)
    score = 10 * sum(WEIGHTS[k] * v for k, v in comp.items()) - penalty
    breakdown = {k: round(v, 2) for k, v in comp.items()} | {
        "penalty": penalty,
        # informational: score points lost to lateness (already inside fulfillment)
        "late_penalty": round(10 * WEIGHTS["fulfillment"] * 100 * value_lost / value_total, 2)
        if value_total else 0}
    return SimResult(sim, violations, round(score, 2), breakdown, truck_reports)
