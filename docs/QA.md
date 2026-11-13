# Q&A preparation (numbers from the 2026-11-13 data)

Every number below can be reproduced offline:
- `uv run python scripts/check_plans.py`: scores, rules, bounds
- `uv run python scripts/upper_bound.py`: Lagrangian bound with LP and CP-SAT checks

## Results
| Scenario | Naive round robin | Chessboard start | Final | Upper bound | Gap |
|---|---|---|---|---|---|
| small | 751.3 | 1000.0 | **1000.00** | 1000.00 | 0 |
| middle | 614.7 | 990.4 | **996.56** | 1000.00 | 3.44 |
| big | 557.0 | 957.5 | **966.54** | 972.41 | 5.87 |
| competitive | 480.6 | 931.0 | **932.22** | 935.15 (933.66 with the integer optimum) | 1.44 |

All plans have 0 rule violations. Cost and CO2 efficiency are 100 in every scenario.

## Likely questions

**Why not 1000?** Time windows conflict: one truck cannot be in two cities at the same time. We
enumerated, for every truck, every set of window orders it can serve together. CP-SAT then picked the
best combination: at most 42 of 63 window orders (competitive) and 15 of 20 (big) can be served at all.
We serve exactly that many.

**How do you know the bound is right?** Weak duality: for any non-negative Lagrange multipliers the dual
value is at least the optimum. Two independent solvers agree: the LP (GLOP) equals the Lagrangian dual
to 4 decimals, and the integer optimum (CP-SAT) is below it. Caveat: one rule (a 30-min stop can replace
a 45-min break) is not monotone. We tested a 75-min tolerance and the result does not change.
Details: [UPPER_BOUND.md](UPPER_BOUND.md).

**Where are the last points lost?** Two places:
1. Orders that cannot be served (the bound above).
2. Empty km. Every remaining empty km is a truck's first leg to a window order. Starting those trucks
   with a local order is never feasible: every candidate makes a window more than 60 min late
   ([UPPER_BOUND.md §8](UPPER_BOUND.md)). There are zero empty km between orders.

**Is anything delivered late?** One stop in all four plans: competitive O055 is 6 min late (value kept:
95%, cost 0.15 points). Without lateness at most 41 window orders fit. The 42nd needs those 6 minutes,
and serving it late scores +3.9 points more than leaving it out.

**Why is big's O044 not delivered?** It is hazmat, and T12 is the only hazmat truck. Every way of adding
it to T12's route lowers the official score: the extra km cost more points than the order's value
brings. The plan is optimised on the official score, so it leaves O044 out.

**How do you know your simulator matches the API?** It reproduces all 29 recorded API responses
exactly: every stop's arrival and departure minute, km, cost, CO2, violations and score. 14 of those 29
were probes designed to separate competing rule interpretations (break placement, lateness value).
The final middle and big plans were also simulated by the API: identical down to every stop's minute
(19 trucks, 328 stops).

**Algorithm in one breath?** An exact simulator; a CP-SAT "chessboard" for the time-window orders;
regret insertion; ALNS (Ropke & Pisinger 2006) on the official score in 4 parallel processes, with the
simulated-annealing temperature driven by a PI controller on the acceptance rate; set partitioning with
Dinkelbach for the loaded-km ratio; a Lagrangian upper bound to measure the remaining gap.

**Where is the control engineering?** The annealing temperature is the actuator of a PI loop. The
measured variable is the acceptance rate of worse moves, and the set point falls from 25% to 1% during
the run. The operator weights adapt to the reward each operator earns.

**How fast is it? What if the data changes?** From scratch (`scripts/solve.py --fresh`):
- competitive: 932.07 in about 6 min
- big: 966.54 in 3 min
- the chessboard alone: 931 in under 30 s

On a server restart: run `fetch_data.py`, then `solve.py all --fresh`, then check, then submit.

**Did you use AI?** Not inside the optimiser. This problem is deterministic and fully known, so learning
gives nothing a 24-hour exact/heuristic pipeline cannot. Development used an AI coding assistant.

**Is the bound a claim of optimality?** No. It is a computed upper bound under one stated assumption.
We say "within 1.44 points of a computed upper bound", not "optimal".
