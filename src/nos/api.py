"""Thin client for the GRUBER Hackathon 2026 API.

Scenario endpoints are public. Submission endpoints need the team key (X-Api-Key).
On scenario_competitive, Score and Simulate are limited (default 3 each), so those
calls require an explicit confirm=True.
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "https://hackathon-challenge.gruber-logistics.dev/Hackaton2026"
LIMITED_SCENARIOS = {"scenario_competitive"}
TIMEOUT_S = 60


class GruberAPI:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.base_url = (base_url or os.getenv("GRUBER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or os.getenv("GRUBER_API_KEY") or None
        self.session = requests.Session()

    # ---------- public scenario data ----------
    def _get(self, path: str):
        r = self.session.get(f"{self.base_url}{path}", timeout=TIMEOUT_S)
        r.raise_for_status()
        return r.json()

    def scenarios(self) -> list[dict]:
        return self._get("/Scenarios")

    def cities(self, scenario: str) -> list[dict]:
        return self._get(f"/Scenarios/{scenario}/Cities")

    def trucks(self, scenario: str) -> list[dict]:
        return self._get(f"/Scenarios/{scenario}/Trucks")

    def orders(self, scenario: str) -> list[dict]:
        return self._get(f"/Scenarios/{scenario}/Orders")

    def distance_matrix(self, scenario: str) -> dict[str, dict[str, float]]:
        return self._get(f"/Scenarios/{scenario}/DistanceMatrix")

    def sample_plan(self, scenario: str) -> dict:
        return self._get(f"/Scenarios/{scenario}/SamplePlan")

    # ---------- authenticated ----------
    def _headers(self) -> dict:
        if not self.api_key:
            raise RuntimeError("GRUBER_API_KEY is not set. Copy .env.example to .env and fill it in.")
        return {"X-Api-Key": self.api_key}

    def register_team(self, name: str) -> dict:
        r = self.session.post(f"{self.base_url}/Team/Register", json={"name": name},
                              headers=self._headers(), timeout=TIMEOUT_S)
        r.raise_for_status()
        return r.json()

    def _submit(self, kind: str, scenario: str, plan: dict, confirm: bool) -> dict:
        if kind in ("Score", "Simulate") and scenario in LIMITED_SCENARIOS and not confirm:
            raise RuntimeError(
                f"{kind} on {scenario} uses one of the limited attempts. Pass confirm=True to really send it."
            )
        r = self.session.post(f"{self.base_url}/Submissions/{scenario}/{kind}", json=plan,
                              headers=self._headers(), timeout=TIMEOUT_S)
        r.raise_for_status()
        return r.json()

    def validate(self, scenario: str, plan: dict) -> dict:
        return self._submit("Validate", scenario, plan, confirm=True)

    def simulate(self, scenario: str, plan: dict, confirm: bool = False) -> dict:
        return self._submit("Simulate", scenario, plan, confirm)

    def score(self, scenario: str, plan: dict, confirm: bool = False) -> dict:
        return self._submit("Score", scenario, plan, confirm)
