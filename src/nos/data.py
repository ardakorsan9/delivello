"""Load a downloaded scenario (data/<scenario>/*.json) into typed objects.

Cities, trucks and orders keep their API ids; `idx` maps a city id to its row in
the numpy distance matrix so hot loops can use integer indexing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@dataclass(frozen=True)
class City:
    id: str
    name: str
    country: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Truck:
    id: str
    start_city: str
    capacity_kg: int
    type: str
    cost_per_km: float
    co2_per_km: float


@dataclass(frozen=True)
class TimeWindow:
    start: int  # minutes since plan start (Day 1, 06:00)
    end: int


@dataclass(frozen=True)
class Order:
    id: str
    pickup_city: str
    delivery_city: str
    weight_kg: int
    required_truck_type: str | None
    pickup_window: TimeWindow | None
    delivery_window: TimeWindow | None
    value: float


@dataclass
class Scenario:
    id: str
    cities: dict[str, City]
    trucks: dict[str, Truck]
    orders: dict[str, Order]
    dist: np.ndarray          # km, shape (n_cities, n_cities)
    idx: dict[str, int]       # city id -> row/col in dist
    fingerprint: str = ""

    def km(self, a: str, b: str) -> float:
        return float(self.dist[self.idx[a], self.idx[b]])


def _tw(d: dict | None) -> TimeWindow | None:
    return TimeWindow(d["from"], d["to"]) if d else None


def load_scenario(scenario_id: str, data_dir: Path = DATA_DIR) -> Scenario:
    folder = data_dir / scenario_id
    if not folder.exists():
        raise FileNotFoundError(f"{folder} not found - run scripts/fetch_data.py first")

    def read(name: str):
        return json.loads((folder / f"{name}.json").read_text())

    cities = {c["id"]: City(c["id"], c["name"], c["country"], c["latitude"], c["longitude"])
              for c in read("cities")}
    trucks = {t["id"]: Truck(t["id"], t["start_city"], t["capacity_kg"], t["type"],
                             t["cost_per_km"], t["co2_per_km"]) for t in read("trucks")}
    orders = {o["id"]: Order(o["id"], o["pickup_city"], o["delivery_city"], o["weight_kg"],
                             o.get("required_truck_type"), _tw(o.get("pickup_window")),
                             _tw(o.get("delivery_window")), float(o["value"])) for o in read("orders")}

    matrix = read("distance_matrix")
    ids = sorted(matrix)
    idx = {cid: i for i, cid in enumerate(ids)}
    dist = np.array([[matrix[a][b] for b in ids] for a in ids], dtype=float)

    meta_file = folder / "meta.json"
    fp = json.loads(meta_file.read_text()).get("fingerprint", "") if meta_file.exists() else ""
    return Scenario(scenario_id, cities, trucks, orders, dist, idx, fp)
