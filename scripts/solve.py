"""One command for a scenario: (optional fresh data) -> chessboard -> parallel ALNS -> polish
-> exact check -> archive if better -> dashboard.json. Never submits to the API.

Usage:
  uv run python scripts/solve.py scenario_competitive --minutes 10
  uv run python scripts/solve.py scenario_big --minutes 3 --workers 4
  uv run python scripts/solve.py all --minutes 5          # small, middle, big, competitive
Options: --workers N (default 4), --seed S, --no-polish, --no-dashboard,
         --fresh (cold start: ignore stored best plan and route pool)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from nos.pipeline import run
from nos.plans import RESULTS_DIR, archive
from nos.simulator import simulate

ROOT = Path(__file__).resolve().parents[1]
ALL = ["scenario_small", "scenario_middle", "scenario_big", "scenario_competitive"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-polish", action="store_true")
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()

    bad = 0
    for sid in ALL if a.scenario == "all" else [a.scenario]:
        print(f"\n{sid}")
        sc, m, start, best, hist = run(sid, a.minutes * 60, a.workers, not a.no_polish, a.seed,
                                       fresh=a.fresh)
        plan = m.to_plan(best.routes)
        sim = simulate(sc, plan)
        if sim.violations or abs(sim.score - best.score()) > 0.011:
            print(f"  ! exact check failed: {len(sim.violations)} violations, "
                  f"simulator {sim.score} vs fast {best.score():.2f} - not archived")
            bad += 1
            continue
        b = sim.breakdown
        print(f"  RESULT {sim.score:.2f}  orders {sim.simulate['orders_fulfilled']}/{m.n_orders}  "
              f"fulfil {b['fulfillment']} cost {b['cost_efficiency']} loaded {b['loaded_ratio']} "
              f"co2 {b['co2_efficiency']}")
        if archive(plan, sid, sim.score, fingerprint=sc.fingerprint, source="solve", valid=True):
            print(f"  -> new best in results/{sid}/best.json")
        else:
            print("  (stored best is at least as good; kept)")
        if hist:
            (RESULTS_DIR / sid / "alns_history.json").write_text(json.dumps(
                {"start": start.score(), "history": hist[::max(1, len(hist) // 2000)]}))
        if not a.no_dashboard:
            subprocess.run([sys.executable, str(ROOT / "scripts" / "export_dashboard.py"), sid], check=False)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
