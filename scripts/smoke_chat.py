import json
import urllib.request

body = {"message": "what is my curr location", "lat": 23.0225, "lon": 72.5714}
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/plan",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json"},
)
data = json.loads(urllib.request.urlopen(req, timeout=40).read())
print("mode", data.get("mode"))
print("topic", data.get("topic"))
print("has_steps", bool((data.get("plan") or {}).get("steps")))
print("reply", (data.get("reply") or "")[:220].encode("ascii", "replace").decode())
