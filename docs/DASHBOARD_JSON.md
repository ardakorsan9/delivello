# dashboard.json — data contract (version 1)

Produced by `uv run python scripts/export_dashboard.py <scenario>` into
`results/<scenario>/dashboard.json`. The web page / demo video only reads this file;
it never calls the API. Fields are only ever **added** within version 1.

Time: all minutes count from **minute 0 = Day 1, 06:00**. Day/clock for a minute `t`:
`day = 1 + floor((t + 360) / 1440)`, `clock = (t + 360) mod 1440` minutes after midnight.

```jsonc
{
  "version": 1,
  "scenario": "scenario_competitive",
  "fingerprint": "424d5e4226d8",          // data id; changes when the server regenerates scenarios
  "generated_at": "2026-11-13T22:40:00+00:00",
  "time": { "minute_0": "Day 1 06:00", "horizon_min": 21234 },  // last truck finishes here

  "cities": [ { "id": "C001", "name": "Belgrade", "country": "RS", "lat": 44.79, "lon": 20.45 } ],

  "trucks": [ {
    "id": "T01", "type": "standard",        // standard | refrigerated | hazmat
    "capacity_kg": 12000, "cost_per_km": 1.2, "co2_per_km": 0.85,
    "start_city": "C001", "color_index": 0, // 0..n-1, pick a palette colour by index
    "used": true,                           // false: truck stays parked (metrics null, empty lists)
    "metrics": { "total_km": 6120, "loaded_km": 6120, "empty_km": 0, "cost": 7344.0, "co2": 5202.0,
                 "max_load_kg": 9800, "utilization": 0.61, "finish_min": 20524,
                 "driving_min": 5246, "break_and_rest_min": 11325 },
    "route": ["C001", "C012", "C045"],     // visited cities in order (same-city stops collapsed)
    "stops": [ { "action": "pickup", "order": "O002", "city": "C012", "arrival_min": 552,
                 "wait_min": 0, "late_min": 0, "departure_min": 582 } ],
    "timeline": [                           // contiguous activity segments, start <= end, minutes
      { "kind": "drive", "start": 0, "end": 270, "from": "C001", "to": "C012",
        "f0": 0.0, "f1": 0.49, "km": 315.0, "loaded": false, "load_kg": 0 },
      { "kind": "break", "start": 270, "end": 315, "from": "C001", "to": "C012", "f": 0.49 },
      { "kind": "rest",  "start": 585, "end": 1245, "from": "C001", "to": "C012", "f": 0.98 },
      { "kind": "wait",  "start": 1250, "end": 1300, "city": "C012", "order": "O002" },
      { "kind": "service", "start": 1300, "end": 1330, "city": "C012", "order": "O002", "action": "pickup" }
    ]
  } ],

  "orders": [ {
    "id": "O002", "pickup_city": "C012", "delivery_city": "C045", "weight_kg": 5300,
    "required_truck_type": null, "value": 1.5,
    "pickup_window": null, "delivery_window": { "from": 3915, "to": 4155 },
    "truck": "T01",                         // null if unserved
    "status": "on_time",                    // on_time | late (<= 60 min, reduced value) | unserved
    "late_min": 0, "direct_km": 1586
  } ],

  "kpis": { "score": 932.22, "total_km": 170527, "loaded_km": 169058, "empty_km": 1469,
            "total_cost": 0, "total_co2": 0, "orders_fulfilled": 179, "orders_total": 200,
            "value_fulfilled": 0, "value_total": 0, "truck_utilization": 0.0,
            "orders_late": 0, "orders_too_late": 0, "total_late_min": 0, "penalized_late_min": 0,
            "breakdown": { "fulfillment": 86.7, "cost_efficiency": 100.0, "loaded_ratio": 99.14,
                           "co2_efficiency": 100.0, "penalty": 0, "late_penalty": 0.15 },
            "violations": 0, "trucks_used": 24 },

  "bounds": { "window_orders": 63,          // orders with a time window
              "window_served": 42,          // served by this plan
              "window_max": 42,             // most that can be served at all (chessboard)
              "window_max_proven": true,    // enumeration complete
              "score_upper_bound": 935.15,  // Lagrangian bound: no plan can score more (docs/UPPER_BOUND.md)
              "fulfillment_upper_bound": 87.03 },

  "stages": [                               // before/after story, in order
    { "name": "naive round robin", "score": 480.6, "orders_fulfilled": 0, "breakdown": {},
      "total_km": 0, "empty_km": 0 },
    { "name": "chessboard (CP-SAT window placement + regret insertion)", "score": 931.0 },
    { "name": "final (ALNS + set partitioning)", "score": 932.22 }
  ],

  "search_history": [                       // ALNS run, <= ~600 points ("nitro tank")
    { "it": 1, "t": 0.0, "best": 923.86, "cur": 923.86, "T": 2.0, "acc": 0.25 }
  ]
}
```

## Rendering notes
- **Truck position at minute `t`:** find the segment with `start <= t < end`.
  - `drive`: the truck is on the straight line from `from` to `to`, at fraction `f0 + (f1 - f0) * (t - start) / (end - start)`.
  - `break` / `rest`: it stands at fraction `f` of that leg (a rest stop by the road).
  - `wait` / `service`: it is in `city`.
  - Before its first segment the truck is at `start_city`; after its last one, at the last stop's city.
- Distances are approximate road km (great-circle × 1.3), so straight lines between cities are the honest drawing.
- **Cargo:** every segment has `loaded` (at least one order on board) and `load_kg`. Draw the red
  delivery box behind the truck while `loaded` is true; this also holds during break/rest/wait/service.
  For a `service` segment the values are the load *before* that pickup/delivery, so the box appears
  right after a pickup's service and disappears after the last delivery's service.
- Gantt colours by `kind`: drive (`loaded` true/false can be two shades), service, wait, break, rest.
- `search_history.best` only rises. Plot it against `t` (seconds) for the "nitro tank" chart.
- Example numbers above are illustrative. Always read the real file.
