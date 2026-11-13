"""Send a plan file to the GRUBER API.

Usage:
  uv run python scripts/submit.py validate scenario_small path/to/plan.json
  uv run python scripts/submit.py simulate scenario_big   path/to/plan.json
  uv run python scripts/submit.py score    scenario_big   path/to/plan.json

  # use the archived best plan of a scenario:
  uv run python scripts/submit.py score scenario_big best

On scenario_competitive, simulate/score use one of the 3 limited attempts:
they need --confirm AND typing the scenario name at the prompt.

Responses are saved under results/<scenario>/api/.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from nos.api import LIMITED_SCENARIOS, GruberAPI
from nos.data import load_scenario
from nos.plans import RESULTS_DIR, archive, best_plan, load_plan


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("kind", choices=["validate", "simulate", "score"])
    p.add_argument("scenario")
    p.add_argument("plan", help="plan JSON file, or 'best' for results/<scenario>/best.json")
    p.add_argument("--confirm", action="store_true", help="allow a limited call on competitive")
    args = p.parse_args()

    if args.plan == "best":
        entry = best_plan(args.scenario)
        if entry is None:
            raise SystemExit(f"no best plan archived for {args.scenario}")
        plan = entry["plan"]
    else:
        data = load_plan(Path(args.plan))
        # accept a bare plan, an archive entry {"meta", "plan"} or a fixture {"plan", ...}
        plan = data["plan"] if isinstance(data.get("plan"), dict) else data

    limited = args.kind in ("simulate", "score") and args.scenario in LIMITED_SCENARIOS
    if limited:
        if not args.confirm:
            raise SystemExit(f"{args.kind} on {args.scenario} is limited (3 per team). Add --confirm.")
        typed = input(f"This uses 1 of 3 {args.kind} attempts. Type '{args.scenario}' to continue: ")
        if typed.strip() != args.scenario:
            raise SystemExit("cancelled")

    api = GruberAPI()
    try:
        if args.kind == "validate":
            res = api.validate(args.scenario, plan)
        elif args.kind == "simulate":
            res = api.simulate(args.scenario, plan, confirm=limited)
        else:
            res = api.score(args.scenario, plan, confirm=limited)
    except requests.HTTPError as e:
        raise SystemExit(f"HTTP {e.response.status_code}: {e.response.text}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out = RESULTS_DIR / args.scenario / "api" / f"{stamp}_{args.kind}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"plan": plan, "response": res}, indent=1))

    if args.kind == "score":
        valid = res.get("validation", {}).get("is_valid", False)
        fp = load_scenario(args.scenario).fingerprint
        new_best = archive(plan, args.scenario, res["score"], fingerprint=fp,
                           source="api_score", valid=valid)
        print(f"score={res['score']}  breakdown={res.get('breakdown')}  valid={valid}"
              + ("  -> new best" if new_best else ""))
    elif args.kind == "validate":
        print(json.dumps(res, indent=1))
    else:
        m = {k: v for k, v in res.items() if k != "trucks"} if isinstance(res, dict) else res
        print(json.dumps(m, indent=1))
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
