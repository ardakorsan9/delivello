"""Lagrangian bound: valid (>= integer optimum and >= any plan) and equal to the LP bound."""
import json
from pathlib import Path

import pytest

from nos.chessboard import solve
from nos.data import scenario_from_dict
from nos.evaluate import Model
from nos.lagrange import columns, dual_value, lagrangian_bound
from nos.simulator import simulate

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("name", ["scenario_middle", "scenario_big"])
def test_bound_is_valid(name):
    sc = scenario_from_dict(name, json.loads((FIX / name / "scenario.json").read_text()))
    m = Model(sc)
    b = lagrangian_bound(m)
    assert b.complete
    assert b.window_value_ub >= b.window_value_lb - 1e-9          # weak duality
    plan = solve(m, None, keep=30, verbose=False).plan
    assert b.score_ub >= simulate(sc, m.to_plan(plan.routes)).score - 1e-6


def test_weak_duality_for_random_multipliers():
    import random
    sc = scenario_from_dict("scenario_big", json.loads((FIX / "scenario_big" / "scenario.json").read_text()))
    m = Model(sc)
    W, cols, _ = columns(m)
    opt = lagrangian_bound(m).window_value_lb                      # a feasible packing value
    rng = random.Random(0)
    for _ in range(200):                                           # every mu >= 0 gives an upper bound
        mu = {u: rng.uniform(0, 3) for u in W}
        assert dual_value(mu, cols, m.n_trucks)[0] >= opt - 1e-9
