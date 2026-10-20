import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moodos.mcp_server import mcp

tools = mcp.list_tools()
weak = [t["name"] for t in tools if t["description"] == t["name"].replace("_", " ")]
print("tool count:", len(tools))
print("weak descriptions:", weak)
print()
for t in tools:
    req = t["inputSchema"].get("required", [])
    print(f"{t['name']:28s} required={req}  {t['description'][:60]}")
print()
print("resources:", json.dumps(mcp.list_resources(), indent=2))
print("prompts:", json.dumps(mcp.list_prompts(), indent=2))
