# Challenge rules (from the official GRUBER documentation)

Source: `Hackaton2026.pdf` / <https://hackathon-challenge.gruber-logistics.dev/Hackaton2026/documentation>.
This file is the reference the local simulator (`src/nos/`) must follow exactly.

## 1. Plan format
- JSON object: key = truck id, value = ordered list of stops `{"action": "pickup"|"delivery", "order": "O001"}`.
- `pickup` -> truck drives to the order's `pickup_city`; `delivery` -> to its `delivery_city`.
- Truck starts at `start_city`, visits stops in list order, **does not return** at the end.
- Consecutive stops in the same city cost 0 km. A truck may visit a city many times.
- Several orders can be on board at once, as long as capacity is never exceeded.
- An order cannot be split between trucks. Unused trucks cost nothing.
- Orders not in the plan are simply not fulfilled (no extra penalty).

## 2. Validation rules — each violation: **-20 points**
| Rule | Meaning |
|---|---|
| `unknown_truck` | truck id does not exist |
| `unknown_order` | order id does not exist |
| `unknown_action` | action is not pickup/delivery |
| `order_assigned_multiple_times` | same order on more than one truck |
| `duplicate_pickup` / `duplicate_delivery` | order picked up / delivered twice |
| `delivery_before_pickup` | delivery stop before its pickup |
| `pickup_without_delivery` | picked up but never delivered |
| `capacity_exceeded` | pickup would push the load above `capacity_kg` |
| `truck_type_mismatch` | `required_truck_type` set and differs from the truck type |

How invalid stops are simulated:
- Non-executable stops (unknown order/action, delivery before pickup, duplicates, order already taken by another truck) are **skipped**.
- Orders delivered by a wrong-type truck are **not fulfilled**.
- A pickup that exceeds capacity is **rejected**: not loaded, its later delivery is ignored, not fulfilled; the penalty still applies.

## 3. Distance, cost, CO2
- Distance matrix: symmetric, km, great-circle x 1.3.
- `loaded_km`: km driven with at least one order on board; `empty_km`: km with nothing on board.
- `total_cost = sum(km x cost_per_km)` per truck; `total_co2 = sum(km x co2_per_km)` per truck (loaded or empty alike).

## 4. Time model
| Rule | Value |
|---|---|
| Start | minute 0 = Day 1, 06:00; all trucks start at minute 0 |
| Driving | 70 km/h, `driving_min = ceil(km * 60 / 70)` |
| Service | 30 min per stop (pickup or delivery) |
| Break | 45 min after 4.5 h (270 min) of driving, inserted automatically |
| Daily rest | 11 h (660 min) after 9 h (540 min) of driving, inserted automatically |
| Waiting / service >= 45 min | counts as a break |

Time windows (`pickup_window` / `delivery_window`, `{from, to}` in minutes):
- Early arrival: wait until `from`.
- Late by up to 60 min after `to`: fulfilled, value scaled linearly 100% -> 50% (30 min late = 75%).
- Late by more than 60 min: **not fulfilled**.
- Windows are generated so the nearest compatible truck can serve the order alone on time.

## 5. Score
Components (each 0-100):
| Component | Formula | Weight |
|---|---|---|
| Fulfillment | `100 * value_fulfilled / value_total` | 50% |
| Cost efficiency | `100 * min(1, reference_cost / total_cost)` | 20% |
| Loaded ratio | `100 * loaded_km / total_km` | 15% |
| CO2 efficiency | `100 * min(1, reference_co2 / total_co2)` | 15% |

References:
- `reference_km = (sum of direct pickup->delivery km of ALL orders) * orders_fulfilled / orders_total`
- `reference_cost = reference_km * min(cost_per_km in fleet)`
- `reference_co2 = reference_km * min(co2_per_km in fleet)`

```
score = 10 * (0.50*fulfillment + 0.20*cost_eff + 0.15*loaded_ratio + 0.15*co2_eff) - 20 * violations
```
Max 1000, can be negative.

Order value: normal 1.0 · refrigerated 1.5 · hazmat 1.5 · +0.5 if it has a pickup or delivery time window.

## 6. API limits
- `scenario_competitive`: max **3 Score + 3 Simulate** calls per team (HTTP 429 after). Validate unlimited.
- Other scenarios: unlimited. Every call is recorded; ranking uses each team's best Score per scenario.
- Server restart regenerates all scenarios -> always fetch fresh data (`scripts/fetch_data.py` warns on change).
- Organizers may publish additional final scenarios during the event.

## 7. Verified against the API (tests/fixtures/, 29 recorded responses)
- Break (270 -> 45) and rest (540 -> 660) are inserted **mid-leg**; a rest also resets the break counter.
- Off-driving time between two legs (waiting + 30-min services, summed over same-city stops) of
  >= 45 min counts as a break. If a pause falls due exactly at arrival, that stop's off time counts toward it.
- Rejected (capacity) pickups are not driven to. `truck_type_mismatch` is flagged on the pickup and on a
  delivery-before-pickup, not on a duplicate pickup.
- Lateness value `value * (1 - 0.5 * late/60)` uses the max lateness of the order's stops; pickup lateness counts
  too. > 60 min on any stop -> not fulfilled. Values are not rounded to 2 decimals.
- `total_late_min` = sum over all executed stops; `penalized_late_min` = lateness of fulfilled late orders.
- `truck_utilization` = km-weighted mean of per-truck `sum(load*km)/(capacity*km)`.
- `late_penalty` in the breakdown is informational: `5 * 100 * value_lost / value_total` (already in fulfillment).
- Still assumed, not probed: off time >= 660 resets the daily driving counter; both stops late at once.
