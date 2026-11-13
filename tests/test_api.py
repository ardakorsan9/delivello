import pytest

from nos.api import GruberAPI


def test_competitive_score_needs_confirm():
    api = GruberAPI(api_key="dummy")
    with pytest.raises(RuntimeError, match="limited attempts"):
        api.score("scenario_competitive", {})
    with pytest.raises(RuntimeError, match="limited attempts"):
        api.simulate("scenario_competitive", {})


def test_missing_key_raises():
    api = GruberAPI(api_key=None)
    api.api_key = None
    with pytest.raises(RuntimeError, match="GRUBER_API_KEY"):
        api.validate("scenario_small", {})
