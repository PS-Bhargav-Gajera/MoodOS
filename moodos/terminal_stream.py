"""Real-time Terminal Stream Bus for MoodOS.

Provides live ANSI terminal communication logging and real-time SSE streaming.
Whenever a user clicks 'Send' in the web interface or an MCP tool is called,
this bus prints the live communication directly to the terminal stdout and
broadcasts it to connected live terminal watchers.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
import json
import sys
import time
from typing import Any

# Configure Windows consoles to handle UTF-8 safely
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ANSI Color Codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
RED = "\033[31m"
WHITE = "\033[37m"
GRAY = "\033[90m"


class TerminalStreamBus:
    """Thread-safe event broadcaster and ANSI terminal logger."""

    def __init__(self, history_len: int = 200) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=history_len)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def get_history(self) -> list[dict[str, Any]]:
        return list(self._history)

    def _broadcast(self, item: dict[str, Any]) -> None:
        self._history.append(item)
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(item)
            except Exception:
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)

    def _write_stdout(self, text: str) -> None:
        try:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
        except Exception:
            pass

    def log_client_send(
        self,
        message: str,
        *,
        user_id: str = "demo",
        lat: float | None = None,
        lon: float | None = None,
        user_label: str | None = None,
        prompt: str | None = None,
        endpoint: str = "/api/plan",
    ) -> None:
        """Called when a user clicks 'Send' in the UI."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        loc_str = (
            f"lat={lat:.4f}, lon={lon:.4f}" if lat is not None and lon is not None else "Location: none/pending"
        )
        if user_label:
            loc_str += f" ('{user_label}')"

        ansi_lines = [
            f"\n{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════════════════════════╗{RESET}",
            f"{BOLD}{CYAN}║ [USER ACTION: CLICKED SEND] -> Web Client sent request to {endpoint}           ║{RESET}",
            f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════════════════════════════════╝{RESET}",
            f"{BOLD}{YELLOW}│ Time:{RESET}     {timestamp} | User: {BOLD}{user_id}{RESET}",
            f"{BOLD}{YELLOW}│ Message:{RESET}  {BOLD}{WHITE}\"{message}\"{RESET}",
            f"{BOLD}{YELLOW}│ Location:{RESET} {loc_str}",
        ]
        if prompt:
            ansi_lines.append(f"{BOLD}{YELLOW}│ Workflow:{RESET} {prompt}")
        ansi_lines.append(f"{BOLD}{YELLOW}│ Status:{RESET}   Dispatching to NLU & Orchestrator pipeline...\n")

        full_ansi = "\n".join(ansi_lines)
        self._write_stdout(full_ansi)

        event = {
            "type": "client_send",
            "time": timestamp,
            "user_id": user_id,
            "message": message,
            "location": loc_str,
            "prompt": prompt,
            "endpoint": endpoint,
            "ansi": full_ansi,
        }
        self._broadcast(event)

    def log_tool_call(self, tool_name: str, args_preview: str) -> None:
        """Called when an MCP tool invocation starts."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        ansi_line = (
            f"  {BOLD}{MAGENTA}--> [ORCHESTRATOR -> MCP SERVER]{RESET} "
            f"Calling Tool {BOLD}{CYAN}{tool_name}{RESET}({args_preview})"
        )
        self._write_stdout(ansi_line)

        event = {
            "type": "tool_call",
            "time": timestamp,
            "tool": tool_name,
            "args": args_preview,
            "ansi": ansi_line,
        }
        self._broadcast(event)

    def log_tool_result(
        self, tool_name: str, elapsed_ms: float, summary: str, is_error: bool = False
    ) -> None:
        """Called when an MCP tool finishes execution."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if is_error:
            ansi_line = (
                f"  {BOLD}{RED}<-- [MCP SERVER -> ORCHESTRATOR]{RESET} "
                f"Tool {BOLD}{CYAN}{tool_name}{RESET} {RED}FAILED{RESET} ({elapsed_ms:.1f}ms): {summary}"
            )
        else:
            ansi_line = (
                f"  {BOLD}{GREEN}<-- [MCP SERVER -> ORCHESTRATOR]{RESET} "
                f"Tool {BOLD}{CYAN}{tool_name}{RESET} finished ({GREEN}{elapsed_ms:.1f}ms{RESET}): {summary}"
            )
        self._write_stdout(ansi_line)

        event = {
            "type": "tool_result",
            "time": timestamp,
            "tool": tool_name,
            "elapsed_ms": elapsed_ms,
            "summary": summary,
            "is_error": is_error,
            "ansi": ansi_line,
        }
        self._broadcast(event)

    def log_step(self, step_name: str, detail: str) -> None:
        """Called during pipeline stage transitions (NLU, Parallel batch, LLM synthesis)."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        ansi_line = (
            f"  {BOLD}{BLUE}[*] [{step_name.upper()}]{RESET} {detail}"
        )
        self._write_stdout(ansi_line)

        event = {
            "type": "step",
            "time": timestamp,
            "step": step_name,
            "detail": detail,
            "ansi": ansi_line,
        }
        self._broadcast(event)

    def log_response_sent(
        self,
        status_code: int,
        elapsed_s: float,
        summary: str,
        *,
        mode: str = "plan",
    ) -> None:
        """Called when the server has compiled the response and responds to the client."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        ansi_lines = [
            f"\n{BOLD}{GREEN}┌── [SERVER -> CLIENT] Response Ready ({status_code} OK | {elapsed_s:.2f}s total) ───{RESET}",
            f"{GREEN}│ Mode:{RESET}     {mode}",
            f"{GREEN}│ Summary:{RESET}  {summary}",
            f"{BOLD}{GREEN}└══════════════════════════════════════════════════════════════════════════════════┘{RESET}\n",
        ]
        full_ansi = "\n".join(ansi_lines)
        self._write_stdout(full_ansi)

        event = {
            "type": "response_sent",
            "time": timestamp,
            "status_code": status_code,
            "elapsed_s": elapsed_s,
            "summary": summary,
            "mode": mode,
            "ansi": full_ansi,
        }
        self._broadcast(event)

    @staticmethod
    def format_args(kwargs: dict[str, Any]) -> str:
        parts = []
        for k, v in kwargs.items():
            if isinstance(v, (int, float, bool)):
                parts.append(f"{k}={v}")
            elif isinstance(v, str):
                short = v if len(v) <= 30 else v[:27] + "..."
                parts.append(f"{k}='{short}'")
            elif v is None:
                parts.append(f"{k}=None")
            elif isinstance(v, list):
                parts.append(f"{k}=[{len(v)} items]")
            elif isinstance(v, dict):
                parts.append(f"{k}={{...}}")
            else:
                parts.append(f"{k}={type(v).__name__}")
        return ", ".join(parts)

    @staticmethod
    def format_result(tool_name: str, res: Any) -> str:
        if res is None:
            return "None returned"
        if isinstance(res, list):
            n = len(res)
            if n == 0:
                return "0 items returned (empty list)"
            # Extract sample titles or names if present
            sample_titles = []
            for item in res[:3]:
                if isinstance(item, dict):
                    t = item.get("title") or item.get("name") or item.get("venue")
                    if t:
                        sample_titles.append(str(t)[:25])
            sample_str = f" [{', '.join(sample_titles)}...]" if sample_titles else ""
            return f"{n} items returned{sample_str}"
        if isinstance(res, dict):
            if "temperature_c" in res and "condition" in res:
                temp = res.get("temperature_c")
                cond = res.get("condition") or res.get("condition_label")
                rain = "rainy" if res.get("rainy") else "dry"
                return f"{temp}°C, {cond}, {rain} (Open-Meteo)"
            if "memories" in res:
                m_count = len(res["memories"]) if isinstance(res["memories"], list) else 0
                return f"{m_count} memories loaded from Mem0"
            if "tracks" in res:
                t_count = len(res["tracks"]) if isinstance(res["tracks"], list) else 0
                return f"{t_count} tracks curated"
            keys = list(res.keys())[:4]
            return f"dict with keys {keys}"
        if isinstance(res, str):
            return f"string ({len(res)} chars)"
        return str(res)[:60]


terminal_bus = TerminalStreamBus()
