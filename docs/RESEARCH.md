# Literature research — truck dispatch optimization

Collected 2026-11-13 from abstracts and summaries (full texts not read; "—" = no figure found).

## Mapping: score component -> theory
| Score part | Structure | Method | Source |
|---|---|---|---|
| Whole search | NP-hard PDPTW | ALNS with adaptive operator weights + SA acceptance | Ropke & Pisinger 2006 |
| Loaded ratio (15%) | fractional objective loaded/total | Dinkelbach: maximize `loaded − λ·total`, update λ, finite convergence | Baldacci et al. 2020 |
| Empty km | repositioning between delivery and next pickup | min-cost flow / assignment (chaining) | Convoy; Ergun et al. 2007 |
| Cost + CO2 (35%) | `min(1, ref/actual)` saturates | ε-constraint / lexicographic: once below reference, spend slack elsewhere | score formula |
| Fulfillment (50%) + time windows | feasibility checks | forward time slack (Savelsbergh 1992); breaks complicate it, full route re-simulation is cheap at our sizes | Campbell & Savelsbergh |
| Final polish | choose best route combination | set partitioning over a route pool (MIP) | Subramanian & Uchoa; Cavaliere et al. 2022 |
| Control contribution | SA temperature schedule | feedback (PI) control of the acceptance rate | adaptive SA |

Off-the-shelf solvers: PyVRP supports only depot–client pickup/delivery, not paired client–client PDP;
OR-Tools supports paired PDPTW but cannot optimize our exact score -> the core is our own code.

## 10 studies
| # | Study | Problem | Math / control | Reported result |
|---|---|---|---|---|
| 1 | [Ropke & Pisinger 2006, Transportation Science](https://pubsonline.informs.org/stoken/default+domain/EC-25/full/10.1287/trsc.1050.0135) | PDPTW | ALNS, adaptive weights, SA | Beat best known solutions on >50% of 350+ benchmarks (up to 500 requests) |
| 2 | [Li & Lim 2001, ICTAI](https://www.sintef.no/projectweb/top/pdptw/200-customers/) | PDPTW | tabu-embedded simulated annealing | — (created the standard PDPTW benchmark) |
| 3 | [Vidal et al., HGS (CIRRELT-2011-61)](https://www.cirrelt.ca/DocumentsTravail/CIRRELT-2011-61.pdf) | VRPTW | hybrid genetic search + diversity control | — (state of the art for VRPTW) |
| 4 | [Subramanian & Uchoa ILS-SP](https://www.uv.es/route2011/Subramanian.pdf); [Cavaliere et al. 2022](https://link.springer.com/article/10.1007/s12532-022-00224-2) | VRP, heterogeneous fleet | local search + set partitioning over route pool | — |
| 5 | [Baldacci et al. 2020, Transportation Science](https://arxiv.org/pdf/1804.03316) | VRP with fractional objective | Dinkelbach for integer programs + bounds | exact method, finite convergence |
| 6 | [Cortés, Sáez, Núñez et al. 2009, Transportation Science](https://econpapers.repec.org/RePEc:inm:ortrsc:v:43:y:2009:i:1:p:27-42) | dynamic PDP | hybrid adaptive predictive control (MPC) + PSO | gains vs rolling horizon, shrinking with size |
| 7 | [Same-day delivery dispatch, arXiv 2308.14476](https://ar5iv.labs.arxiv.org/html/2308.14476) | dynamic dispatch | iterative conditional dispatch vs rolling horizon | +1.5% avg (up to 2%) |
| 8 | [Ergun, Kuyzu, Savelsbergh 2007, Transportation Science](https://pubsonline.informs.org/doi/fpi/10.1287/trsc.1060.0169) | truckload empty miles | continuous-move tours / lane covering | 19% savings in example tour; trucks run empty ~20% of the time ([slides](https://www2.isye.gatech.edu/~ms79/publications/mclcp.pdf)) |
| 9 | [Convoy (industry)](https://convoy.com/blog/drop-and-hook-combinatorial-optimization/) | trailer repositioning | min-cost flow network | −2.5% routing cost, −3% empty miles |
| 10 | [UPS ORION (industry)](https://app.3blmedia.com/news/ups-accelerates-use-routing-optimization-software-reduce-100-million-miles-driven) | parcel routing | route optimization heuristics | 6–8 fewer miles/route/day; ~100M miles, 10M gallons, >$300M, ~100k t CO2 per year (projection) |

Extra: [Li et al. 2022, DRL for PDP](https://arxiv.org/abs/2110.02634) (needs training, not for 24 h);
[Koç, Bektaş, Jabali, Laporte 2014](https://www.cirrelt.ca/DocumentsTravail/CIRRELT-2014-26.pdf) (heterogeneous fleet & CO2).

## Takeaways
- For static PDPTW the winning family is ALNS + simulated annealing.
- Control algorithms (MPC) appear in *dynamic* problems; ours is static, so MPC fits only a
  "new event -> re-plan" demo. Our control contribution: adaptive mechanisms inside ALNS
  (PI-controlled temperature, adaptive operator weights).
- Industry gains are typically 2–20%; versus our naive baseline much larger gains are expected.
- Deep learning is not realistic within 24 h.

Pitch line: *"Our method combines the state of the art for this exact problem class (ALNS, Ropke & Pisinger 2006)
with exact fractional optimization (Dinkelbach) and a feedback-controlled search."*
