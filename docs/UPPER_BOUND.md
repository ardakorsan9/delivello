# Upper bound on the score: Lagrangian relaxation

Code: `src/nos/lagrange.py`, run `uv run python scripts/upper_bound.py`. The script also solves the LP
relaxation (GLOP) and the integer problem (CP-SAT) as independent checks.

## 1. Notation
- $O$: orders, $W \subseteq O$: orders with a pickup or delivery time window, $T$: trucks.
- $v_u$: value of order $u$ (docs §9.1), $V = \sum_{u \in O} v_u$.
- Score (docs §9), with $F, C, R, G \in [0, 100]$ and $n_{viol}$ violations:
$$\text{score} = 10\,(0.50\,F + 0.20\,C + 0.15\,R + 0.15\,G) - 20\,n_{viol},\qquad
F = 100\,\frac{\text{value fulfilled}}{V}.$$

## 2. Two structural facts

**Fact 1 (orders without windows).** They enter the bound with their full value: whatever a plan does,
the value it fulfils from orders without a time window is at most their total value.

**Lemma 2 (monotonicity, modelling assumption).** Removing stops from a route never makes a remaining stop
later. Driving and service are additive; waiting only shortens. One rule is not monotone: off-duty time
$\ge 45$ min counts as a break, so an extra 30-min stop next to another one can replace a 45-min break
(net gain $\le 15$ min). We check robustness by repeating the enumeration with a lateness tolerance of 75
and 90 min instead of 60. The served window count does not change for competitive at 75 min
(`chessboard.solve(..., grace=75)`).

**Consequence.** A set $S \subseteq W$ is servable by truck $t$ in *some* plan iff $t$, starting empty with
only the stops of $S$, serves every $u \in S$ at most 60 min late. Let $F_t$ be the family of such sets
(enumerated bottom-up by `chessboard.enumerate_truck`; complete, i.e. not truncated, for all scenarios).

## 3. The window packing problem (P)
$$
\begin{aligned}
Z^{*} \;=\; \max\; & \sum_{t \in T} \sum_{S \in F_t} v_S\, y_{tS}, \qquad v_S = \sum_{u \in S} v_u \\
\text{s.t.}\; & \sum_{S \in F_t} y_{tS} \le 1 && \forall t \in T \quad \text{(one window set per truck)} \\
& \sum_{t \in T} \sum_{S \in F_t:\, u \in S} y_{tS} \le 1 && \forall u \in W \quad \text{(each order at most once)} \\
& y_{tS} \in \{0, 1\}.
\end{aligned}
$$
$v_S$ is the *nominal* value. Lateness only lowers the realised value, so $Z^*$ bounds every plan's window value.

## 4. Lagrangian relaxation
Relax the order constraints with multipliers $\mu_u \ge 0$:
$$
\mathcal{L}(y, \mu) = \sum_{t}\sum_{S \in F_t} v_S\, y_{tS} + \sum_{u \in W} \mu_u \Big(1 - \sum_{t}\sum_{S \ni u} y_{tS}\Big)
= \sum_{u \in W}\mu_u + \sum_{t}\sum_{S \in F_t} \Big(v_S - \sum_{u \in S}\mu_u\Big) y_{tS}.
$$
Maximising over $y$ subject only to the truck constraints separates by truck. Each truck takes its best
*reduced* column, or nothing:
$$
L(\mu) = \sum_{u \in W} \mu_u + \sum_{t \in T} \max\Big(0,\; \max_{S \in F_t} \big(v_S - \mu(S)\big)\Big),
\qquad \mu(S) = \sum_{u \in S}\mu_u .
$$

**Weak duality.** For any feasible $y$ of (P) and any $\mu \ge 0$, the penalty term
$\mu_u(1 - \sum y) \ge 0$. So
$\sum v_S y_{tS} \le \mathcal{L}(y,\mu) \le L(\mu)$. Hence $Z^* \le L(\mu)$ for **every** $\mu \ge 0$.

**Lagrangian dual.** $Z_{LD} = \min_{\mu \ge 0} L(\mu) \ge Z^*$. $L$ is convex and piecewise linear: it is a
maximum of affine functions of $\mu$.

**Strength (Geoffrion 1974).** Each truck subproblem
$\{y_t \in \{0,1\}^{|F_t|}: \sum_S y_{tS} \le 1\}$ has the integrality property: its convex hull equals the LP
polytope. Therefore $Z_{LD} = Z_{LP}$, the LP-relaxation optimum of (P). The script verifies this numerically
with GLOP: dual minus LP is $0.0000$ in all scenarios.

