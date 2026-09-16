---
tags: [moodos, route, api]
---

# Route Prompts

`GET /api/prompts` → `app.py:172`

## Response

```json
{
  "prompts": ["/mood-night", "/date-night", ...7 workflow names],
  "tools": ["analyze_mood", "extract_preferences", ...22 tools]
}
```

`prompts` come from `MoodOSMCPServer.prompts` (`mcp_server.py:49`); `tools`
from `mcp.tools` keys. The workflow select in the page is hardcoded to these
names (`index.html:41-49`), and the LLM plan prompt receives the chosen
workflow as a slot (`orchestrator.py:1201-1202`).

## Connects to

- [[Route Plan]] · all 02-Tools

## Used by

- External MCP clients / debugging