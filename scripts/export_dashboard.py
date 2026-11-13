"""Write results/<scenario>/dashboard.json for the web dashboard / demo video.

Contents (contract: docs/DASHBOARD_JSON.md): cities, trucks with per-stop
schedule and minute-level timeline (drive/break/rest/wait/service), orders with
status, KPIs and score breakdown, the proven window-order optimum, the
before/after stages (naive round robin -> chessboard -> final) and the ALNS
search history. Offline, no API calls.

Usage:  uv run python scripts/export_dashboard.py scenario_competitive [...]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from nos.chessboard import solve as chessboard
from nos.lagrange import lagrangian_bound
from nos.data import load_scenario
from nos.evaluate import Model
from nos.plans import RESULTS_DIR, best_plan
from nos.simulator import simulate
from nos.timeline import check_against, truck_timeline

VERSION = 1


def round_robin(sc) -> dict:
    trucks = list(sc.trucks.values())
    plan = {t.id: [] for t in trucks}
    for i, o in enumerate(sc.orders.values()):
        for k in range(len(trucks)):
            t = trucks[(i + k) % len(trucks)]
            if o.required_truck_type in (None, t.type) and o.weight_kg <= t.capacity_kg:
                plan[t.id] += [{"action": "pickup", "order": o.id}, {"action": "delivery", "order": o.id}]
                break
    return {k: v for k, v in plan.items() if v}


def stage(name, sim) -> dict:
    return {"name": name, "score": sim.score, "orders_fulfilled": sim.simulate["orders_fulfilled"],
            "breakdown": sim.breakdown, "total_km": sim.simulate["total_km"],
            "empty_km": sim.simulate["empty_km"]}


def tw(w):
    return {"from": w.start, "to": w.end} if w else None


def export(sid: str) -> dict:
    sc = load_scenario(sid)
    m = Model(sc)
    stored = best_plan(sid)
    if not stored or stored["meta"].get("fingerprint") != sc.fingerprint:
        raise SystemExit(f"{sid}: no best.json for the current data")
    plan = stored["plan"]
    sim = simulate(sc, plan)

    trucks = []
    for k, t in enumerate(sc.trucks.values()):
        rep = next((r for r in sim.trucks if r["truck"] == t.id), None)
        stops = plan.get(t.id, [])
        timeline = truck_timeline(sc, t.id, stops) if stops else []
        if rep:
            check_against(timeline, rep["schedule"])
        trucks.append({
            "id": t.id, "type": t.type, "capacity_kg": t.capacity_kg, "cost_per_km": t.cost_per_km,
            "co2_per_km": t.co2_per_km, "start_city": t.start_city, "color_index": k,
            "used": bool(stops),
            "metrics": {key: rep[key] for key in ("total_km", "loaded_km", "empty_km", "cost", "co2",
                                                  "max_load_kg", "utilization", "finish_min",
                                                  "driving_min", "break_and_rest_min")} if rep else None,
            "route": rep["route"] if rep else [t.start_city],
            "stops": rep["schedule"] if rep else [],
            "timeline": timeline,
        })

    carrier, late = {}, {}
    for r in sim.trucks:
        for s in r["schedule"]:
            carrier[s["order"]] = r["truck"]
            late[s["order"]] = max(late.get(s["order"], 0), s["late_min"])
    orders = []
    for o in sc.orders.values():
        lm = late.get(o.id, 0)
        status = "unserved" if o.id not in carrier else ("late" if lm else "on_time")
        orders.append({"id": o.id, "pickup_city": o.pickup_city, "delivery_city": o.delivery_city,
                       "weight_kg": o.weight_kg, "required_truck_type": o.required_truck_type,
                       "value": o.value, "pickup_window": tw(o.pickup_window),
                       "delivery_window": tw(o.delivery_window), "truck": carrier.get(o.id),
                       "status": status, "late_min": lm,
                       "direct_km": sc.km(o.pickup_city, o.delivery_city)})

    cb = chessboard(m, verbose=False)
    lag = lagrangian_bound(m)
    cb_sim = simulate(sc, m.to_plan(cb.plan.routes))
    stages = [stage("naive round robin", simulate(sc, round_robin(sc))),
              stage("chessboard (CP-SAT window placement + regret insertion)", cb_sim),
              stage("final (ALNS + set partitioning)", sim)]

    hist_file = RESULTS_DIR / sid / "alns_history.json"
    history = []
    if hist_file.exists():
        h = json.loads(hist_file.read_text())["history"]
        step = max(1, len(h) // 600)
        history = [{k: x[k] for k in ("it", "t", "best", "cur", "T", "acc")} for x in h[::step]]

    W = [o for o in sc.orders.values() if o.pickup_window or o.delivery_window]
    return {
        "version": VERSION, "scenario": sid, "fingerprint": sc.fingerprint,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "time": {"minute_0": "Day 1 06:00", "horizon_min": max((t["metrics"]["finish_min"]
                                                                for t in trucks if t["metrics"]), default=0)},
        "cities": [{"id": c.id, "name": c.name, "country": c.country, "lat": c.lat, "lon": c.lon}
                   for c in sc.cities.values()],
        "trucks": trucks,
        "orders": orders,
        "kpis": {"score": sim.score, **sim.simulate, "breakdown": sim.breakdown,
                 "violations": len(sim.violations), "trucks_used": sum(t["used"] for t in trucks)},
        "bounds": {"window_orders": len(W), "window_served": sum(1 for o in orders if o["status"] != "unserved"
                                                                 and (sc.orders[o["id"]].pickup_window
                                                                      or sc.orders[o["id"]].delivery_window)),
                   "window_max": cb.window_served, "window_max_proven": not cb.truncated_trucks,
                   "score_upper_bound": round(lag.score_ub, 2),
                   "fulfillment_upper_bound": round(lag.fulfillment_ub, 3)},
        "stages": stages,
        "search_history": history,
    }


def main() -> None:
    for sid in sys.argv[1:] or ["scenario_competitive"]:
        d = export(sid)
        out = RESULTS_DIR / sid / "dashboard.json"
        out.write_text(json.dumps(d, separators=(",", ":")))
        k = d["kpis"]
        print(f"{sid}: {out} ({out.stat().st_size / 1024:.0f} KB) score {k['score']} "
              f"orders {k['orders_fulfilled']}/{k['orders_total']} window {d['bounds']['window_served']}/"
              f"{d['bounds']['window_orders']} (max {d['bounds']['window_max']}) "
              f"stages {[round(s['score'], 1) for s in d['stages']]}")


if __name__ == "__main__":
    main()
