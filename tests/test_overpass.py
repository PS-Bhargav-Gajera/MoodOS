"""The Overpass dependency must not be able to stall a /api/plan request.

`providers._overpass_query` is a single synchronous choke point sitting inside
the plan request. It used to allow 3 mirrors x 2 attempts x 20s -- roughly 131s
for one leg, plus an 18s restaurant leg that hardcoded its own URL and skipped
the mirrors entirely. When the public Overpass instance 504s (it does, under
load), `scripts/smoke_plan.py` would sit there until its 90s timeout expired
and no plan was ever produced.

These tests pin the three guarantees that replace that:
  * a hard total budget per query,
  * a circuit breaker that stops calling OSM once it is clearly down,
  * one choke point, so no leg can grow its own private timeout again.
"""

import inspect
import time

import pytest

from moodos import providers as p
from moodos.config import settings


# --------------------------------------------------------------- fakes

class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.text = ""

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, script, attempts):
        self._script = script
        self._attempts = attempts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, content=None, **kw):
        self._attempts.append(url)
        outcome = self._script(url, len(self._attempts))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _install(monkeypatch, script):
    """Replace httpx.Client with one that records attempts and replays `script`."""
    attempts: list[str] = []
    monkeypatch.setattr(
        p.httpx, "Client", lambda **kw: _FakeClient(script, attempts)
    )
    return attempts


def _always(*outcome):
    def script(_url, _n):
        return outcome[0] if len(outcome) == 1 else outcome[min(_n - 1, len(outcome) - 1)]
    return script


def _fast_budget(monkeypatch, budget=0.4, timeout=0.2, trip=3, cooldown=60.0):
    monkeypatch.setattr(settings, "overpass_budget_s", budget)
    monkeypatch.setattr(settings, "overpass_timeout_s", timeout)
    monkeypatch.setattr(settings, "overpass_trip_after", trip)
    monkeypatch.setattr(settings, "overpass_cooldown_s", cooldown)
    # Never let a real mirror be dialled during a test.
    monkeypatch.setattr(
        settings, "overpass_url", "https://primary.test/api/interpreter"
    )
    monkeypatch.setattr(
        settings, "overpass_mirrors",
        "https://a.test/api/interpreter,https://b.test/api/interpreter",
    )


# ------------------------------------------------------------ the budget

def test_overpass_query_respects_the_total_budget(monkeypatch):
    """Every attempt hangs. The query must still return near the budget."""
    _fast_budget(monkeypatch, budget=0.4)
    _install(monkeypatch, _always(TimeoutError("read timed out")))

    t0 = time.monotonic()
    result = p._overpass_query("[out:json];")
    elapsed = time.monotonic() - t0

    assert result is None
    # Budget plus slack for the fake client; the old code took ~131s here.
    assert elapsed < 3.0, f"took {elapsed:.1f}s, budget was 0.4s"


def test_budget_stops_retrying_before_exhausting_every_mirror(monkeypatch):
    _fast_budget(monkeypatch, budget=0.3)
    attempts = _install(monkeypatch, _always(TimeoutError("read timed out")))

    p._overpass_query("[out:json];")

    # 3 mirrors x 2 attempts would be 6. The deadline must cut it short.
    assert len(attempts) < 6, f"made {len(attempts)} attempts despite the budget"
    assert attempts, "no attempt was made at all"


def test_all_mirrors_failing_returns_none_without_raising(monkeypatch):
    _fast_budget(monkeypatch, budget=2.0)
    _install(monkeypatch, _always(_Resp(504)))

    assert p._overpass_query("[out:json];") is None


# ------------------------------------------------------------- the breaker

def test_breaker_opens_after_threshold_and_stops_calling(monkeypatch):
    _fast_budget(monkeypatch, budget=2.0, trip=2, cooldown=60.0)
    attempts = _install(monkeypatch, _always(TimeoutError("read timed out")))

    p._overpass_query("[out:json];")
    p._overpass_query("[out:json];")
    assert p._overpass_breaker_open() is True

    attempts.clear()
    p._overpass_query("[out:json];")

    assert attempts == [], "breaker was open but OSM was called anyway"


