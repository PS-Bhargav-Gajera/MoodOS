"""Gap: `_tmdb_json` retried 12x with NO total budget.

12 attempts exist for FAST failures (the docstring's TLS-handshake drops cost
~0s each). A hung TMDB instead costs 12 x 12s per call, and callers chain
several calls per movie step, so one plan could block for minutes.

Contract under test (TMDB_BUDGET_S = 6.0):
  * hanging attempts -> {} returned within the budget, fewer than 12 attempts,
    and the "budget exhausted" warning is logged
  * the 12 retries for INSTANT failures survive the budget (guard)
  * the per-attempt httpx timeout is min(TIMEOUT, remaining), never more

Everything is deterministic: `prov.time.monotonic` is replaced by a fake clock
that the fake transport advances, so there are no real sleeps.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from moodos import providers as prov

BUDGET = 6.0    # the value being shipped as prov.TMDB_BUDGET_S
HANG = 2.0      # simulated duration of one hung attempt


class _Clock:
    """Fake monotonic clock: only advances when a hung attempt says so."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.start = start
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    @property
    def elapsed(self) -> float:
        return self.now - self.start


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload or {}


class _Script:
    """One outcome per attempt, plus every timeout it was offered."""

    def __init__(self, clock: _Clock, outcomes: list[tuple]) -> None:
        self.clock = clock
        self.outcomes = list(outcomes)
        self.attempts = 0
        self.timeouts: list[float] = []

    def make_client(self, **kwargs):
        self.timeouts.append(kwargs.get("timeout"))
        return _FakeClient(self)


class _FakeClient:
    def __init__(self, script: _Script) -> None:
        self._script = script

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        s = self._script
        kind, payload = s.outcomes[min(s.attempts, len(s.outcomes) - 1)]
        s.attempts += 1
        if kind == "hang":
            s.clock.advance(HANG)          # the hung attempt eats real time
            raise httpx.ReadTimeout("simulated hang")
        if kind == "fail":
            raise httpx.ConnectError("instant handshake drop")
        return _Resp(200, payload)


def _install(monkeypatch, clock: _Clock, outcomes: list[tuple]) -> _Script:
    script = _Script(clock, outcomes)
    monkeypatch.setattr(prov.httpx, "Client", script.make_client)
    # raising=False so this file also runs (and fails) before the fix exists.
    monkeypatch.setattr(prov, "TMDB_BUDGET_S", BUDGET, raising=False)
    monkeypatch.setattr(prov.time, "monotonic", clock)
    return script


# --- 1. hanging attempts are capped by the budget --------------------------

def test_hanging_attempts_stop_at_the_budget(monkeypatch, caplog):
    clock = _Clock()
    script = _install(monkeypatch, clock, [("hang", None)] * 12)

    with caplog.at_level(logging.WARNING, logger="moodos.providers"):
        out = prov._tmdb_json("search/movie", {"query": "exhausted"})

    assert out == {}, "budget exhaustion must degrade to {} (no raise)"
    assert script.attempts < 12, f"made {script.attempts} attempts despite the budget"
    assert clock.elapsed <= BUDGET + 1e-9, \
        f"took {clock.elapsed:.2f}s, budget is {BUDGET:.1f}s"
    assert any("TMDB budget exhausted" in r.getMessage() for r in caplog.records), \
        "giving up on budget must be logged"


# --- 2. guard: the 12 fast retries survive ---------------------------------

def test_instant_failures_still_retry_and_succeed_on_attempt_three(monkeypatch):
    clock = _Clock()
    script = _install(
        monkeypatch, clock,
        [("fail", None), ("fail", None), ("ok", {"id": 7})],
    )

    out = prov._tmdb_json("search/movie", {"query": "eventually"})

    assert out == {"id": 7}, "a fast failure must not stop the retries"
    assert script.attempts == 3
    assert clock.elapsed == 0.0, "instant failures must not consume budget"


# --- 3. per-attempt timeout is bounded by the remaining budget -------------

def test_per_attempt_timeout_is_capped_by_the_remaining_budget(monkeypatch):
    clock = _Clock()
    script = _install(monkeypatch, clock, [("hang", None)] * 12)

    prov._tmdb_json("search/movie", {"query": "slow"})

    assert script.timeouts, "no request was made"
    assert script.timeouts[0] == min(prov.TIMEOUT, BUDGET)
    # every later attempt may only be offered what is left of the budget
    for i, offered in enumerate(script.timeouts[1:], start=1):
        assert offered <= BUDGET
        assert offered < prov.TIMEOUT, \
            f"attempt {i + 1} was offered the full {offered}s instead of the remainder"
    assert script.timeouts == sorted(script.timeouts, reverse=True)