## 5. Solving the dual: projected subgradient
At $\mu^k$ let $S_t^k$ be truck $t$'s chosen column (or none). A subgradient of $L$ is
$$ g_u^k = 1 - \#\{t : u \in S_t^k\}. $$
Update with the Polyak step towards the best known primal value $Z_{LB}$ (greedy packing guided by $\mu$):
$$
\mu^{k+1} = \max\!\Big(0,\; \mu^k - \theta_k \,\frac{L(\mu^k) - Z_{LB}}{\lVert g^k \rVert^2}\, g^k\Big),
$$
with $\theta_0 = 2$, halved after 50 steps without improvement (Held & Karp). Stop when $g^k = 0$
($\mu^k$ is optimal), when $L - Z_{LB} < 10^{-6}$, or when $\theta < 10^{-6}$. Every iterate gives a valid
bound; we keep $\min_k L(\mu^k)$.

## 6. From the window bound to a score bound
Orders outside $W$ add at most their total value:
$$
F \le F_{ub} = 100\,\frac{\sum_{u \notin W} v_u + Z_{LD}}{V}.
$$
With $C, G \le 100$ (they are capped by $\min(1,\cdot)$), $R = 100\,\text{loaded}/\text{total} \le 100$ and
$n_{viol} \ge 0$:
$$
\boxed{\;\text{score} \le 10\,\big(0.50\,F_{ub} + 0.20\cdot 100 + 0.15\cdot 100 + 0.15\cdot 100\big) = 500 + 5\,F_{ub}\;}
$$

## 7. Results (2026-11-13 data)
| Scenario | $\lvert W\rvert$ | columns | $Z_{LD}=Z_{LP}$ | $Z^*$ (CP-SAT) | $F_{ub}$ | **score bound** | our best | gap |
|---|---|---|---|---|---|---|---|---|
| middle | 7 | 42 | 11.00 | 11.00 | 100.000 % | **1000.00** | 996.56 | 3.44 |
| big | 20 | 64 | 26.00 | 26.00 | 94.483 % | **972.41** | 964.85 | 7.56 |
| competitive | 63 | 394 | 68.75 | 68.00 | 87.030 % | **935.15** | 932.22 | 2.93 |

Reading the gaps:
- **Competitive:** the LP/Lagrangian bound has an integrality gap of 0.75 value. Using the integer optimum
  $Z^* = 68$ instead gives $F \le 86.733\,\%$ and **score $\le$ 933.66**, so we are within **1.44 points**.
  Of that, $R = 99.14$ accounts for $\approx 1.3$: empty first legs of trucks that must serve window orders.
- **Big:** 5.2 points come from O044 (hazmat, no window, left out because serving it lowers the score) and $\approx 2.4$ from $R = 98.4$.
- **Middle:** fulfillment is at the bound; the whole gap is $R = 97.7$.

The bound assumes $R = 100$ (no empty km at all). A tighter bound would need a lower bound on the empty
first legs, which depends on which trucks serve the window orders. This is a possible next step (relax the
same packing with the first-leg km in the objective).

## 8. Why the remaining empty km is structural
All empty km of the best plans are **first legs** (start city to first pickup). There are zero empty km
between orders. For every truck with an empty first leg we tried to start it with an order picked up in
its own start city: taken from any truck or unserved, with its delivery at every later position, and
checked exactly. Not one such move is feasible:

| Scenario | Truck | Empty first leg | Compatible orders starting in its city | Feasible |
|---|---|---|---|---|
| middle | T01 / T02 | 69 / 284 km | 0 / 2 | 0 / 0 |
| big | T03 / T13 | 264 / 265 km | 0 / 0 | — |
| competitive | T03 / T05 / T14 / T17 / T22 | 175 / 308 / 308 / 521 / 157 km | 3 / 4 / 3 / 4 / 0 | 0 |

Every candidate makes one of that truck's time-window stops more than 60 min late. These trucks are the
ones that must serve window orders (the chessboard assignment), so they have to drive straight there.
The remaining gap to the bound is geography and time, not search.

References: A. M. Geoffrion, "Lagrangean relaxation for integer programming", *Math. Programming Study* 2
(1974); M. Held, R. M. Karp, "The traveling-salesman problem and minimum spanning trees: part II",
*Math. Programming* 1 (1971); M. L. Fisher, "The Lagrangian relaxation method for solving integer programming
problems", *Management Science* 27 (1981).
