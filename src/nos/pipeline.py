"""End-to-end solve pipeline: start -> parallel ALNS -> set-partitioning polish.

1. Start from the better of: the stored best plan (same data fingerprint) and the
   chessboard plan (optimal window placement + regret insertion).
2. Run ALNS in `workers` processes with different seeds for the same time budget.
3. Merge the route pools of all workers (and earlier runs) and polish the best
   plan by set partitioning.
The caller verifies with the exact simulator and archives only a better plan.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import time
from pathlib import Path

from .alns import ALNS
from .chessboard import solve as chessboard
from .construct import Insertion
from .data import load_scenario
from .evaluate import Model
from .plans import RESULTS_DIR, best_plan
from .polish import set_partition


def routes_from_plan(m: Model, plan: dict) -> list:
    oi = {o: k for k, o in enumerate(m.order_ids)}
    routes = [[] for _ in range(m.n_trucks)]
    for tid, stops in plan.items():
        routes[m.truck_ids.index(tid)] = [(oi[s["order"]], s["action"] == "pickup") for s in stops]
    return routes


def pool_path(scenario: str) -> Path:
    return RESULTS_DIR / scenario / "route_pool.json"


def load_pool(scenario: str, fingerprint: str, n_trucks: int) -> dict[int, set]:
    pool: dict[int, set] = {t: set() for t in range(n_trucks)}
    f = pool_path(scenario)
    if f.exists():
        d = json.loads(f.read_text())
        if d.get("fingerprint") == fingerprint:
            for t, rs in d["pool"].items():
                pool[int(t)] |= {tuple((o, bool(p)) for o, p in r) for r in rs}
    return pool


def save_pool(scenario: str, fingerprint: str, pool: dict[int, set], cap: int = 5000) -> None:
    f = pool_path(scenario)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"fingerprint": fingerprint,
                             "pool": {t: [list(map(list, r)) for r in list(rs)[:cap]]
                                      for t, rs in pool.items()}}))


def start_solution(m: Model, scenario: str, log=print, fresh: bool = False) -> Insertion:
    cands = []
    stored = None if fresh else best_plan(scenario)
    if stored and stored["meta"].get("fingerprint") == m.sc.fingerprint:
        cands.append(("best.json", Insertion(m, routes_from_plan(m, stored["plan"]))))
    t0 = time.perf_counter()
    cb = chessboard(m, verbose=False)
    log(f"  chessboard: {cb.window_served}/{cb.window_total} window orders "
        f"({'complete' if not cb.truncated_trucks else 'truncated'}), "
        f"score {cb.plan.score():.2f}, {time.perf_counter() - t0:.0f}s")
    cands.append(("chessboard", cb.plan))
    name, best = max(cands, key=lambda c: c[1].score())
    log(f"  start: {name} {best.score():.2f}")
    return best


def _worker(args):
    scenario, routes, seed, seconds, topn = args
    m = Model(load_scenario(scenario))
    res = ALNS(m, seed=seed, topn=topn).run(Insertion(m, routes), time_limit=seconds, verbose=False)
    return seed, res.best.routes, res.best.score(), res.pool, res.history, res.iterations


def parallel_alns(m: Model, scenario: str, start: Insertion, seconds: float, workers: int = 4,
                  topn: int = 12, seed0: int = 0, log=print):
    jobs = [(scenario, start.routes, seed0 + k, seconds, topn) for k in range(workers)]
    if workers == 1:
        outs = [_worker(jobs[0])]
    else:
        with mp.get_context("fork").Pool(workers) as p:
            outs = p.map(_worker, jobs)
    pool: dict[int, set] = {t: set() for t in range(m.n_trucks)}
    for _, _, _, pl, _, _ in outs:
        for t, rs in pl.items():
            pool[t] |= rs
    for seed, _, score, _, _, its in sorted(outs, key=lambda o: -o[2]):
        log(f"  seed {seed}: {score:.3f} ({its} iterations)")
    seed, routes, score, _, hist, its = max(outs, key=lambda o: o[2])
    return Insertion(m, routes), pool, hist, sum(o[5] for o in outs)


def run(scenario: str, seconds: float, workers: int = 4, polish: bool = True, seed0: int = 0,
        log=print, fresh: bool = False):
    """fresh: ignore the stored best plan and route pool (cold start, as after a server restart)."""
    sc = load_scenario(scenario)
    m = Model(sc)
    t0 = time.perf_counter()
    start = start_solution(m, scenario, log, fresh)
    best, hist, its = start, [], 0
    pool = ({t: set() for t in range(m.n_trucks)} if fresh
            else load_pool(scenario, sc.fingerprint, m.n_trucks))
    if seconds > 0:
        cand, new_pool, hist, its = parallel_alns(m, scenario, start, seconds, workers, seed0=seed0, log=log)
        for t, rs in new_pool.items():
            pool[t] |= rs
        if not fresh:
            save_pool(scenario, sc.fingerprint, pool)
        if cand.score() > best.score():
            best = cand
    if polish:
        best = set_partition(m, pool, best, verbose=False)
        log(f"  polish: {best.score():.3f}")
    log(f"  total {time.perf_counter() - t0:.0f}s, {its} ALNS iterations")
    return sc, m, start, best, hist
