"""The local simulator must reproduce every recorded API response exactly."""
import json
from pathlib import Path

import pytest

from nos.data import scenario_from_dict
from nos.simulator import simulate

FIX = Path(__file__).parent / "fixtures"
CASES = sorted(p for p in FIX.glob("*/*.json") if p.name != "scenario.json")


@pytest.mark.parametrize("path", CASES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_matches_api(path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "compare_fixtures", Path(__file__).parents[1] / "scripts" / "compare_fixtures.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sc = scenario_from_dict(path.parent.name, json.loads((path.parent / "scenario.json").read_text()))
    fx = json.loads(path.read_text())
    assert mod.diff(fx, simulate(sc, fx["plan"])) == []
