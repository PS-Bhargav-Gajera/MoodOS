"""T1 transport test — temporary probe for PROGRESS.md step T1.

Sends one tiny Overpass query to https://overpass-api.de/api/interpreter only
(no mirrors), one variant at a time with a 3s pause, printing variant name,
status code, elapsed seconds and the first 150 chars of the body.
"""

import os
import time

import httpx

QUERY = "[out:json][timeout:10];node(around:2000,28.6139,77.2090)[amenity=restaurant];out center 5;"
URL = "https://overpass-api.de/api/interpreter"
TIMEOUT = 40.0

UA_OLD = "MoodOS/0.1 (student project; contact: local)"
UA_NEW = "MoodOS/0.1 (student project; https://github.com/PS-Bhargav-Gajera/moodos)"

print("=== proxy env ===")
for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    print(f"{name}={os.environ.get(name, '')!r}")


def run(name, method, **kwargs):
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            if method == "POST":
                r = client.post(URL, **kwargs)
            else:
                r = client.get(URL, **kwargs)
        elapsed = time.monotonic() - t0
        body = r.text[:150]
        print(f"--- {name} ---")
        print(f"status={r.status_code} elapsed={elapsed:.2f}s")
        print(f"body[:150]={body!r}")
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f"--- {name} ---")
        print(f"EXC elapsed={elapsed:.2f}s type={type(exc).__name__} msg={exc}")
    print()


def main():
    variants = [
        # 1 POST raw body, current project UA
        ("1 POST data=query, project UA", "POST",
         {"data": QUERY, "headers": {"User-Agent": UA_OLD}}),
        # 2 POST form, current project UA
        ("2 POST data={data: query}, project UA", "POST",
         {"data": {"data": QUERY}, "headers": {"User-Agent": UA_OLD}}),
        # 3 POST form, new UA
        ("3 POST data={data: query}, new UA", "POST",
         {"data": {"data": QUERY}, "headers": {"User-Agent": UA_NEW}}),
        # 4 POST form, new UA + Accept
        ("4 POST data={data: query}, new UA + Accept */*", "POST",
         {"data": {"data": QUERY},
          "headers": {"User-Agent": UA_NEW, "Accept": "*/*"}}),
        # 5 GET params, same headers
        ("5 GET params={data: query}, new UA + Accept */*", "GET",
         {"params": {"data": QUERY},
          "headers": {"User-Agent": UA_NEW, "Accept": "*/*"}}),
    ]
    for i, (name, method, kw) in enumerate(variants):
        run(name, method, **kw)
        if i < len(variants) - 1:
            time.sleep(3)

    # 6 as #4 but forcing IPv4
    print("--- 6 POST new UA + Accept, IPv4 local_address=0.0.0.0 ---")
    t0 = time.monotonic()
    try:
        with httpx.Client(
            timeout=TIMEOUT,
            transport=httpx.HTTPTransport(local_address="0.0.0.0"),
        ) as client:
            r = client.post(URL, data={"data": QUERY},
                            headers={"User-Agent": UA_NEW, "Accept": "*/*"})
        elapsed = time.monotonic() - t0
        print(f"status={r.status_code} elapsed={elapsed:.2f}s")
        print(f"body[:150]={r.text[:150]!r}")
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f"EXC elapsed={elapsed:.2f}s type={type(exc).__name__} msg={exc}")
    print()
    time.sleep(3)

    # 7 as #4 but trust_env=False
    print("--- 7 POST new UA + Accept, trust_env=False ---")
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=TIMEOUT, trust_env=False) as client:
            r = client.post(URL, data={"data": QUERY},
                            headers={"User-Agent": UA_NEW, "Accept": "*/*"})
        elapsed = time.monotonic() - t0
        print(f"status={r.status_code} elapsed={elapsed:.2f}s")
        print(f"body[:150]={r.text[:150]!r}")
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f"EXC elapsed={elapsed:.2f}s type={type(exc).__name__} msg={exc}")


if __name__ == "__main__":
    main()
