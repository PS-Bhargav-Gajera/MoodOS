"""Tests for Open-Meteo Weather MCP Server and Client."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app as appmod
from moodos.weather_mcp import (
    OpenMeteoWeatherMCPClient,
    OpenMeteoWeatherMCPServer,
    WMO_WEATHER_CODES,
    evaluate_weather_for_activity,
    fetch_current_weather,
    fetch_hourly_forecast,
    fetch_weather_by_city,
    fetch_weather_forecast,
    get_wmo_info,
    weather_mcp_client,
    weather_mcp_server,
)


@pytest.fixture()
def client():
    return TestClient(appmod.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1. WMO Code Understanding Tests
# ---------------------------------------------------------------------------


def test_wmo_code_interpretation():
    # Clear sky
    clear = get_wmo_info(0)
    assert clear["condition"] == "clear"
    assert clear["rainy"] is False
    assert clear["outdoor_suitable"] is True

    # Rain
    rain = get_wmo_info(63)
    assert rain["condition"] == "rain"
    assert rain["rainy"] is True
    assert rain["outdoor_suitable"] is False

    # Thunderstorm
    storm = get_wmo_info(95)
    assert storm["condition"] == "thunderstorm"
    assert storm["rainy"] is True

    # Unknown code fallback
    unknown = get_wmo_info(9999)
    assert "mixed" in unknown["condition"]


# ---------------------------------------------------------------------------
# 2. Server Schema and Protocol Tests
# ---------------------------------------------------------------------------


def test_weather_mcp_server_tools_list():
    server = OpenMeteoWeatherMCPServer()
    tools = server.list_tools()
    names = {t["name"] for t in tools}
    assert {
        "get_current_weather",
        "get_weather_forecast",
        "get_hourly_forecast",
        "get_weather_by_city",
        "evaluate_weather_for_activity",
    } <= names

    for tool in tools:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema


def test_weather_mcp_server_jsonrpc_initialize():
    server = OpenMeteoWeatherMCPServer()
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    res = server.handle_jsonrpc(req)
    assert res["jsonrpc"] == "2.0"
    assert res["id"] == 1
    assert res["result"]["serverInfo"]["name"] == "open-meteo-weather-mcp"
    assert "tools" in res["result"]["capabilities"]


def test_weather_mcp_server_jsonrpc_tools_list():
    server = OpenMeteoWeatherMCPServer()
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    res = server.handle_jsonrpc(req)
    assert res["id"] == 2
    tools = res["result"]["tools"]
    assert len(tools) == 5


def test_weather_mcp_server_jsonrpc_tools_call():
    server = OpenMeteoWeatherMCPServer()
    fake_weather = {
        "temperature_c": 24.5,
        "condition": "clear",
        "rainy": False,
        "lat": 28.6139,
        "lon": 77.2090,
    }
    with patch("moodos.weather_mcp.fetch_current_weather", return_value=fake_weather):
        req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_current_weather", "arguments": {"lat": 28.6139, "lon": 77.2090}},
        }
        res = server.handle_jsonrpc(req)
        assert res["id"] == 3
        assert res["result"]["isError"] is False
        content_text = res["result"]["content"][0]["text"]
        parsed = json.loads(content_text)
        assert parsed["temperature_c"] == 24.5
        assert parsed["condition"] == "clear"


def test_weather_mcp_server_jsonrpc_unknown_method():
    server = OpenMeteoWeatherMCPServer()
    req = {"jsonrpc": "2.0", "id": 4, "method": "unknown_rpc", "params": {}}
    res = server.handle_jsonrpc(req)
    assert "error" in res
    assert res["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# 3. Client & Tool Implementation Tests
# ---------------------------------------------------------------------------


def test_weather_mcp_client_inprocess():
    client = OpenMeteoWeatherMCPClient()
    fake_weather = {"temperature_c": 22.0, "rainy": False, "condition": "clear"}
    with patch("moodos.weather_mcp.fetch_current_weather", return_value=fake_weather):
        res = client.get_current_weather(lat=23.0225, lon=72.5714)
        assert res["temperature_c"] == 22.0
        assert res["condition"] == "clear"


def test_evaluate_weather_for_activity():
    # Scenario A: Good outdoor walking conditions
    clear_weather = {
        "temperature_c": 22.0,
        "rainy": False,
        "wind_speed_kmh": 12.0,
        "condition": "clear",
    }
    with patch("moodos.weather_mcp.fetch_current_weather", return_value=clear_weather):
        res = evaluate_weather_for_activity(23.0225, 72.5714, activity="outdoor_walk")
        assert res["suitable"] is True
        assert res["indoor_recommended"] is False
        assert res["suitability_score"] >= 0.8

    # Scenario B: Rainy conditions -> outdoor activity unsuitable
    rainy_weather = {
        "temperature_c": 19.0,
        "rainy": True,
        "wind_speed_kmh": 25.0,
        "condition": "rain",
    }
    with patch("moodos.weather_mcp.fetch_current_weather", return_value=rainy_weather):
        res = evaluate_weather_for_activity(23.0225, 72.5714, activity="outdoor_walk")
        assert res["suitable"] is False
        assert res["indoor_recommended"] is True
        assert "Rain" in " ".join(res["reasons"])

    # Scenario C: Indoor cinema activity is always suitable
    with patch("moodos.weather_mcp.fetch_current_weather", return_value=rainy_weather):
        res = evaluate_weather_for_activity(23.0225, 72.5714, activity="movie_theater")
        assert res["suitable"] is True
        assert res["suitability_score"] == 1.0


def test_fetch_weather_by_city():
    fake_geo_resp = {
        "results": [{"name": "Ahmedabad", "latitude": 23.0225, "longitude": 72.5714, "country": "India"}]
    }
    fake_weather = {"temperature_c": 28.0, "condition": "clear", "rainy": False}
    fake_forecast = {"days": [{"date": "2026-10-21", "temp_max_c": 32.0}]}

    with patch("httpx.Client.get") as mock_get, \
         patch("moodos.weather_mcp.fetch_current_weather", return_value=fake_weather), \
         patch("moodos.weather_mcp.fetch_weather_forecast", return_value=fake_forecast):

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_geo_resp
        mock_get.return_value = mock_resp

        res = fetch_weather_by_city("Ahmedabad")
        assert res["found"] is True
        assert res["city"] == "Ahmedabad"
        assert res["current"]["temperature_c"] == 28.0


# ---------------------------------------------------------------------------
# 4. HTTP API Endpoint Tests in app.py
# ---------------------------------------------------------------------------


def test_api_weather_tools_endpoint(client):
    r = client.get("/mcp/weather/tools")
    assert r.status_code == 200
    data = r.json()
    assert "tools" in data
    assert len(data["tools"]) == 5


def test_api_weather_call_endpoint(client):
    fake_weather = {"temperature_c": 25.0, "condition": "clear", "rainy": False}
    with patch("moodos.weather_mcp.fetch_current_weather", return_value=fake_weather):
        r = client.post(
            "/mcp/weather/call",
            json={"tool": "get_current_weather", "arguments": {"lat": 28.6139, "lon": 77.2090}},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["tool"] == "get_current_weather"
        assert data["result"]["temperature_c"] == 25.0


def test_api_weather_jsonrpc_endpoint(client):
    r = client.post(
        "/mcp/weather",
        json={"jsonrpc": "2.0", "id": 42, "method": "tools/list", "params": {}},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 42
    assert len(data["result"]["tools"]) == 5


def test_api_weather_activity_endpoint(client):
    fake_weather = {"temperature_c": 22.0, "rainy": False, "wind_speed_kmh": 10.0, "condition": "clear"}
    with patch("moodos.weather_mcp.fetch_current_weather", return_value=fake_weather):
        r = client.get("/api/weather/activity?lat=28.6139&lon=77.2090&activity=outdoor_walk")
        assert r.status_code == 200
        data = r.json()
        assert data["activity"] == "outdoor_walk"
        assert data["suitable"] is True
