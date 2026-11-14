"""What-if: a truck breaks down mid-plan and Delivello replans the rest (offline, no API calls).

Model of a breakdown of truck B in city C right after its stop k (minute T = that stop's departure):
- Nothing before T can change. Every other truck keeps the stops it has done and the stop it is
  driving to at T (its "frozen prefix"); new stops can only go after it.
- B stops for good at C. Cargo on board is not lost: it waits in C and becomes a rescue order
  (same id, value, weight and delivery window, pickup city C), to be collected within 24 h of T.
- Orders B had not picked up yet are free again. No order can be picked up before T (dispatch only
  learns at T), so every order not yet picked up gets a pickup window starting at T.
All plans are scored with the exact simulator on that modified scenario, so before / after are
comparable:
  no reaction  B's orders are simply lost, everybody else drives on as planned;
  Delivello   regret insertion of B's orders after the frozen prefixes (seconds), then a second pass
               (no truck may finish later than the original plan does)
               that also releases every order nobody has picked up yet and re-inserts all of them;
               the better one is kept.

Usage:
  uv run python scripts/disruption.py scan  [scenario]          # rank candidate breakdowns
  uv run python scripts/disruption.py build [scenario] T09:5 ... # write web/data/whatif_<n>.js
  uv run python scripts/disruption.py roads [--all]              # road geometry for those plans (OSRM);
                                                                 # --all: every competitive city pair (live)
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from nos.construct import Insertion, regret_insertion
from nos.data import TimeWindow, load_scenario
from nos.evaluate import Model
from nos.plans import RESULTS_DIR, best_plan
from nos.simulator import simulate
from nos.timeline import check_against, truck_timeline

ROOT = Path(__file__).resolve().parents[1]
OPEN_END = 10_000_000          # "no deadline" end of the pickup window that starts at T
RESCUE_MIN = 24 * 60           # cargo of the broken truck must be collected within 24 h


class Frozen(Insertion):
    """Insertion that never puts a stop before position frozen[t] of truck t, and never lets a truck
    finish later than `limit` (the original plan's last minute: a breakdown must not stretch the plan)."""

    def __init__(self, m, routes, frozen, limit=None):
        super().__init__(m, routes)
        self.frozen = frozen
        self.limit = limit

    def candidates(self, t, o, topn=None):
        c = super().candidates(t, o, topn)
        return c if self.limit is None else [x for x in c if x[1].finish <= self.limit]

    def positions(self, t, o, topn):
        f = self.frozen[t]
        if f == 0:
            return super().positions(t, o, topn)
        n = len(self.routes[t])
        cand = [(i, j) for i in range(f, n + 1) for j in range(i, n + 1)]
        if topn is None or len(cand) <= topn:
            return cand
        allp = super().positions(t, o, None if (n + 1) * (n + 2) // 2 <= 4 * topn else 4 * topn)
        good = [(i, j) for i, j in allp if i >= f]
        return good or cand[:topn]

    def copy(self):
        c = super().copy()
        c.__class__ = Frozen
        c.frozen, c.limit = self.frozen, self.limit
        return c


def breakdown(sc, plan: dict, tid: str, k: int):
    """Modified scenario, frozen stop counts and the plan pieces for a breakdown of tid after stop k."""
    sim = simulate(sc, plan)
    sched = {r["truck"]: r["schedule"] for r in sim.trucks}
    s = sched[tid][k]
    T, C = s["departure_min"], s["city"]
    picked = set()                                  # orders picked up by anybody before T
    frozen_n = {}
    for t, stops in sched.items():
        n = sum(1 for x in stops if x["departure_min"] <= T) if t != tid else k + 1
        if t != tid and n < len(stops):
            n += 1                                  # the stop it is driving to (or serving) at T
        frozen_n[t] = n
        picked |= {x["order"] for x in stops[:n] if x["action"] == "pickup"}
    b_done = sched[tid][:k + 1]
    delivered_b = {x["order"] for x in b_done if x["action"] == "delivery"}
    onboard = [x["order"] for x in b_done if x["action"] == "pickup" and x["order"] not in delivered_b]
    waiting = [x["order"] for x in sched[tid][k + 1:] if x["action"] == "pickup"]

    orders = dict(sc.orders)
    for oid, o in sc.orders.items():
        if oid in onboard:                          # rescue: cargo waits in C from T
            orders[oid] = replace(o, pickup_city=C, pickup_window=TimeWindow(T, T + RESCUE_MIN))
        elif oid not in picked:                     # nobody can pick it up before dispatch knows
            w = o.pickup_window
            orders[oid] = replace(o, pickup_window=TimeWindow(max(T, w.start) if w else T,
                                                              w.end if w else OPEN_END))
    sc2 = replace(sc, orders=orders)
    # plan with B cut at C; B's pickups of the on-board cargo are dropped (a rescue truck collects it)
    base = {t: list(p) for t, p in plan.items()}
    base[tid] = [x for x in plan[tid][:k + 1] if not (x["action"] == "pickup" and x["order"] in onboard)]
    info = {"truck": tid, "stop": k, "t": T, "city": C, "city_name": sc.cities[C].name,
            "onboard": onboard, "waiting": waiting}
    return sc2, frozen_n, base, info


def replan(sc2, frozen_n: dict, base: dict, info: dict, full: bool = True, limit: int | None = None):
    m = Model(sc2)
    oi = {o: i for i, o in enumerate(m.order_ids)}
    routes = [[(oi[s["order"]], s["action"] == "pickup") for s in base.get(t, [])] for t in m.truck_ids]
    frozen = [frozen_n.get(t, 0) if t != info["truck"] else len(routes[m.truck_ids.index(t)])
              for t in m.truck_ids]
    for ti, t in enumerate(m.truck_ids):
        if t != info["truck"]:
            frozen[ti] = min(frozen[ti], len(routes[ti]))
    b = m.truck_ids.index(info["truck"])
    orphans = [oi[o] for o in info["onboard"] + info["waiting"]]

    def cut_b(ins):                                 # the broken truck takes nothing new
        for o in range(m.n_orders):
            m.can[o][b] = False
        return ins

    t0 = time.perf_counter()
    cut_b(None)
    quick = Frozen(m, [list(r) for r in routes], frozen, limit)
    regret_insertion(m, k=3, orders=orphans, ins=quick)
    quick_s = time.perf_counter() - t0
    best, how = quick, "insert"
    if full:
        wide = Frozen(m, [list(r) for r in routes], frozen, limit)
        free = set(orphans)
        for ti, r in enumerate(wide.routes):
            free |= {o for o, _ in r[frozen[ti]:]
                     if not any(o == p and pk for p, pk in r[:frozen[ti]])}
        wide.remove(free - set(orphans))
        regret_insertion(m, k=3, orders=sorted(free), ins=wide)
        if wide.score() > best.score():
            best, how = wide, "full"
    secs = time.perf_counter() - t0
    return m, best, how, quick_s, secs


def evaluate(sc2, plan):
    sim = simulate(sc2, plan)
    return sim, sim.score, sim.simulate["orders_fulfilled"]


def scan(sid: str) -> None:
    sc = load_scenario(sid)
    plan = best_plan(sid)["plan"]
    sim = simulate(sc, plan)
    limit = max(r["finish_min"] for r in sim.trucks)
    rows = []
    for r in sim.trucks:
        for k, s in enumerate(r["schedule"]):
            if not (2 * 1440 <= s["departure_min"] <= 8 * 1440) or s["action"] != "delivery":
                continue
            sc2, fz, base, info = breakdown(sc, plan, r["truck"], k)
            if len(info["onboard"]) + len(info["waiting"]) < 3:
                continue
            _, s0, n0 = evaluate(sc2, base)
            m, best, how, q, secs = replan(sc2, fz, base, info, full=False, limit=limit)
            s1 = best.score()
            served = {m.order_ids[o] for rr in best.routes for o, p in rr if not p}
            saved = sum(1 for o in info["onboard"] + info["waiting"] if o in served)
            rows.append((s1 - s0, r["truck"], k, info, s0, s1, saved, q))
    rows.sort(key=lambda x: -x[0])
    for gain, t, k, info, s0, s1, saved, q in rows[:15]:
        print(f"{t}:{k:<3d} day {1 + (info['t'] + 360) // 1440:2d} {info['city_name']:14s} "
              f"onboard {len(info['onboard'])} waiting {len(info['waiting']):2d}  "
              f"no reaction {s0:7.2f} -> Delivello {s1:7.2f} (+{gain:5.2f})  saved "
              f"{saved}/{len(info['onboard']) + len(info['waiting'])}  {q:.1f}s")


def dashboard(sc2, plan: dict, original: dict) -> dict:
    """Same contract as results/<s>/dashboard.json (what web/player.js plays)."""
    sim = simulate(sc2, plan)
    trucks = []
    for k, t in enumerate(sc2.trucks.values()):
        rep = next((r for r in sim.trucks if r["truck"] == t.id), None)
        stops = plan.get(t.id, [])
        tl = truck_timeline(sc2, t.id, stops) if stops else []
        if rep:
            check_against(tl, rep["schedule"])
        trucks.append({"id": t.id, "type": t.type, "capacity_kg": t.capacity_kg, "cost_per_km": t.cost_per_km,
                       "co2_per_km": t.co2_per_km, "start_city": t.start_city, "color_index": k,
                       "used": bool(stops), "metrics": {"finish_min": rep["finish_min"]} if rep else None,
                       "route": rep["route"] if rep else [t.start_city],
                       "stops": rep["schedule"] if rep else [], "timeline": tl})
    carrier, late = {}, {}
    for r in sim.trucks:
        for s in r["schedule"]:
            carrier[s["order"]] = r["truck"]
            late[s["order"]] = max(late.get(s["order"], 0), s["late_min"])
    orig_o = {o["id"]: o for o in original["orders"]}
    orders = []
    for o in sc2.orders.values():
        lm = late.get(o.id, 0)
        orders.append({**orig_o[o.id], "pickup_city": o.pickup_city, "truck": carrier.get(o.id),
                       "status": "unserved" if o.id not in carrier else ("late" if lm else "on_time"),
                       "late_min": lm, "direct_km": sc2.km(o.pickup_city, o.delivery_city)})
    return {**original, "trucks": trucks, "orders": orders,
            "time": {"minute_0": "Day 1 06:00",
                     "horizon_min": max((t["metrics"]["finish_min"] for t in trucks if t["metrics"]), default=0)},
            "kpis": {"score": sim.score, **sim.simulate, "breakdown": sim.breakdown,
                     "violations": len(sim.violations), "trucks_used": sum(t["used"] for t in trucks)},
            "search_history": []}


def build(sid: str, specs: list[str]) -> None:
    sc = load_scenario(sid)
    plan = best_plan(sid)["plan"]
    original = json.loads((RESULTS_DIR / sid / "dashboard.json").read_text())
    sim0 = simulate(sc, plan)
    s_orig, limit = sim0.score, max(r["finish_min"] for r in sim0.trucks)
    out = ROOT / "web" / "data"
    index = []
    for n, spec in enumerate(specs, 1):
        tid, k = spec.split(":")
        sc2, fz, base, info = breakdown(sc, plan, tid, int(k))
        _, s0, n0 = evaluate(sc2, base)
        m, best, how, q, secs = replan(sc2, fz, base, info, limit=limit)
        after = m.to_plan(best.routes)
        sim1, s1, n1 = evaluate(sc2, after)
        assert not sim1.violations, f"{spec}: replanned plan has violations {sim1.violations[:3]}"
        assert abs(s1 - best.score()) < 0.011, f"{spec}: simulator {s1} vs evaluator {best.score()}"
        served = {o["order"] for r in sim1.trucks for o in r["schedule"] if o["action"] == "delivery"}
        lost = [o for o in info["onboard"] + info["waiting"] if o not in served]
        helpers = sorted({t for t, st in after.items() for x in st
                          if x["order"] in info["onboard"] + info["waiting"] and t != tid})
        w = {**info, "day": 1 + (info["t"] + 360) // 1440, "score_planned": s_orig,
             "score_no_reaction": s0, "orders_no_reaction": n0, "score_nos": s1, "orders_nos": n1,
             "saved": len(info["onboard"]) + len(info["waiting"]) - len(lost), "lost": lost,
             "helpers": helpers, "replan_seconds": round(secs, 1), "method": how,
             "kind": "Vehicle breakdown", "label": "realistic scenario, not a recorded incident"}
        d = dashboard(sc2, after, original)
        js = (f"window.NOS_DATA=window.NOS_DATA||{{}};window.NOS_DATA[{json.dumps(sid)}]={json.dumps(d, separators=(',', ':'))};\n"
              f"window.NOS_WHATIF={json.dumps(w)};\n")
        (out / f"whatif_{n}.js").write_text(js)
        index.append({"n": n, "truck": tid, "day": w["day"], "city": info["city_name"]})
        print(f"whatif_{n}: {tid} breaks down in {info['city_name']} on day {w['day']}: "
              f"{len(info['onboard'])} on board + {len(info['waiting'])} waiting -> saved {w['saved']}, "
              f"lost {len(lost)}; score planned {s_orig:.2f} | no reaction {s0:.2f} | Delivello {s1:.2f} "
              f"({how}, {secs:.1f}s, helpers {', '.join(helpers)})")
    (out / "whatif_index.js").write_text("window.NOS_WHATIF_INDEX=" + json.dumps(index) + ";\n")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    args = sys.argv[2:]
    sid = args[0] if args and args[0].startswith("scenario_") else "scenario_competitive"
    specs = [a for a in args if ":" in a]
    if cmd == "scan":
        scan(sid)
    elif cmd == "build":
        build(sid, specs)
    elif cmd == "roads":
        whatif_roads(all_pairs="--all" in args)



def whatif_roads(all_pairs: bool = False) -> None:
    """Road geometry for city pairs only the replanned plans drive -> web/data/whatif_roads.js.

    Same OSRM source and cache as scripts/build_web.py (web/data/roads_cache.json); roads.js is left as it
    is, the what-if page merges this file on top of it. all_pairs: every pair of the competitive cities, so
    that live replans (scripts/live_server.py) never fall back to straight lines.
    """
    import re
    import urllib.request

    out = ROOT / "web" / "data"
    cache_f = out / "roads_cache.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    pairs, cities = set(), {}
    for f in sorted(out.glob("whatif_[0-9]*.js")):
        d = json.loads(re.search(r'\]=(\{.*\});\nwindow.NOS_WHATIF', f.read_text(), re.S).group(1))
        cities.update({c["id"]: (c["lon"], c["lat"]) for c in d["cities"]})
        for t in d["trucks"]:
            pairs |= {tuple(sorted((g["from"], g["to"]))) for g in t["timeline"] if g["kind"] == "drive"}
    if all_pairs:
        from itertools import combinations
        comp = json.loads((RESULTS_DIR / "scenario_competitive" / "dashboard.json").read_text())
        cities.update({c["id"]: (c["lon"], c["lat"]) for c in comp["cities"]})
        pairs |= {tuple(sorted(p)) for p in combinations([c["id"] for c in comp["cities"]], 2)}
    todo = [p for p in sorted(pairs) if "|".join(p) not in cache]
    print(f"what-if roads: {len(pairs)} pairs, {len(todo)} to fetch (~{len(todo)} s)")
    url = "https://router.project-osrm.org/route/v1/driving/{},{};{},{}?overview=simplified&geometries=geojson"
    for a, b in todo:
        try:
            req = urllib.request.Request(url.format(*cities[a], *cities[b]), headers={"User-Agent": "nos-demo/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.loads(r.read())
            if res.get("code") == "Ok":
                cache["|".join((a, b))] = [[round(x, 3), round(y, 3)] for x, y in res["routes"][0]["geometry"]["coordinates"]]
        except Exception as e:  # network hiccup: that pair stays a straight line
            print(f"  {a}-{b}: {e}")
        time.sleep(1.0)
    cache_f.write_text(json.dumps(cache, separators=(",", ":")))
    used = {k: v for k, v in cache.items() if tuple(k.split("|")) in pairs}
    (out / "whatif_roads.js").write_text("window.NOS_ROADS=Object.assign(window.NOS_ROADS||{}," +
                                         json.dumps(used, separators=(",", ":")) + ");\n")
    print(f"whatif_roads.js: {len(used)}/{len(pairs)} pairs with road geometry")


if __name__ == "__main__":
    main()
