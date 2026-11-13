"""Plan files and the best-plan archive.

A plan is the API submission format: {truck_id: [{"action": ..., "order": ...}, ...]}.
Every plan we produce is saved under results/<scenario>/ with its metadata, and
results/<scenario>/best.json always holds the highest-scoring valid plan so far
for the current scenario data (tracked by fingerprint).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"

Plan = dict[str, list[dict[str, str]]]


def save_plan(plan: Plan, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=1))


def load_plan(path: Path) -> Plan:
    return json.loads(Path(path).read_text())


def archive(plan: Plan, scenario: str, score: float, *, fingerprint: str, source: str,
            valid: bool, extra: dict | None = None, results_dir: Path = RESULTS_DIR) -> bool:
    """Store a plan; update best.json if it is valid and beats the current best.

    Returns True when the plan became the new best.
    """
    folder = results_dir / scenario
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    meta = {"scenario": scenario, "score": score, "valid": valid, "source": source,
            "fingerprint": fingerprint, "saved_at": stamp, **(extra or {})}
    save_plan({"meta": meta, "plan": plan}, folder / "history" / f"{stamp}_{source}.json")

    best_file = folder / "best.json"
    if valid:
        best = json.loads(best_file.read_text()) if best_file.exists() else None
        stale = best is not None and best["meta"].get("fingerprint") != fingerprint
        if best is None or stale or score > best["meta"]["score"]:
            save_plan({"meta": meta, "plan": plan}, best_file)
            return True
    return False


def best_plan(scenario: str, results_dir: Path = RESULTS_DIR) -> dict | None:
    f = results_dir / scenario / "best.json"
    return json.loads(f.read_text()) if f.exists() else None
