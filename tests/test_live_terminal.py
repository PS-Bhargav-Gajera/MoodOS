"""Tests for MoodOS Real-time Live Terminal Stream & Traffic Inspection."""

from __future__ import annotations

import json
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient

from app import app
from moodos.terminal_stream import terminal_bus


@pytest.fixture
def client():
    return TestClient(app)


def test_terminal_bus_history_and_events():
    terminal_bus.log_client_send("I need a break", user_id="test_user", lat=28.6, lon=77.2)
    terminal_bus.log_tool_call("test_tool", "param=123")
    terminal_bus.log_tool_result("test_tool", 45.2, "completed successfully")
    terminal_bus.log_step("test_step", "analyzing context")
    terminal_bus.log_response_sent(200, 1.25, "1 plan generated")

    history = terminal_bus.get_history()
    assert len(history) >= 5

    types = [h["type"] for h in history]
    assert "client_send" in types
    assert "tool_call" in types
    assert "tool_result" in types
    assert "step" in types
    assert "response_sent" in types


def test_live_terminal_history_endpoint(client):
    r = client.get("/api/live-terminal/history")
    assert r.status_code == 200
    data = r.json()
    assert "history" in data
    assert isinstance(data["history"], list)


def test_live_terminal_plan_integration(client):
    fake_reply = {
        "reply": "It looks like you're feeling stressed. Take care!",
        "mode": "chat",
    }
    with patch("moodos.chat.answer_chat", return_value=fake_reply), \
         patch("moodos.nlu.classify_turn", return_value={"mode": "chat"}):
        r = client.post("/api/plan", json={"message": "how's the weather today?", "user_id": "tester"})
        assert r.status_code == 200
        history = terminal_bus.get_history()
        # Ensure client_send was recorded
        send_events = [h for h in history if h.get("type") == "client_send" and h.get("user_id") == "tester"]
        assert len(send_events) >= 1
