"""Probe plans for simulator rules the existing fixtures never exercise.

For each open question we search (with the local simulator) for a plan whose
outcome depends on the answer, then send it to Simulate + Score and store it as
tests/fixtures/<scenario>/<probe>.json, next to the existing fixtures.

Open questions:
- partial value for 1..60 min lateness (pickup late, delivery late, both late)
- which idle time counts as a 45-min break: waiting alone (current), any
  off-driving time at the stop(s) incl. service, or waiting never
- order_assigned_multiple_times: which truck keeps the order
- duplicate_delivery

Never touches scenario_competitive.

Usage:  uv run python scripts/probe_rules.py            # dry run: show probes
        uv run python scripts/probe_rules.py --send     # send and save fixtures
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import nos.simulator as S
from nos.data import load_scenario

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
SCENARIOS = ["scenario_middle", "scenario_big"]
TRIES = 40000


def P(o):
    return {"action": "pickup", "order": o}


def D(o):
    return {"action": "delivery", "order": o}


# ---- break-rule variants (monkeypatched _Clock.idle) ----
_orig_idle = S._Clock.idle


def _idle_offtime(self, minutes):          # any off-driving time at the stop counts
    self.t += minutes
    self.off += minutes
    if self.off >= S.BREAK_MIN:
        self.cont = 0
    if self.off >= S.REST_MIN:
        self.daily = 0


def _idle_never(self, minutes):            # waiting never counts as a break
    self.t += minutes
    self.off += minutes


VARIANTS = {"wait_only": _orig_idle, "offtime": _idle_offtime, "never": _idle_never}


def run(sc, plan, variant="wait_only"):
    S._Clock.idle = VARIANTS[variant]
    try:
        return S.simulate(sc, plan)
    finally:
        S._Clock.idle = _orig_idle


def schedule_sig(res):
    return [(s["arrival_min"], s["departure_min"]) for t in res.trucks for s in t["schedule"]]


def compatible(o, t):
    return o.required_truck_type in (None, t.type) and o.weight_kg <= t.capacity_kg


def random_plan(sc, rng, targets):
    """One truck: a few random orders as prefix, then a target order."""
    t = rng.choice(list(sc.trucks.values()))
    ok = [o.id for o in sc.orders.values() if compatible(sc.orders[o.id], t)]
    tg = [o for o in targets if compatible(sc.orders[o], t)]
    if not tg:
        return None
    seq = rng.sample(ok, k=min(len(ok), rng.randint(0, 4)))
    target = rng.choice(tg)
    if target in seq:
        seq.remove(target)
    stops = []
    for o in seq:
        stops += [P(o), D(o)]
    stops += [P(target), D(target)]
    return t.id, target, {t.id: stops}


def find_lateness(sc, rng):
    """Plans with 1..60 min lateness on pickup only / delivery only / both."""
    tw = [o.id for o in sc.orders.values() if o.pickup_window or o.delivery_window]
    found = {}
    for _ in range(TRIES):
        r = random_plan(sc, rng, tw)
        if not r:
            continue
        tid, target, plan = r
        res = run(sc, plan)
        sched = res.trucks[0]["schedule"]
        lp = next(s["late_min"] for s in sched if s["order"] == target and s["action"] == "pickup")
        ld = next(s["late_min"] for s in sched if s["order"] == target and s["action"] == "delivery")
        # every other order must be on time so the target alone explains the result
        others = sum(s["late_min"] for s in sched if s["order"] != target)
        if others:
            continue
        kind = ("late_pickup" if 0 < lp <= 60 and ld == 0 else
                "late_delivery" if lp == 0 and 0 < ld <= 60 else
                "late_both" if 0 < lp <= 60 and 0 < ld <= 60 else
                "late_pickup_too_much" if lp > 60 and ld == 0 else None)
        if kind and kind not in found:
            found[kind] = plan
        if len(found) == 4:
            break
    return found


def find_break_rule(sc, rng):
    """Plans where the three break-rule variants give three different schedules."""
    tw = [o.id for o in sc.orders.values() if o.pickup_window or o.delivery_window]
    found = {}
    for _ in range(TRIES):
        r = random_plan(sc, rng, tw)
        if not r:
            continue
        _, _, plan = r
        a, b, c = (schedule_sig(run(sc, plan, v)) for v in VARIANTS)
        if a != b and "break_offtime" not in found:
            found["break_offtime"] = plan
        if a != c and "break_wait" not in found:
            found["break_wait"] = plan
        if len(found) == 2:
            break
    # same-city consecutive stops: 2 x 30 min service = 60 min off-driving
    return found


def find_same_city(sc, rng):
    """Two stops in the same city right after a near-270-min drive."""
    for _ in range(TRIES):
        t = rng.choice(list(sc.trucks.values()))
        ok = [o for o in sc.orders.values() if compatible(o, t)
              and not o.pickup_window and not o.delivery_window]
        a, b = rng.sample(ok, 2)
        if a.delivery_city != b.pickup_city:
            continue
        plan = {t.id: [P(a.id), D(a.id), P(b.id), D(b.id)]}
        if schedule_sig(run(sc, plan, "wait_only")) != schedule_sig(run(sc, plan, "offtime")):
            return {"break_same_city": plan}
    return {}


def fixed_probes(sc):
    trucks = list(sc.trucks)
    free = [o.id for o in sc.orders.values() if not o.required_truck_type
            and not o.pickup_window and not o.delivery_window]
    o1, o2 = free[0], free[1]
    return {
        # same order on two trucks; dict order puts the higher truck id first
        "multi_assigned": {trucks[1]: [P(o1), D(o1)], trucks[0]: [P(o1), D(o1), P(o2), D(o2)]},
        "duplicate_delivery": {trucks[0]: [P(o1), D(o1), D(o1), P(o2), D(o2)]},
    }


def main() -> None:
    send = "--send" in sys.argv
    rng = random.Random(7)
    api = None
    if send:
        from nos.api import GruberAPI
        api = GruberAPI()
    for sid in SCENARIOS:
        assert sid != "scenario_competitive"
        sc = load_scenario(sid)
        fx_fp = json.loads((FIXTURES / sid / "scenario.json").read_text())["meta"]["fingerprint"]
        if fx_fp != sc.fingerprint:
            sys.exit(f"{sid}: server data changed since fixtures were recorded - re-collect first")
        probes = {**find_lateness(sc, rng), **find_break_rule(sc, rng), **find_same_city(sc, rng)}
        if sid == SCENARIOS[0]:
            probes |= fixed_probes(sc)
        for name, plan in probes.items():
            local = {v: run(sc, plan, v) for v in VARIANTS}
            print(f"{sid:16s} {name:22s} stops={sum(map(len, plan.values())):2d} "
                  + " ".join(f"{v}={r.score:.2f}" for v, r in local.items()))
            if send:
                sim = api.simulate(sid, plan)
                score = api.score(sid, plan)
                (FIXTURES / sid / f"{name}.json").write_text(json.dumps(
                    {"plan": plan, "simulate": sim, "score": score}, indent=1))
                print(f"{'':16s} -> api score={score['score']:.2f}")


if __name__ == "__main__":
    main()
