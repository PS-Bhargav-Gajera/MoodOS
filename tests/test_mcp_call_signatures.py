"""Every `mcp.call("<tool>", kwarg=...)` site must match the real tool.

`MoodOSMCPServer.call()` is a plain `self.tools[name](**kwargs)` dispatch, so a
keyword the tool does not declare raises TypeError at runtime. Inside
`run_pipeline` that TypeError is caught by the per-lookup `except` and logged
as a warning, which is why `search_music(q=...)` and `search_books(q=...)`
shipped with a green suite: the music and books legs silently returned `[]`
for every plan, and `search_web_knowledge(q=...)` (called outside any guard)
500'd the whole `/api/plan` request whenever RAG confidence was thin.

Stub-based tests cannot catch this class of bug — the stub is written from the
same wrong assumption as the call site. This test instead reads the source with
`ast` and checks every literal call against the registered tool's signature.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from moodos.mcp_server import mcp

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "app.py", *sorted((ROOT / "moodos").glob("*.py"))]


def _literal_mcp_calls(path: Path) -> list[tuple[int, str, list[str]]]:
    """(line, tool_name, keyword_names) for each `mcp.call("name", a=1)`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "call"):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "mcp"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue  # mcp.call(name, ...) with a computed name: not checkable
        if any(kw.arg is None for kw in node.keywords):
            continue  # **kwargs unpacking: not checkable statically
        found.append((
            node.lineno,
            str(node.args[0].value),
            [kw.arg for kw in node.keywords],
        ))
    return found


def _collect() -> list[tuple[str, int, str, list[str]]]:
    out: list[tuple[str, int, str, list[str]]] = []
    for path in SOURCES:
        for lineno, tool, kws in _literal_mcp_calls(path):
            out.append((path.name, lineno, tool, kws))
    return out


CALL_SITES = _collect()


def test_the_scan_actually_found_the_known_call_sites():
    """Guard the guard: an empty scan would make every assertion vacuous."""
    assert CALL_SITES, "no mcp.call sites were parsed"
    names = {tool for _, _, tool, _ in CALL_SITES}
    assert {"get_weather", "search_music", "search_books",
            "search_web_knowledge"} <= names


@pytest.mark.parametrize(
    "filename,lineno,tool,keywords",
    CALL_SITES,
    ids=[f"{f}:{n}:{t}" for f, n, t, _ in CALL_SITES],
)
def test_call_site_kwargs_match_the_tool_signature(
    filename: str, lineno: int, tool: str, keywords: list[str],
):
    assert tool in mcp.tools, f"{filename}:{lineno} calls unknown tool {tool!r}"
    sig = inspect.signature(mcp.tools[tool])
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return
    try:
        sig.bind(**{name: None for name in keywords})
    except TypeError as exc:  # pragma: no cover - message is the assertion
        raise AssertionError(
            f"{filename}:{lineno} mcp.call({tool!r}, ...) passes a keyword the "
            f"tool does not declare: {exc}. Real signature: {sig}"
        ) from None


def test_no_call_site_uses_the_retired_q_alias():
    """`q=` was the kwarg that broke plan generation; it must not come back."""
    offenders = [
        (f, n, t) for f, n, t, kws in CALL_SITES
        if t in {"search_music", "search_books", "search_web_knowledge", "suggest_movies",
                 "search_movies", "retrieve_knowledge"}
        and "q" in kws
    ]
    assert offenders == []
