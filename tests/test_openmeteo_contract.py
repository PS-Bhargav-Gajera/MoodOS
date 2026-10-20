"""Section 2 contract test — Open-Meteo row (Phase 2).

| Input  | Must return              | On failure (fallback)                        |
|--------|--------------------------|----------------------------------------------|
| lat/lon| temperature, rain chance | assume neutral weather, add an indoor option |

Everything here runs offline: `httpx.Client` is replaced, so no forecast is
ever fetched. The four checklist items map to tests below:

  * happy path: correct output shape
  * empty or odd input: no crash
  * timeout or wrong key: graceful fallback (neutral weather + indoor option)
  * slow response: the request is bounded by OPEN_METEO_TIMEOUT_S
"""

from __future__ import annotations

import httpx
import pytest

from moodos import providers as prov
from moodos.geo import ProviderUnavailable
from moodos.orchestrator import _assemble_plan, _DUR_CAPS

_LAT, _LON = 23.0225, 72.5714

_CAFE = {
    "id": "osm:c1", "kind": "place", "subtype": "cafe",
    "title": "Cafe One", "lat": _LAT + 0.0003, "lon": _LON + 0.0005,
    "estimated_cost": 120, "duration_min": 45,
    "intensity": "low", "crowded": False, "distance_km": 0.1,
    "final_score": 0.86,
}


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    """Records how it was constructed, then replays one outcome."""

    def __init__(self, outcome, seen, kwargs):
        self._outcome = outcome
        self._seen = seen
        self._kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kw):
        self._seen.append({"url": url, "timeout": self._kwargs.get("timeout"), **kw})
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return _Resp(self._outcome)


def _install(monkeypatch, outcome):
    """Replace providers.httpx.Client; returns the list of recorded calls."""
    seen: list[dict] = []
    monkeypatch.setattr(
        prov.httpx,
        "Client",
        lambda **kwargs: _Client(outcome, seen, kwargs),
    )
    return seen


def _live_payload(temperature=27.0, weather_code=0, precipitation=0.0):
    return {"current": {
        "temperature_2m": temperature,
        "weather_code": weather_code,
        "precipitation": precipitation,
        "wind_speed_10m": 4.0,
    }}


def _slots(**over):
    base = {
        "current_mood": "exhausted", "desired_mood": "relaxed",
        "intensity": "low", "social": "solo", "budget_inr": 1000,
        "duration_hours": 2.0, "music_language": None,
        "food_priority": False, "stay_home": False, "want_movie": False,
    }
    base.update(over)
    return base


def _plan(steps):
    return {
        "steps": steps,
        "total_duration_min": int(sum(int(s.get("duration_min") or 0) for s in steps)),
        "total_cost_inr": int(sum(int(s.get("cost_inr") or 0) for s in steps)),
    }


def _steps():
    return [
        {"order": 1, "kind": "cafe", "title": "Cafe One",
         "duration_min": 45, "cost_inr": 120, "flexible": True},
    ]


# --------------------------------------------------------------- checklist
# Happy path: correct output shape.

def test_happy_path_returns_temperature_and_rain_chance(monkeypatch):
    monkeypatch.setattr(prov.ttl_cache, "set", lambda *a, **k: None)
    _install(monkeypatch, _live_payload(temperature=31.0, precipitation=1.2))

    out = prov.get_weather(_LAT, _LON)

    assert out["temperature_c"] == 31.0
    assert out["rainy"] is True          # rain chance, derived from code+precip
    assert isinstance(out["condition"], str) and out["condition"]
    assert out["source"] == "open-meteo"
    assert out["freshness"] == "live"
    # A live read must NOT ask the planner for the fallback option.
    assert "indoor_recommended" not in out


# Slow response: the forecast request is bounded by its own timeout.

def test_forecast_request_is_bounded_by_the_open_meteo_timeout(monkeypatch):
    monkeypatch.setattr(prov.ttl_cache, "set", lambda *a, **k: None)
    seen = _install(monkeypatch, _live_payload())

    prov.get_weather(_LAT, _LON)

    assert seen, "the forecast request was never made"
    assert seen[0]["timeout"] == prov.OPEN_METEO_TIMEOUT_S
    assert seen[0]["timeout"] > 0
    assert seen[0]["url"].startswith("https://api.open-meteo.com/")


# Timeout: graceful fallback — neutral weather, no crash, no invented rain.

def test_timeout_falls_back_to_neutral_weather(monkeypatch):
    _install(monkeypatch, httpx.TimeoutException("simulated read timeout"))

    out = prov.get_weather(_LAT, _LON)   # non-strict: the plan path

    assert out["temperature_c"] is None
    assert out["rainy"] is None          # neutral: not "dry", not "wet"
    assert out["condition"] == "unknown"
    assert out["source"] == "unavailable"
    assert out["freshness"] == "unknown"
    assert out["indoor_recommended"] is True   # ...and carry an indoor option
    # The failure must not be frozen into the cache.
    assert prov.ttl_cache.get(f"weather:{round(_LAT, 3)}:{round(_LON, 3)}") is None


