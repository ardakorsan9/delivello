# Delivello — smart dispatch for GRUBER Logistics

Dispatch optimizer for the **GRUBER Logistics Hackathon Challenge 2026 — "Logistics Grand Prix"**
(NOI Hackathon SFSCON Edition 2026).

Given cities, trucks and transport orders, Delivello builds one ordered pickup/delivery stop list per
truck: deliver more, drive less, minimize empty kilometres, cost and CO₂.

Challenge API: <https://hackathon-challenge.gruber-logistics.dev/swagger/index.html>

Results (offline simulator, identical to the API):
small 1000.00, middle 997.24, big 966.54, competitive 932.22 (proven ceiling 933.66).

## Demo
- `web/index.html`: replay of the final plans on the map, score computed live from the plan.
- `web/whatif.html`: emergency what-if: a truck breaks down mid-plan and Delivello replans the fleet
  in a few seconds (`scripts/disruption.py`, every plan checked with the exact simulator).
- Build the page data first: see [web/README.md](web/README.md).

## Setup

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# 1. install uv (once)
#    Linux / macOS / WSL:
curl -LsSf https://astral.sh/uv/install.sh | sh
#    Windows PowerShell:
#    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. install dependencies (creates .venv)
uv sync --extra solver

# 3. API key: copy the template and put the team key in .env
cp .env.example .env        # Windows: copy .env.example .env
```

`.env` is git-ignored. **Never commit the API key** — this repository is open source.

## Usage

```bash
uv run python scripts/fetch_data.py     # download all scenarios into data/
uv run python scripts/check_team.py     # verify the API key, show team info and limits
uv run pytest                           # run tests

# solve one scenario (or "all"): chessboard start -> parallel ALNS -> polish -> check -> dashboard.json
uv run python scripts/solve.py scenario_competitive --minutes 10
uv run python scripts/check_plans.py    # check every stored best plan against all rules (offline)
uv run python scripts/upper_bound.py    # Lagrangian upper bound on the score
```

Nothing above submits a plan. Submissions go only through `scripts/submit.py`.

## Method
1. **Exact simulator**: a re-implementation of the Simulate/Score rules, checked against recorded API responses.
2. **Chessboard**: CP-SAT places the time-window orders on trucks, then regret insertion fills in the rest.
3. **ALNS** (Ropke & Pisinger 2006) on the official score, run in parallel with several seeds. The
   simulated-annealing temperature is driven by a PI controller on the acceptance rate.
4. **Set partitioning** over the route pool, with Dinkelbach's method for the loaded-km ratio.
5. **Lagrangian upper bound**: shows how far a plan is from the best possible score
   ([docs/UPPER_BOUND.md](docs/UPPER_BOUND.md)).

`scenario_competitive` allows only 3 Score and 3 Simulate calls per team. The client
(`src/nos/api.py`) refuses those calls unless `confirm=True` is passed.

## Project layout

```
src/nos/        library code (API client, simulator, optimizers)
scripts/        command-line entry points
tests/          tests
data/           downloaded scenarios (git-ignored, regenerate with fetch_data.py)
```

## License

GNU Affero General Public License v3.0 (AGPL-3.0) — see [LICENSE](LICENSE).
