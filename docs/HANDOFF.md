# NOS — Handoff / project state

Read this first in a new session. Talk to Arda in **Turkish**; he is new to Linux, so give
commands step by step. Rules reference: [RULES.md](RULES.md). Literature: [RESEARCH.md](RESEARCH.md).

## Context
- NOI Hackathon SFSCON Edition 2026 (Bolzano), 24 h, Fri 13 – Sat 14 Nov 2026, ~80 students.
- Challenge: **GRUBER Logistics "Logistics Grand Prix"**: truck dispatch optimization
  (PDPTW: pickup & delivery with time windows, heterogeneous fleet, driver breaks).
- Project: **NOS – Network Optimization System**, tagline "Ride or Deliver".
- Team: Arda (control/automation engineer: code + math), a designer (Figma/Illustrator/Blender/Canva),
  a presenter. Product AI kept minimal: math first.

## Environment
- Repo: `~/projects/nos` (WSL Ubuntu 24.04, `uv`, Python 3.12). Arda reads code in Cursor via WSL;
  the Cursor agent is not used on this repo (avoid concurrent edits).
- Challenge PDFs: `~/veri/hackathon/docs/challenge/` (`Hackaton2026.pdf` = full documentation).
- Disk: C: (SSD) only ~9 GB free. Code stays in `~/projects`; large files (video, renders) go to `~/veri` (E: HDD).

| Path | Purpose |
|---|---|
| `src/nos/api.py` | GRUBER API client; Score/Simulate on competitive require `confirm=True` |
| `src/nos/data.py` | scenario loader (City/Truck/Order/TimeWindow, numpy distance matrix) |
| `src/nos/plans.py` | plan archive; `results/<scenario>/best.json` = best valid plan |
| `scripts/fetch_data.py` | download all scenarios to `data/`, fingerprint warns on server restart |
| `scripts/check_team.py` | verify API key (via Validate) / register team name |
| `scripts/submit.py` | `validate | simulate | score <scenario> <plan.json|best>`; competitive needs `--confirm` + typed name |
| `scripts/collect_fixtures.py` | probe plans -> real API responses in `tests/fixtures/` |
| `src/nos/simulator.py` | exact re-implementation of Simulate + Score (matches all 29 fixtures) |
| `src/nos/evaluate.py` | fast per-truck evaluator for valid plans (`Model`), agrees with simulator |
| `src/nos/alns.py` | ALNS: 5 destroy ops, 3 repairs, adaptive weights, PI-controlled SA temperature, route pool |
| `src/nos/chessboard.py` | exact window-order placement: per-truck feasible window sets + CP-SAT packing |
| `src/nos/polish.py` | set partitioning over the route pool + Dinkelbach for the loaded ratio |
| `src/nos/timeline.py` | minute timeline (drive/break/rest/wait/service) for Gantt + map animation |
| `src/nos/construct.py` | `Insertion` state (incremental totals), regret-k insertion, top-n position search |
| `src/nos/lagrange.py` | Lagrangian upper bound on the score ([math](UPPER_BOUND.md)) |
| `src/nos/pipeline.py` | start (best.json vs chessboard) -> parallel ALNS (multi-seed) -> polish |
| `scripts/solve.py` | **one command per scenario**: pipeline + exact check + archive + dashboard.json |
| `scripts/export_dashboard.py` | write `results/<s>/dashboard.json` ([contract](DASHBOARD_JSON.md)) |
| `scripts/upper_bound.py` | Lagrangian bound with LP (GLOP) and integer (CP-SAT) cross-checks |
| `scripts/check_plans.py` | offline check of every best.json against all rules + score upper bound |
| `tests/fixtures/` | recorded API responses: 5 base probes per scenario + 14 rule probes (middle/big) |

## API
- Base `https://hackathon-challenge.gruber-logistics.dev/Hackaton2026`, Swagger at `/swagger`.
- Key lives in `.env` (git-ignored). **Never** put it in code, commits or chat.
- Team id `team08`, display name "NOS". `GET /Team` does not exist (404).
- `scenario_competitive` (45 cities / 25 trucks / 200 orders, ~30% time windows):
  **only 3 Score + 3 Simulate per team, none used yet. Always ask Arda before using one.**
- small (20 orders), middle (50), big (120): unlimited. Ranking = best Score per scenario.
- Server restart regenerates all scenarios; organizers may publish final scenarios during the event.

## Findings
- Baseline so far: naive round-robin on small = **751.34** (fulfillment 100, cost 48.9, loaded 54.3, CO2 48.1).

