"""Regret insertion must produce valid plans whose fast score equals the exact one."""
import json
from pathlib import Path

from nos.construct import regret_insertion
from nos.data import scenario_from_dict
from nos.evaluate import Model
from nos.simulator import simulate

FIX = Path(__file__).parent / "fixtures"


def test_regret_insertion_small_and_middle():
    for name, k, minimum in [("scenario_small", 3, 999.99), ("scenario_middle", 2, 970)]:
        sc = scenario_from_dict(name, json.loads((FIX / name / "scenario.json").read_text()))
        m = Model(sc)
        ins = regret_insertion(m, k=k)
        res = simulate(sc, m.to_plan(ins.routes))
        assert res.violations == []
        assert abs(res.score - ins.score()) < 0.011
        assert res.score >= minimum
