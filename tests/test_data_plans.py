import json

from nos.data import DATA_DIR, load_scenario
from nos.plans import archive, best_plan


def test_load_small_scenario():
    s = load_scenario("scenario_small")
    assert len(s.trucks) == 4 and len(s.orders) == 20 and len(s.cities) == 10
    assert s.dist.shape == (10, 10)
    assert (s.dist == s.dist.T).all() and (s.dist.diagonal() == 0).all()
    o = next(iter(s.orders.values()))
    raw = json.loads((DATA_DIR / "scenario_small" / "distance_matrix.json").read_text())
    assert s.km(o.pickup_city, o.delivery_city) == raw[o.pickup_city][o.delivery_city]


def test_archive_keeps_best_valid(tmp_path):
    p1, p2, p3 = {"T01": []}, {"T02": []}, {"T03": []}
    assert archive(p1, "sc", 100, fingerprint="a", source="t", valid=True, results_dir=tmp_path)
    assert not archive(p2, "sc", 90, fingerprint="a", source="t", valid=True, results_dir=tmp_path)
    assert not archive(p3, "sc", 999, fingerprint="a", source="t", valid=False, results_dir=tmp_path)
    assert best_plan("sc", tmp_path)["plan"] == p1
    # new scenario data (server restart) replaces a stale best even with a lower score
    assert archive(p2, "sc", 10, fingerprint="b", source="t", valid=True, results_dir=tmp_path)
    assert best_plan("sc", tmp_path)["plan"] == p2