## Planned method
1. **Exact simulator** (state machine per truck) reproducing every fixture in `tests/fixtures/`.
   Open questions: break/rest placement mid-leg vs at stops, waiting counted as break, rounding.
2. **Score-loss breakdown** + lower bound on unavoidable empty km + multi-seed convergence evidence
   (a tight formal upper bound is not realistic in 24 h; do not claim "% of optimum").
3. **Construction**: chaining (assignment / min-cost flow) + regret insertion.
4. **ALNS** (Ropke & Pisinger 2006) with simulated annealing; temperature driven by a **PI controller**
   on the acceptance rate; adaptive operator weights. Objective = official score.
5. **Polish**: set partitioning over a route pool (OR-Tools CP-SAT), Dinkelbach for the loaded-ratio fraction.
6. Optional AI: an LLM that only *explains* the plan; start by hour ~16 or drop it.

## Design integration
- Optimizer writes `results/<scenario>/dashboard.json`; a static web page (works offline) renders it.
- Designer delivers Figma screens 1920x1080 dark: route map, KPI strip, algorithm lab (score history =
  "nitro tank"), truck timeline (Gantt: drive/service/wait/break/rest). Google Fonts, hex colours, SVG icons.
- Freeze the JSON contract early.

## Event logistics / open items
- Forgejo: `repos.hackathon.bz.it/2026-sfscon/team-15` (private). Organizers wrongly added a stranger
  (Hamza Jamil) and our third member István is missing; they promised a fix. **Do not push until fixed**,
  then push the full history.
- Project must be open source (MIT, already in repo). Make the repo public and add its link to the
  hackathon.bz.it project page before the final.
- Intermediate presentation **Sat 10:00** (technical approach + architecture, counts toward final).
  Prize preferences to Emily by **Sat 12:00**. Rehearsal 13:00–15:00 in Seminar 1.
- Final: 3 min pitch (1 min intro + 2 min demo) + 2 min Q&A. Slides: Cover, Team, Project, How we solved it, Demo.
- Juror: Günther Erb (GRUBER IT director; also judged 2023 & 2024, picked product/story-driven projects).
- Extra award: "Maker Space – Most Valuable Prototype" (optional 3D-printed trucks).
- Element rooms: main `#main-room-sfscon26:matrix.org`, Gruber `#gruber-sfscon26:matrix.org`.

## State (2026-11-13 late evening)
- Arda's decision: **send nothing to the API until the end** (final plans ~1-2 h before the deadline, after a
  fingerprint check). Small/middle/big Score is unlimited; competitive has 3 Score + 3 Simulate, unused.
- Local best (results/<scenario>/best.json, git-ignored): small 1000.00, middle 996.56, big 966.54,
  competitive 932.22. `scripts/check_plans.py` passes for all four.
- **Window part is optimal** (chessboard enumeration complete, robust up to 75 min tolerance):
  big 15/20, competitive 42/63 window orders. Fulfillment
  cannot rise further (big O044 hazmat is left out because it lowers the score).
- All remaining empty km are first legs (start city -> first pickup) of trucks that carry window orders;
  zero empty km between orders. Remaining upside: ~1-3 points per scenario via alternative window
  assignments with shorter first legs.
- Before/after (dashboard stages): competitive 480.6 (naive) -> 931.0 (chessboard) -> 932.2 (final).

- **First API check (2026-11-13 22:38 UTC):** Simulate of the final middle and big plans matches our simulator
  exactly (19 trucks, 328 stops, every metric). No Score sent yet; competitive untouched (3 + 3 left).
- Q&A sheet with every number and its source: [QA.md](QA.md). Only one late stop in all plans
  (competitive O055, 6 min, needed: without lateness at most 41 window orders fit).
- Feature freeze (Arda, 2026-11-13 night): no new optimiser features. Remaining work = demo video:
  truck images from the designer + `dashboard.json` routes; red cargo box while `loaded` is true.

## Next step
1. Web dashboard reading `dashboard.json` (designer's Figma, offline page), then record the demo video.
2. Optional: chessboard tie-break on first-leg empty km; longer ALNS + polish runs.
3. Final day: `uv run python scripts/fetch_data.py`; if a fingerprint changed run
   `uv run python scripts/solve.py all --minutes 5 --fresh` (cold start reaches competitive 932.07 in ~6 min),
   then `scripts/check_plans.py`, then Score with Arda's go.
