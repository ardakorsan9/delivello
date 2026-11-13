"""Compare the local simulator against every recorded API response in tests/fixtures/."""
import json
import sys
from collections import Counter
from pathlib import Path

from nos.data import scenario_from_dict
from nos.simulator import simulate

FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
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


def main() -> int:
    bad = 0
    for folder in sorted(FIX.iterdir()):
        raw = json.loads((folder / "scenario.json").read_text())
        sc = scenario_from_dict(folder.name, raw)
        for f in sorted(folder.glob("*.json")):
            if f.name == "scenario.json":
                continue
            fx = json.loads(f.read_text())
            d = diff(fx, simulate(sc, fx["plan"]))
            print(("OK  " if not d else "FAIL") + f" {folder.name}/{f.stem}")
            for line in d[:12]:
                print("     " + line)
            bad += bool(d)
    print(f"\n{bad} fixture(s) differ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