def test_breaker_resets_after_a_success(monkeypatch):
    _fast_budget(monkeypatch, budget=0.4, trip=1, cooldown=0.15)
    _install(monkeypatch, _always(TimeoutError("read timed out")))
    p._overpass_query("[out:json];")
    assert p._overpass_breaker_open() is True

    # A success can only be observed once the cooldown lets a probe through;
    # while the breaker is open the whole point is that OSM is not called.
    time.sleep(0.2)
    attempts = _install(monkeypatch, _always(_Resp(200, {"elements": []})))

    assert p._overpass_query("[out:json];") == {"elements": []}
    assert p._overpass_breaker_open() is False
    assert attempts, "breaker was still open, so OSM was never retried"


def test_breaker_probes_again_once_the_cooldown_elapses(monkeypatch):
    _fast_budget(monkeypatch, budget=2.0, trip=1, cooldown=0.15)
    attempts = _install(monkeypatch, _always(TimeoutError("read timed out")))
    p._overpass_query("[out:json];")
    assert p._overpass_breaker_open() is True

    time.sleep(0.2)
    attempts = _install(monkeypatch, _always(_Resp(200, {"elements": []})))
    p._overpass_query("[out:json];")

    assert attempts, "breaker never half-opened after the cooldown"


# -------------------------------------------------------------- the mirrors

def test_mirrors_come_from_settings_in_order(monkeypatch):
    monkeypatch.setattr(settings, "overpass_url", "https://primary.test/api")
    monkeypatch.setattr(
        settings, "overpass_mirrors", " https://a.test/api , https://a.test/api ,\n"
    )

    mirrors = p._overpass_mirrors()

    assert mirrors[0] == "https://primary.test/api", "primary must be tried first"
    assert mirrors == ("https://primary.test/api", "https://a.test/api"), mirrors


def test_mirrors_survive_an_empty_config(monkeypatch):
    monkeypatch.setattr(settings, "overpass_url", "https://only.test/api")
    monkeypatch.setattr(settings, "overpass_mirrors", "")

    assert p._overpass_mirrors() == ("https://only.test/api",)


def test_a_working_mirror_short_circuits_the_rest(monkeypatch):
    _fast_budget(monkeypatch, budget=5.0)
    attempts = _install(monkeypatch, _always(_Resp(200, {"elements": [{"id": 1}]})))

    assert p._overpass_query("[out:json];") == {"elements": [{"id": 1}]}
    assert len(attempts) == 1, "should stop at the first mirror that answers"


# ------------------------------------------- one choke point for every leg

def test_no_hardcoded_overpass_url_outside_the_wrapper():
    """Guards the regression that caused this: a leg with its own URL and its
    own timeout, silently outside the mirror/breaker protection."""
    src = inspect.getsource(p)
    # The default now lives in config.py, not in the call path.
    assert "overpass-api.de" not in src
    # And nothing posts to a literal interpreter URL any more.
    assert not [
        line for line in src.splitlines()
        if ".post(" in line and "/interpreter" in line
    ]


@pytest.mark.parametrize("call", [
    lambda: p.nearby_places(21.52, 70.46, query="cafe", limit=2),
    lambda: p.nearby_restaurants(21.52, 70.46, limit=2),
])
def test_osm_legs_go_through_the_wrapper(monkeypatch, call):
    """Both legs that used to hardcode a URL must now share the budget+breaker."""
    seen: list[str] = []

    def fake_query(query):
        seen.append(query)
        return {"elements": []}

    monkeypatch.setattr(p, "_overpass_query", fake_query)
    monkeypatch.setattr(p.ttl_cache, "get", lambda key, **kw: None)
    monkeypatch.setattr(p.ttl_cache, "set", lambda *a, **kw: None)

    call()

    assert seen, "leg did not use the shared _overpass_query choke point"


def test_leg_degrades_to_empty_when_the_breaker_is_open(monkeypatch):
    """An open breaker must yield an empty leg, not a hang and not a raise."""
    _fast_budget(monkeypatch, budget=1.0, trip=1, cooldown=60.0)
    _install(monkeypatch, _always(TimeoutError("read timed out")))
    p._overpass_query("[out:json];")  # trips the breaker

    monkeypatch.setattr(p.ttl_cache, "get", lambda key, **kw: None)
    monkeypatch.setattr(p.ttl_cache, "set", lambda *a, **kw: None)

    t0 = time.monotonic()
    assert p.nearby_places(21.52, 70.46, query="cafe", limit=2) == []
    assert p.nearby_restaurants(21.52, 70.46, limit=2) == []
    assert time.monotonic() - t0 < 2.0, "an open breaker must return immediately"
