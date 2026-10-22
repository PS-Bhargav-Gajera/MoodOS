"""Terminal Live Traffic Inspector for Open-Meteo Weather MCP.

Run this script to observe the exact JSON-RPC 2.0 communication
flowing between the Client and Server in your terminal.

Usage:
  python scripts/inspect_weather_mcp_traffic.py
  python scripts/inspect_weather_mcp_traffic.py --http http://127.0.0.1:8000/mcp/weather
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx

from moodos.weather_mcp import weather_mcp_client, weather_mcp_server

# ANSI Color Codes for terminal
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
RED = "\033[31m"


def print_banner():
    print(f"\n{BOLD}{CYAN}========================================================================{RESET}")
    print(f"{BOLD}{MAGENTA}      Open-Meteo Weather MCP: Client <-> Server Traffic Inspector      {RESET}")
    print(f"{BOLD}{CYAN}========================================================================{RESET}")


def inspect_rpc_exchange(method: str, params: dict | None = None, http_url: str | None = None, req_id: int = 1):
    req_payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params or {},
    }

    print(f"\n{BOLD}{YELLOW}┌─── CLIENT -> SERVER [JSON-RPC Request #{req_id}] ───────────────────────{RESET}")
    if http_url:
        print(f"{YELLOW}│ Target URL:{RESET} {http_url}")
    print(f"{YELLOW}│ Method:{RESET}     {BOLD}{CYAN}{method}{RESET}")
    print(f"{YELLOW}│ Payload:{RESET}")
    for line in json.dumps(req_payload, indent=2).splitlines():
        print(f"{YELLOW}│{RESET}   {line}")
    print(f"{BOLD}{YELLOW}└────────────────────────────────────────────────────────────────────────{RESET}")

    t0 = time.perf_counter()
    status_str = "200 OK (in-process)"

    if http_url:
        try:
            resp = httpx.post(http_url, json=req_payload, timeout=15.0)
            status_str = f"HTTP {resp.status_code}"
            res_payload = resp.json()
        except Exception as exc:
            status_str = f"HTTP Connection Failed: {exc}"
            res_payload = {"error": str(exc)}
    else:
        res_payload = weather_mcp_server.handle_jsonrpc(req_payload)

    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f"{BOLD}{GREEN}┌─── SERVER -> CLIENT [JSON-RPC Response #{req_id} | {status_str} | {elapsed_ms:.1f}ms] ───{RESET}")
    print(f"{GREEN}│ Response Body:{RESET}")
    for line in json.dumps(res_payload, indent=2, ensure_ascii=True).splitlines():
        print(f"{GREEN}│{RESET}   {line}")

    # If it was a tools/call, unwrap and display the pretty result summary
    if method == "tools/call" and "result" in res_payload:
        content = res_payload["result"].get("content", [])
        if content and content[0].get("type") == "text":
            try:
                parsed_data = json.loads(content[0]["text"])
                print(f"{GREEN}│{RESET}")
                print(f"{GREEN}│ {BOLD}Decoded Weather Summary:{RESET}")
                if "temperature_c" in parsed_data:
                    print(f"{GREEN}│{RESET}   * Temperature: {parsed_data.get('temperature_c')} C (feels like {parsed_data.get('feels_like_c')} C)")
                    print(f"{GREEN}│{RESET}   * Condition:   {parsed_data.get('condition_label')}")
                    print(f"{GREEN}│{RESET}   * Rainy:       {parsed_data.get('rainy')}")
                    print(f"{GREEN}│{RESET}   * Wind Speed:  {parsed_data.get('wind_speed_kmh')} km/h")
                elif "days" in parsed_data:
                    print(f"{GREEN}│{RESET}   * Forecast: {len(parsed_data['days'])} days returned")
                    for day in parsed_data['days'][:3]:
                        print(f"{GREEN}│{RESET}     - {day['date']}: {day.get('temp_min_c')} C to {day.get('temp_max_c')} C | {day.get('condition_label')}")
                elif "recommendation" in parsed_data:
                    print(f"{GREEN}│{RESET}   * Activity:       {parsed_data.get('activity')}")
                    print(f"{GREEN}│{RESET}   * Suitable:       {parsed_data.get('suitable')}")
                    print(f"{GREEN}│{RESET}   * Score:          {parsed_data.get('suitability_score')}/1.0")
                    print(f"{GREEN}│{RESET}   * Recommendation: {parsed_data.get('recommendation')}")
                elif "city" in parsed_data:
                    curr = parsed_data.get('current', {})
                    print(f"{GREEN}│{RESET}   * City:        {parsed_data.get('city')}, {parsed_data.get('country')}")
                    print(f"{GREEN}│{RESET}   * Coordinates: ({parsed_data.get('lat')}, {parsed_data.get('lon')})")
                    print(f"{GREEN}│{RESET}   * Weather:     {curr.get('temperature_c')} C, {curr.get('condition_label')}")
            except Exception:
                pass

    print(f"{BOLD}{GREEN}└────────────────────────────────────────────────────────────────────────{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Inspect Weather MCP Client <-> Server Traffic")
    parser.add_argument("--http", type=str, default=None, help="HTTP URL of Weather MCP (e.g. http://127.0.0.1:8000/mcp/weather). Omit for direct in-process.")
    parser.add_argument("--demo", action="store_true", help="Run full automated traffic demonstration")
    args = parser.parse_args()

    print_banner()

    target_url = args.http
    if not target_url:
        # Check if local server is listening on port 8000
        try:
            r = httpx.get("http://127.0.0.1:8000/mcp/weather/tools", timeout=0.8)
            if r.status_code == 200:
                target_url = "http://127.0.0.1:8000/mcp/weather"
                print(f"{BOLD}{GREEN}* Detected live MoodOS server on http://127.0.0.1:8000/mcp/weather{RESET}")
        except Exception:
            print(f"{BOLD}{BLUE}i Running in Direct In-Process Dispatch mode (no external port needed).{RESET}")
    else:
        print(f"{BOLD}{CYAN}Connecting to remote MCP server at: {target_url}{RESET}")

    scenarios = [
        ("1. Handshake / Initialize", "initialize", {}),
        ("2. Discover Tools (tools/list)", "tools/list", {}),
        (
            "3. Tool Call: get_current_weather (New Delhi: 28.6139, 77.2090)",
            "tools/call",
            {"name": "get_current_weather", "arguments": {"lat": 28.6139, "lon": 77.2090}},
        ),
        (
            "4. Tool Call: evaluate_weather_for_activity (Outdoor Walk)",
            "tools/call",
            {"name": "evaluate_weather_for_activity", "arguments": {"lat": 28.6139, "lon": 77.2090, "activity": "outdoor_walk"}},
        ),
        (
            "5. Tool Call: get_weather_by_city (Ahmedabad)",
            "tools/call",
            {"name": "get_weather_by_city", "arguments": {"city": "Ahmedabad"}},
        ),
        (
            "6. Tool Call: get_weather_forecast (7 days)",
            "tools/call",
            {"name": "get_weather_forecast", "arguments": {"lat": 28.6139, "lon": 77.2090, "days": 7}},
        ),
    ]

    for idx, (title, method, params) in enumerate(scenarios, 1):
        print(f"\n{BOLD}{CYAN}>>> Scenario {title}{RESET}")
        inspect_rpc_exchange(method=method, params=params, http_url=target_url, req_id=idx)
        time.sleep(0.3)

    print(f"\n{BOLD}{GREEN}* All MCP communication scenarios completed successfully!{RESET}\n")


if __name__ == "__main__":
    main()
