"""MoodOS Real-Time Live Terminal Monitor.

Run this script in any terminal window. As soon as a user clicks 'Send' in the
browser (or sends a request to MoodOS), this script displays the exact, live
communication between the Web Client, Orchestrator, and MCP Server in real time.

Usage:
    python scripts/live_terminal.py
    python scripts/live_terminal.py --url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time

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

import httpx

RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
RED = "\033[31m"


def print_banner(server_url: str):
    print(f"\n{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{CYAN}║             MoodOS Live Terminal Monitor — Real-Time MCP Traffic                 ║{RESET}")
    print(f"{BOLD}{CYAN}╠══════════════════════════════════════════════════════════════════════════════════╣{RESET}")
    print(f"{CYAN}║ Connected to:{RESET} {BOLD}{server_url:<64}{RESET}{CYAN}║{RESET}")
    print(f"{CYAN}║ Instructions:{RESET} Open http://127.0.0.1:8000 in your browser,                       {CYAN}║{RESET}")
    print(f"{CYAN}║              type your mood prompt, and click {BOLD}{YELLOW}SEND{RESET}{CYAN}.                       ║{RESET}")
    print(f"{CYAN}║              All live client-server communication will display below.           ║{RESET}")
    print(f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════════════════════════════════╝{RESET}\n")
    print(f"{BOLD}{GREEN}* Listening for live events from browser... (Press Ctrl+C to stop){RESET}\n")
    sys.stdout.flush()


def listen_stream(server_url: str):
    stream_url = f"{server_url.rstrip('/')}/api/live-terminal/stream"
    seen_events = set()

    while True:
        try:
            with httpx.Client(timeout=None) as client:
                with client.stream("GET", stream_url) as response:
                    if response.status_code != 200:
                        print(f"{YELLOW}[!] Waiting for server to become ready (status: {response.status_code})...{RESET}")
                        time.sleep(2)
                        continue

                    for line in response.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        payload_str = line[len("data: ") :].strip()
                        if not payload_str:
                            continue
                        try:
                            data = json.loads(payload_str)
                            # Create a simple deduplication key
                            evt_key = f"{data.get('time')}:{data.get('type')}:{data.get('tool', data.get('step', ''))}"
                            if evt_key in seen_events:
                                continue
                            seen_events.add(evt_key)
                            if len(seen_events) > 1000:
                                seen_events.clear()

                            ansi = data.get("ansi")
                            if ansi:
                                sys.stdout.write(ansi + "\n")
                                sys.stdout.flush()
                        except Exception as parse_err:
                            pass
        except httpx.ConnectError:
            print(f"{YELLOW}[!] Connection refused. Is MoodOS running on {server_url}? Retrying in 2s...{RESET}")
            time.sleep(2)
        except KeyboardInterrupt:
            print(f"\n{BOLD}{CYAN}Live monitor stopped.{RESET}")
            break
        except Exception as exc:
            print(f"{RED}[!] Stream disconnected ({exc}). Reconnecting in 2s...{RESET}")
            time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description="Live Terminal View for MoodOS MCP Communication")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL of MoodOS server")
    args = parser.parse_args()

    print_banner(args.url)
    listen_stream(args.url)


if __name__ == "__main__":
    main()
