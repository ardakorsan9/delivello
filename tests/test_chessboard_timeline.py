"""Chessboard optimum, minute timeline and dashboard export."""
import json
from pathlib import Path

import pytest

from nos.chessboard import solve
from nos.data import scenario_from_dict
from nos.evaluate import Model
from nos.lagrange import lagrangian_bound
from nos.simulator import simulate
from nos.timeline import check_against, truck_timeline

FIX = Path(__file__).parent / "fixtures"


def scen(name):
    return scenario_from_dict(name, json.loads((FIX / name / "scenario.json").read_text()))


@pytest.mark.parametrize("name", ["scenario_middle", "scenario_big"])
def test_chessboard_valid_and_within_bound(name):
    sc = scen(name)
    m = Model(sc)
    r = solve(m, verbose=False)
    res = simulate(sc, m.to_plan(r.plan.routes))
    assert res.violations == [] and r.status == "OPTIMAL" and not r.truncated_trucks
    assert res.score <= lagrangian_bound(m).score_ub + 1e-6
    served = {s["order"] for t in res.trucks for s in t["schedule"]}
    # an unserved order without a window is always *feasible*: append it to a compatible
    # truck's route (it may still be left out because it lowers the score)
    oi = {o: k for k, o in enumerate(m.order_ids)}
    for oid in sc.orders:
        o = sc.orders[oid]
        if oid in served or o.pickup_window or o.delivery_window:
            continue
        u = oi[oid]
        assert any(m.eval_truck(t, r.plan.routes[t] + [(u, True), (u, False)]).ok
                   for t in range(m.n_trucks) if m.can[u][t])


@pytest.mark.parametrize("path", sorted(p for p in FIX.glob("*/*.json") if p.name != "scenario.json"),
                         ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_timeline_matches_simulator(path):
    fx = json.loads(path.read_text())
    if fx["score"]["validation"]["violations"]:
        pytest.skip("timeline is defined for valid plans")
    sc = scen(path.parent.name)
    res = simulate(sc, fx["plan"])
    for rep in res.trucks:
        tl = truck_timeline(sc, rep["truck"], fx["plan"][rep["truck"]])
        check_against(tl, rep["schedule"])
        assert tl[0]["start"] == 0 and tl[-1]["end"] == rep["finish_min"]
        assert all(a["end"] == b["start"] for a, b in zip(tl, tl[1:]))  # contiguous
        drive = sum(s["end"] - s["start"] for s in tl if s["kind"] == "drive")
        pause = sum(s["end"] - s["start"] for s in tl if s["kind"] in ("break", "rest"))
        assert drive == rep["driving_min"] and pause == rep["break_and_rest_min"]
