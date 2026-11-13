"""Minute-by-minute activity timeline of a plan, for the Gantt chart and the map animation.

Replays each truck with exactly the simulator's rules and emits segments
{kind, start, end, ...}: kind in drive | break | rest | wait | service. A drive
segment covers the fraction [f0, f1] of the leg from `from` to `to`, so the
front end can interpolate the truck position (straight line between cities).
`check_against` asserts the replay ends every stop at the simulator's minute.
"""

from __future__ import annotations

from .data import Scenario
from .simulator import (BREAK_AFTER, BREAK_MIN, REST_AFTER, REST_MIN, SERVICE_MIN, driving_min)


def truck_timeline(sc: Scenario, tid: str, stops: list[dict]) -> list[dict]:
    truck = sc.trucks[tid]
    city = truck.start_city
    now = cont = daily = off = 0
    load = 0
    on_board: list[str] = []
    seg: list[dict] = []

    def add(kind, start, end, **kw):
        if end > start:
            seg.append({"kind": kind, "start": start, "end": end, **kw})

    for st in stops:
        o = sc.orders[st["order"]]
        pick = st["action"] == "pickup"
        target = o.pickup_city if pick else o.delivery_city
        km = sc.km(city, target)
        if km:
            total = driving_min(km)
            done = 0
            while done < total:
                if daily >= REST_AFTER:
                    p = max(0, REST_MIN - off)
                    add("rest", now, now + p, at=(city, target, done / total))
                    now += p
                    cont = daily = 0
                elif cont >= BREAK_AFTER:
                    p = max(0, BREAK_MIN - off)
                    add("break", now, now + p, at=(city, target, done / total))
                    now += p
                    cont = 0
                off = 0
                step = min(total - done, BREAK_AFTER - cont, REST_AFTER - daily)
                add("drive", now, now + step, **{"from": city, "to": target, "f0": done / total,
                                                 "f1": (done + step) / total, "km": km * step / total,
                                                 "loaded": bool(on_board), "load_kg": load})
                now += step
                cont += step
                daily += step
                done += step
            city = target
        win = o.pickup_window if pick else o.delivery_window
        if win is not None and now < win.start:
            add("wait", now, win.start, city=city, order=o.id)
            off += win.start - now
            now = win.start
            if off >= BREAK_MIN:
                cont = 0
            if off >= REST_MIN:
                daily = 0
        add("service", now, now + SERVICE_MIN, city=city, order=o.id, action=st["action"])
        now += SERVICE_MIN
        off += SERVICE_MIN
        if off >= BREAK_MIN:
            cont = 0
        if off >= REST_MIN:
            daily = 0
        if pick:
            on_board.append(o.id)
            load += o.weight_kg
        else:
            on_board.remove(o.id)
            load -= o.weight_kg
    for s in seg:
        if "at" in s:
            a, b, f = s.pop("at")
            s.update({"from": a, "to": b, "f": f})
    return seg


def check_against(timeline: list[dict], schedule: list[dict]) -> None:
    ends = [s["end"] for s in timeline if s["kind"] == "service"]
    want = [s["departure_min"] for s in schedule]
    assert ends == want, f"timeline drifts from simulator: {ends[:5]} vs {want[:5]}"
