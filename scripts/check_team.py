"""Check that the API key in .env works (uses the unlimited Validate endpoint).

Usage:  uv run python scripts/check_team.py
        uv run python scripts/check_team.py --register "Delivello"
"""

from __future__ import annotations

import argparse
import json

import requests

from nos.api import GruberAPI


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--register", metavar="NAME", help="register / rename the team on the leaderboard")
    args = p.parse_args()

    api = GruberAPI()
    try:
        plan = api.sample_plan("scenario_small")
        result = api.validate("scenario_small", plan)
        print("API key OK - validate on scenario_small:", json.dumps(result))
        if args.register:
            print("register:", json.dumps(api.register_team(args.register), indent=1))
    except requests.HTTPError as e:
        print(f"HTTP {e.response.status_code}: {e.response.text}")


if __name__ == "__main__":
    main()
