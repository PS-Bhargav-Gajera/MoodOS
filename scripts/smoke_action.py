import json
import urllib.request

def post(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

prep = post("http://127.0.0.1:8000/api/booking/prepare", {})
print("prep", prep["status"], prep["requires_confirmation"])
conf = post("http://127.0.0.1:8000/api/booking/confirm", {"confirmed": True, "show_index": 0})
print("confirm", conf["status"], conf.get("provider"))
fb = post(
    "http://127.0.0.1:8000/api/feedback",
    {"signal": "like", "note": "User enjoys low-intensity solo experiences after college.", "repeats": 2},
)
print("feedback", fb)
