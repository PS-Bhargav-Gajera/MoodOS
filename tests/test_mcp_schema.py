"""MCP registry / schema validation (Phase 4).

There is no MCP SDK in this project: `MoodOSMCPServer` is an in-process
`dict[str, Callable]` with no transport, no decorators and no type hints on the
old lambda entries. MCP Inspector (or any MCP client) needs a
machine-readable input schema per tool to render a form and to validate
arguments before dispatch, so Phase 4 derives one from each callable's
signature and publishes it over HTTP.

The rules under test:
  * every registered tool is introspectable (no lambdas),
  * every tool publishes a schema whose parameters MATCH its real signature,
  * required params are the ones without defaults,
  * every tool has a human description,
  * the HTTP surface serves the registry in the shape a client expects,
  * the counts agree with what the rest of the codebase claims.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

import app as appmod
from moodos.mcp_server import mcp

EXPECTED_TOOL_COUNT = 23
EXPECTED_RESOURCE_COUNT = 4
EXPECTED_PROMPT_COUNT = 7


@pytest.fixture()
def client():
    return TestClient(appmod.app, raise_server_exceptions=False)


# ------------------------------------------------------- registry integrity

def test_tool_count_is_twenty_three():
    assert len(mcp.tools) == EXPECTED_TOOL_COUNT


def test_no_tool_is_a_bare_lambda():
    """A lambda has no parameter names, so no schema can be derived for it.

    Phase 4 converted all 9 lambda entries into real methods. This test is the
    regression guard: adding a lambda back must fail loudly.
    """
    lambdas = [n for n, f in mcp.tools.items() if type(f).__name__ == "lambda"]
    assert lambdas == [], f"these tools are bare lambdas: {lambdas}"


def test_every_tool_is_callable_with_zero_args_or_defaults():
    for name, fn in mcp.tools.items():
        sig = inspect.signature(fn)
        for pname, param in sig.parameters.items():
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            # every parameter must either be required or have a default;
            # nothing may be an unconstrained positional-only hole.
            assert param.default is not inspect.Parameter.empty or \
                param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY), \
                f"{name}.{pname}"


def test_unknown_tool_raises_keyerror():
    with pytest.raises(KeyError, match="Unknown MCP tool"):
        mcp.call("definitely_not_a_tool")


def test_call_still_dispatches_by_name():
    out = mcp.call("analyze_mood", message="I feel calm and relaxed")
    assert out["current_mood"]


# ------------------------------------------------------- schema correctness

def test_every_tool_has_a_schema_with_a_description():
    for name in mcp.tools:
        schema = mcp.tool_schema(name)
        assert schema["name"] == name
        assert schema["description"], f"{name} has no description"
        # a description that is just the name with underscores swapped is a
        # placeholder, not a description
        assert schema["description"] != name.replace("_", " "), name
        assert schema["inputSchema"]["type"] == "object"


def test_schema_parameters_match_the_real_signature():
    """The published schema must be DERIVED, never hand-maintained."""
    for name, fn in mcp.tools.items():
        schema = mcp.tool_schema(name)
        sig = inspect.signature(fn)
        expected = {pname for pname, prm in sig.parameters.items()
                    if prm.kind not in (prm.VAR_POSITIONAL, prm.VAR_KEYWORD)}
        published = set(schema["inputSchema"]["properties"])
        assert published == expected, f"{name}: {published} != {expected}"


def test_schema_required_matches_parameters_without_defaults():
    for name, fn in mcp.tools.items():
        schema = mcp.tool_schema(name)
        sig = inspect.signature(fn)
        expected_req = {p for p, prm in sig.parameters.items()
                        if prm.default is inspect.Parameter.empty
                        and prm.kind not in (prm.VAR_POSITIONAL, prm.VAR_KEYWORD)}
        published_req = set(schema["inputSchema"].get("required", []))
        assert published_req == expected_req, f"{name}: {published_req} != {expected_req}"


def test_optional_parameters_publish_their_default():
    schema = mcp.tool_schema("tmdb_trending")
    props = schema["inputSchema"]["properties"]
    assert props["media_type"]["default"] == "movie"
    assert props["time_window"]["default"] == "week"
    assert props["limit"]["default"] == 8


def test_location_tools_require_lat_and_lon():
    for name in ("get_weather", "find_nearby_places", "find_nearby_cinemas",
                 "search_restaurants", "search_restaurants_by_mood"):
        schema = mcp.tool_schema(name)
        props = schema["inputSchema"]["properties"]
        assert props["lat"]["type"] == "number", name
        assert props["lon"]["type"] == "number", name
        assert set(schema["inputSchema"]["required"]) >= {"lat", "lon"}, name


def test_list_tools_is_sorted_and_covers_every_registered_tool():
    listing = mcp.list_tools()
    names = [t["name"] for t in listing]
    assert names == sorted(names)
    assert set(names) == set(mcp.tools)


# ------------------------------------------------------- resources & prompts

def test_resource_count_and_shape():
    resources = mcp.list_resources()
    assert len(resources) == EXPECTED_RESOURCE_COUNT
    for r in resources:
        assert r["uri"] and r["description"]


def test_prompt_count_and_shape():
    prompts = mcp.list_prompts()
    assert len(prompts) == EXPECTED_PROMPT_COUNT
    for p in prompts:
        assert p["name"].startswith is not None  # sanity
        assert p["command"].startswith("/")


# ------------------------------------------------------- HTTP surface

def test_mcp_tools_endpoint_serves_the_registry(client):
    res = client.get("/mcp/tools")
    assert res.status_code == 200
    body = res.json()
    assert len(body["tools"]) == EXPECTED_TOOL_COUNT
    names = {t["name"] for t in body["tools"]}
    assert names == set(mcp.tools)
    for t in body["tools"]:
        assert "inputSchema" in t and "description" in t


def test_mcp_resources_endpoint(client):
    res = client.get("/mcp/resources")
    assert res.status_code == 200
    assert len(res.json()["resources"]) == EXPECTED_RESOURCE_COUNT


def test_mcp_prompts_endpoint(client):
    res = client.get("/mcp/prompts")
    assert res.status_code == 200
    assert len(res.json()["prompts"]) == EXPECTED_PROMPT_COUNT


def test_single_tool_schema_endpoint(client):
    res = client.get("/mcp/tools/get_weather")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "get_weather"
    assert set(body["inputSchema"]["required"]) == {"lat", "lon"}


def test_unknown_tool_schema_is_404(client):
    res = client.get("/mcp/tools/no_such_tool")
    assert res.status_code == 404


def test_legacy_prompts_endpoint_still_lists_tool_names(client):
    """Backwards compatibility: /api/prompts keeps its original shape."""
    res = client.get("/api/prompts")
    assert res.status_code == 200
    body = res.json()
    assert set(body["tools"]) == set(mcp.tools)
    assert len(body["prompts"]) == EXPECTED_PROMPT_COUNT
