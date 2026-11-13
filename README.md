# NOS — Network Optimization System

Dispatch optimizer for the **GRUBER Logistics Hackathon Challenge 2026 — "Logistics Grand Prix"**
(NOI Hackathon SFSCON Edition 2026).

Given cities, trucks and transport orders, NOS builds one ordered pickup/delivery stop list per
truck: deliver more, drive less, minimize empty kilometres, cost and CO₂.

Challenge API: <https://hackathon-challenge.gruber-logistics.dev/swagger/index.html>

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
```

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

MIT — see [LICENSE](LICENSE).
