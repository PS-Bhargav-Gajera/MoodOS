"""Gap: intent extraction was unbudgeted (first LLM call in /api/plan).

`nlu.extract_intent` used to block the pipeline for its whole LLM chain
(Groq <=25s + up to 7 Gemini models x 25s ~= 200s worst case). It now runs the
LLM leg on a daemon thread with a hard join budget, like
`orchestrator._plan_with_budget`, and falls back to the heuristic slots.

What must hold:
  * it returns within EXTRACT_BUDGET_S (or close to it), not after the LLM
  * budget exhaustion -> heuristic slots, so the pipeline continues
  * an LLM that raises -> heuristic slots, no exception escapes
  * an LLM that answers instantly with {} -> heuristic slots, and NO
    "budget exceeded" log (that message must mean a real timeout)
  * an LLM that answers inside the budget is still used
"""

from __future__ import annotations

import logging
import time

from moodos import nlu

_MSG = "tired, want to relax"


def _base():
    return nlu.heuristic_extract(_MSG)


def _slow_llm(monkeypatch, delay=1.5, payload=None):
    """Fake LLM that answers only *after* the test's budget (default: marker)."""
    def fake(prompt: str):
        time.sleep(delay)
        return payload if payload is not None else {"_agent": "slow-llm"}
    monkeypatch.setattr(nlu.router, "extract_json", fake)
    # raising=False so this file also runs (and fails) before the fix exists.
    monkeypatch.setattr(nlu, "EXTRACT_BUDGET_S", 0.3, raising=False)


# --- 1. the budget itself -------------------------------------------------

def test_extract_intent_respects_its_time_budget(monkeypatch):
    _slow_llm(monkeypatch, delay=1.5)

    t0 = time.monotonic()
    nlu.extract_intent(_MSG)
    elapsed = time.monotonic() - t0

    assert elapsed < 1.0, f"extraction took {elapsed:.2f}s (budget is 0.3s)"


def test_budget_exhaustion_returns_heuristic_slots_so_pipeline_continues(monkeypatch):
    _slow_llm(monkeypatch, delay=1.5)

    out = nlu.extract_intent(_MSG)

    assert out == _base()
    assert out["_agent"] == "heuristic" and out["_model"] == "rules"
    for key in ("current_mood", "desired_mood", "intensity", "social",
                "duration_hours", "budget_inr", "party_size", "music_language"):
        assert key in out, key


def test_budget_timeout_is_logged_only_on_a_real_timeout(monkeypatch, caplog):
    _slow_llm(monkeypatch, delay=1.5)

    with caplog.at_level(logging.WARNING, logger="moodos.nlu"):
        nlu.extract_intent(_MSG)

    assert any("budget exceeded" in r.getMessage() for r in caplog.records), \
        "a real timeout must be logged as a budget overrun"


# --- 2. failure modes fall back to heuristic ------------------------------

def test_llm_exception_falls_back_to_heuristic(monkeypatch, caplog):
    def boom(prompt: str):
        raise RuntimeError("groq down")
    monkeypatch.setattr(nlu.router, "extract_json", boom)

    with caplog.at_level(logging.WARNING, logger="moodos.nlu"):
        out = nlu.extract_intent(_MSG)     # must not raise

    assert out == _base()
    assert not any("budget exceeded" in r.getMessage() for r in caplog.records)


def test_llm_returning_nothing_logs_no_budget_timeout(monkeypatch, caplog):
    monkeypatch.setattr(nlu.router, "extract_json", lambda prompt: {})

    with caplog.at_level(logging.WARNING, logger="moodos.nlu"):
        out = nlu.extract_intent(_MSG)

    assert out == _base()
    assert not any("budget exceeded" in r.getMessage() for r in caplog.records), \
        "an instant empty answer is not a timeout"
    assert any("LLM returned nothing" in r.getMessage() for r in caplog.records)


# --- control ---------------------------------------------------------------

def test_llm_answer_inside_the_budget_is_used(monkeypatch):
    monkeypatch.setattr(
        nlu.router, "extract_json",
        lambda prompt: {"_agent": "fast-llm", "current_mood": "tense"},
    )

    out = nlu.extract_intent("for 3 people, 1500 rupees, tense")

    assert out["_agent"] == "fast-llm"
    assert out["current_mood"] == "tense"
    # numeric slots stay owned by the heuristic parser
    assert out["budget_inr"] == nlu.heuristic_extract(
        "for 3 people, 1500 rupees, tense")["budget_inr"]
