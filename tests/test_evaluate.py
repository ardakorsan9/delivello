"""The fast evaluator must agree with the exact simulator on valid plans."""
import json
import random
from pathlib import Path

import pytest

from nos.data import scenario_from_dict
from nos.evaluate import Model
from nos.simulator import simulate

FIX = Path(__file__).parent / "fixtures"


def random_routes(m: Model, rng: random.Random):
    routes = [[] for _ in range(m.n_trucks)]
    for o in rng.sample(range(m.n_orders), k=rng.randint(1, m.n_orders)):
        ts = [t for t in range(m.n_trucks) if m.can[o][t]]
        r = routes[rng.choice(ts)]
        i = rng.randint(0, len(r))
        j = rng.randint(i, len(r))
        r.insert(j, (o, False))
        r.insert(i, (o, True))
    return routes


@pytest.mark.parametrize("name", ["scenario_small", "scenario_middle", "scenario_big"])
def test_fast_eval_matches_simulator(name):
    sc = scenario_from_dict(name, json.loads((FIX / name / "scenario.json").read_text()))
    m = Model(sc)
    rng = random.Random(1)
    checked = 0
    for _ in range(200):
        routes = random_routes(m, rng)
        evals = [m.eval_truck(t, r) for t, r in enumerate(routes)]
        res = simulate(sc, m.to_plan(routes))
        if res.violations:   # capacity broken: API rejection semantics are not modelled here
            assert not all(e.ok for e in evals)
            continue
        checked += 1
        assert m.score(evals) == pytest.approx(res.score, abs=0.011)
        assert sum(e.count for e in evals) == res.simulate["orders_fulfilled"]
        assert sum(e.value for e in evals) == pytest.approx(res.simulate["value_fulfilled"], abs=1e-4)
    assert checked >= 20
