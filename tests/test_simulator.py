"""The local simulator must reproduce every recorded API response exactly.

A failing case prints the differing fields (simulate metrics, per-truck values,
the first differing stop, score breakdown, violations).
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from nos.data import scenario_from_dict
from nos.simulator import simulate

FIX = Path(__file__).parent / "fixtures"
CASES = sorted(p for p in FIX.glob("*/*.json") if p.name != "scenario.json")
SCHED_KEYS = ("action", "order", "city", "arrival_min", "wait_min", "late_min", "departure_min")


def diff(fx: dict, res) -> list[str]:
    out = []
    api = fx["simulate"]
    for k, v in api.items():
        if k == "trucks":
            continue
        if res.simulate.get(k) != v:
            out.append(f"sim.{k}: api={v} ours={res.simulate.get(k)}")
    ours = {t["truck"]: t for t in res.trucks}
    for t in api.get("trucks", []):
        o = ours.get(t["truck"])
        if o is None:
            out.append(f"truck {t['truck']} missing")
            continue
        for k, v in t.items():
            if k == "schedule":
                for i, (a, b) in enumerate(zip(v, o["schedule"])):
                    bad = [f"{k2}:{a[k2]}/{b.get(k2)}" for k2 in SCHED_KEYS if a[k2] != b.get(k2)]
                    if bad:
                        out.append(f"{t['truck']} stop{i} {a['action']} {a['order']}: " + " ".join(bad))
                        break
                if len(v) != len(o["schedule"]):
                    out.append(f"{t['truck']} schedule len api={len(v)} ours={len(o['schedule'])}")
            elif o.get(k) != v:
                out.append(f"{t['truck']}.{k}: api={v} ours={o.get(k)}")
    sc = fx["score"]
    if round(res.score, 2) != sc["score"]:
        out.append(f"score: api={sc['score']} ours={res.score}")
    for k, v in sc["breakdown"].items():
        if res.breakdown.get(k) != v:
            out.append(f"breakdown.{k}: api={v} ours={res.breakdown.get(k)}")
    av = Counter((v["rule"], v["truck"], v["order"]) for v in sc["validation"]["violations"])
    ov = Counter((v["rule"], v["truck"], v["order"]) for v in res.violations)
    if av != ov:
        out.append(f"violations: api-only={dict(av - ov)} ours-only={dict(ov - av)}")
    return out


@pytest.mark.parametrize("path", CASES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_matches_api(path):
    sc = scenario_from_dict(path.parent.name, json.loads((path.parent / "scenario.json").read_text()))
    fx = json.loads(path.read_text())
    assert diff(fx, simulate(sc, fx["plan"])) == []
