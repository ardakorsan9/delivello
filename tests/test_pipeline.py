"""End-to-end pipeline on the downloaded small scenario (cold start, 2 workers)."""
from nos.pipeline import run
from nos.simulator import simulate


def test_cold_start_pipeline_small():
    sc, m, start, best, _ = run("scenario_small", seconds=3, workers=2, fresh=True, log=lambda *a: None)
    res = simulate(sc, m.to_plan(best.routes))
    assert res.violations == []
    assert best.score() >= start.score() - 1e-9
    assert abs(res.score - best.score()) < 0.011
