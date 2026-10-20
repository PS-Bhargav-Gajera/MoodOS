"""Crisis short-circuit: deterministic phrase check before any LLM, pipeline,
location network call, or write. Tests first — this module fails on import
until moodos/crisis.py exists (module-level import below)."""

import logging

import pytest
from moodos.crisis import TELE_MANAS_HELP, is_crisis
from moodos.llm import router
from moodos.memory import mem0
from moodos import orchestrator as orch

# --- must trigger ----------------------------------------------------------

CRISIS_TRIGGER = [
    "I feel hopeless and I don't want to be here anymore",  # the exact probe
    "I want to end my life",
    "thinking about suicide",
    "I don't want to live anymore",
]

# --- must NOT trigger ------------------------------------------------------

CRISIS_CONTROL = [
    "I'm tired and sad",
    "feeling hopeless today",
    "start with dinner and end it with a movie",
    "I want to watch Suicide Squad tonight",
    "I hurt myself playing football, plan a quiet evening",
    "Plan a quiet evening for 2 hours, budget 500 rupees",
]


@pytest.mark.parametrize("msg", CRISIS_TRIGGER)
def test_is_crisis_true(msg):
    assert is_crisis(msg) is True


@pytest.mark.parametrize("msg", CRISIS_CONTROL)
def test_is_crisis_false(msg):
    assert is_crisis(msg) is False


@pytest.fixture
def nothing_heavy(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("crisis path must not run this")

    monkeypatch.setattr(orch, "run_pipeline", boom)
    monkeypatch.setattr(router, "extract_json", boom)
    monkeypatch.setattr(router, "plan_json", boom)
    monkeypatch.setattr(mem0, "add", boom)
    monkeypatch.setattr(orch, "save_event", boom)


@pytest.mark.parametrize("msg", CRISIS_TRIGGER)
def test_handle_message_short_circuits_without_pipeline_or_llm(msg, nothing_heavy):
    out = orch.handle_message(msg, "demo")
    assert out["mode"] == "chat"
    assert out["plan"] is None
    assert "14416" in out["reply"]
    assert "1-800-891-4416" in out["reply"]
    assert "112" in out["reply"]
    assert "trust" in out["reply"].lower()
    # app.py does bundle.setdefault("location", {})["resolver"] = ... after
    # handle_message; a None location would 500 there. Omitted or dict is fine.
    assert out.get("location") in (None, {}) or isinstance(out.get("location"), dict)


@pytest.mark.parametrize("msg", CRISIS_CONTROL[:3] + CRISIS_CONTROL[5:])
def test_controls_still_reach_run_pipeline(msg, monkeypatch):
    called = []

    def fake_pipeline(*a, **k):
        called.append(a[0] if a else k.get("message"))
        return {"mode": "plan", "plan": {"steps": []}}

    monkeypatch.setattr(orch, "run_pipeline", fake_pipeline)
    out = orch.handle_message(msg, "demo")
    assert called, "crisis guard intercepted a normal planning request"
    assert out["mode"] == "plan"


def test_crisis_path_never_logs_message(caplog, nothing_heavy):
    msg = "I want to end my life"
    with caplog.at_level(logging.DEBUG):
        orch.handle_message(msg, "demo")
    offenders = [r for r in caplog.records if msg.lower() in r.getMessage().lower()]
    assert not offenders, f"crisis message text was logged: {offenders}"


def test_plan_route_crisis_beats_location_resolution(monkeypatch):
    """End-to-end through the HTTP route: 200, chat reply, no location work."""
    import app as appmod
    from fastapi.testclient import TestClient

    def boom(*a, **k):
        raise AssertionError("crisis must return before location/pipeline")

    monkeypatch.setattr(appmod, "resolve_location", boom)
    monkeypatch.setattr(appmod, "handle_message", boom)
    client = TestClient(appmod.app)
    res = client.post("/api/plan", json={
        "message": "I feel hopeless and I don't want to be here anymore",
        "user_id": "crisis_test",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "chat"
    assert body["plan"] is None
    assert "14416" in body["reply"]
    assert "1-800-891-4416" in body["reply"]
    assert "112" in body["reply"]


def test_tele_manas_constant_mentions_both_numbers_and_112():
    assert "14416" in TELE_MANAS_HELP
    assert "1-800-891-4416" in TELE_MANAS_HELP
    assert "112" in TELE_MANAS_HELP
