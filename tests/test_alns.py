"""Fast position search and a short ALNS run."""
import json
import random
from pathlib import Path

from nos.alns import ALNS
from nos.construct import regret_insertion
from nos.data import scenario_from_dict
from nos.evaluate import Model
from nos.simulator import simulate

FIX = Path(__file__).parent / "fixtures"


def model(name):
    return Model(scenario_from_dict(name, json.loads((FIX / name / "scenario.json").read_text())))


def route_km(m, t, r):
    c, s = m.t_start[t], 0.0
    for o, p in r:
        x = m.o_city[o][0 if p else 1]
        s += m.km[c][x]
        c = x
    return s


def test_topn_positions_are_the_cheapest():
    m = model("scenario_big")
    ins = regret_insertion(m, k=2, orders=list(range(60)))
    rng = random.Random(0)
    for _ in range(100):
        t, o = rng.randrange(m.n_trucks), rng.randrange(60, m.n_orders)
        r = ins.routes[t]

        def km(i, j):
            return round(route_km(m, t, r[:i] + [(o, True)] + r[i:j] + [(o, False)] + r[j:]), 6)
        brute = sorted(km(i, j) for i, j in ins.positions(t, o, None))
        fast = sorted(km(i, j) for i, j in ins.positions(t, o, 8))
        assert fast == brute[:len(fast)] and len(fast) == min(8, len(brute))


def test_alns_never_worse_and_valid():
    m = model("scenario_middle")
    start = regret_insertion(m, k=2)
    res = ALNS(m, seed=0).run(start, time_limit=5, verbose=False)
    assert res.best.score() >= start.score() - 1e-9
    sim = simulate(m.sc, m.to_plan(res.best.routes))
    assert sim.violations == [] and abs(sim.score - res.best.score()) < 0.011