def test_timeout_in_strict_mode_raises_provider_unavailable(monkeypatch):
    """mcp_server.get_weather runs strict, so the tool reports an honest 503."""
    _install(monkeypatch, httpx.TimeoutException("simulated read timeout"))

    with pytest.raises(ProviderUnavailable):
        prov.get_weather(_LAT, _LON, strict=True)


# Empty or odd input: no crash.

def test_odd_payload_does_not_raise(monkeypatch):
    monkeypatch.setattr(prov.ttl_cache, "set", lambda *a, **k: None)
    for payload in ({}, {"error": "no lat/lon"}, []):
        _install(monkeypatch, payload)
        out = prov.get_weather(_LAT, _LON)
        assert isinstance(out, dict)
        assert out["lat"] == _LAT and out["lon"] == _LON


# HTTP 200 is not proof of dry weather: a 200 carrying an error body, or a
# "current" block with nulls, must reach the neutral fallback and must never
# be frozen into the 15-minute cache as "clear, dry, live".

def _key():
    return f"weather:{round(_LAT, 3)}:{round(_LON, 3)}"


def test_200_with_error_body_is_neutral_and_not_cached(monkeypatch):
    _install(monkeypatch, {"error": True, "reason": "Invalid coordinates"})

    out = prov.get_weather(_LAT, _LON)

    assert out["rainy"] is None
    assert out["condition"] == "unknown"
    assert out["source"] == "unavailable"
    assert out["indoor_recommended"] is True
    assert prov.ttl_cache.get(_key()) is None


def test_current_with_null_values_is_neutral_and_not_cached(monkeypatch):
    """200 + {"current": {...: null}} -- the block exists but says nothing."""
    _install(monkeypatch, {"current": {
        "temperature_2m": None,
        "weather_code": None,
        "precipitation": None,
        "wind_speed_10m": None,
    }})

    out = prov.get_weather(_LAT, _LON)

    assert out["rainy"] is None
    assert out["condition"] == "unknown"
    assert out["source"] == "unavailable"
    assert prov.ttl_cache.get(_key()) is None


def test_normal_200_populates_the_same_cache_key(monkeypatch):
    """Control: a good 200 still caches under the very key the failure tests
    assert is empty, and the second call is served without a refetch."""
    seen = _install(monkeypatch, _live_payload(temperature=28.5))

    first = prov.get_weather(_LAT, _LON)
    cached = prov.ttl_cache.get(_key())

    assert cached is not None, "a normal 200 must be cached under the weather key"
    assert cached == first
    assert first["rainy"] is False and first["source"] == "open-meteo"

    second = prov.get_weather(_LAT, _LON)
    assert second == first
    assert len(seen) == 1, "second call must be served from cache, not the network"


# Fallback: the neutral payload really does put an indoor option in the plan.

def test_fallback_payload_adds_an_indoor_step_to_the_plan(monkeypatch):
    _install(monkeypatch, httpx.TimeoutException("simulated read timeout"))
    weather = prov.get_weather(_LAT, _LON)          # neutral + indoor_recommended

    result = _assemble_plan(
        _plan(_steps()), [_CAFE], _slots(), _LAT, _LON, [], weather=weather,
    )

    indoor = [s for s in result["steps"] if s.get("kind") == "indoor"]
    assert len(indoor) == 1, result["steps"]
    assert indoor[0]["duration_min"] <= _DUR_CAPS["indoor"]
    assert indoor[0].get("why")
    # Order stays a clean 1..N sequence after the insertion.
    assert [s["order"] for s in result["steps"]] == list(
        range(1, len(result["steps"]) + 1)
    )
    assert result["budget_fit"]["within_tolerance"]


def test_live_weather_does_not_add_the_indoor_step(monkeypatch):
    """The indoor option is a fallback, not a permanent extra stop."""
    monkeypatch.setattr(prov.ttl_cache, "set", lambda *a, **k: None)
    _install(monkeypatch, _live_payload())
    weather = prov.get_weather(_LAT, _LON)

    result = _assemble_plan(
        _plan(_steps()), [_CAFE], _slots(), _LAT, _LON, [], weather=weather,
    )

    assert not [s for s in result["steps"] if s.get("kind") == "indoor"]


def test_indoor_option_is_not_duplicated(monkeypatch):
    """The rainy branch of _heuristic_plan may already have added one."""
    _install(monkeypatch, httpx.TimeoutException("simulated read timeout"))
    weather = prov.get_weather(_LAT, _LON)
    steps = _steps() + [
        {"order": 2, "kind": "indoor", "title": "Short indoor pause at a quiet cafe (rain)",
         "duration_min": 15, "cost_inr": 0, "flexible": True},
    ]

    result = _assemble_plan(_plan(steps), [_CAFE], _slots(), _LAT, _LON, [],
                            weather=weather)

    assert len([s for s in result["steps"] if s.get("kind") == "indoor"]) == 1


def test_stay_home_plan_does_not_get_an_outdoor_backup(monkeypatch):
    """Everything in a stay-home plan is already indoors."""
    _install(monkeypatch, httpx.TimeoutException("simulated read timeout"))
    weather = prov.get_weather(_LAT, _LON)

    result = _assemble_plan(
        _plan(_steps()), [_CAFE], _slots(stay_home=True), _LAT, _LON, [],
        weather=weather,
    )

    assert not [s for s in result["steps"] if s.get("kind") == "indoor"]
