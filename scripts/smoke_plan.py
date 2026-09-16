import json
import urllib.request

body = {
    "message": "I'm exhausted after college, alone, have 1000 rupees, four hours, and want to go out but nothing intense."
}
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/plan",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json"},
)
raw = urllib.request.urlopen(req, timeout=90).read()
data = json.loads(raw)
print("steps", len(data.get("plan", {}).get("steps") or []))
print("extract", data.get("agents"))
print("path", data.get("retrieval_path"))
print("explanation", (data.get("plan") or {}).get("explanation", "")[:240])
for s in (data.get("plan") or {}).get("steps") or []:
    print("-", s.get("title"), s.get("cost_inr"))
