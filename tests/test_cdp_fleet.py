"""Prove (a) external CDP endpoint (logged-in-Chrome mode) and (b) fleet parallelism."""
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
LANE = HERE.parent / "nitrolane.py"
FLEET = HERE.parent / "nitrolane_fleet.py"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def lane(req: dict) -> dict:
    proc = subprocess.run([sys.executable, str(LANE)], input=json.dumps(req), capture_output=True,
                          text=True, encoding="utf-8", timeout=300)
    return json.loads(proc.stdout)


def wiki(name: str) -> dict:
    return {"target": "browser", "url": "https://en.wikipedia.org",
            "subtask": {"goal": f"Open the Wikipedia article about {name}", "inputs": {"query": name},
                        "verification": [f"The article titled {name} is open"]},
            "check": f"document.title.startsWith({name!r})"}


# (a) external CDP: a Chrome we did not start through nitrolane's warm instance
profile = tempfile.mkdtemp(prefix="nitrolane-cdp-test-")
chrome = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9223", f"--user-data-dir={profile}",
                           "--no-first-run", "about:blank"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(100):
        try:
            urllib.request.urlopen("http://127.0.0.1:9223/json/version", timeout=2)
            break
        except Exception:
            time.sleep(0.2)
    req = wiki("Grace Hopper")
    req["cdp"] = "http://127.0.0.1:9223"
    r = lane(req)
    print("CDP:", r["status"], r.get("check"), r["sec"])
    assert r["status"] == "SUBTASK_COMPLETE" and r["check"] is True, r
finally:
    chrome.terminate()

# (b) fleet: 4 browser tasks; wall time must beat the sum of individual run times
spec = {"parallel": 4, "tasks": [wiki("Alan Turing"), wiki("Ada Lovelace"),
                                 {"target": "browser", "url": "https://news.ycombinator.com",
                                  "subtask": {"goal": "Open the list of newest submissions",
                                              "verification": ["The newest submissions page is shown"]},
                                  "check": "location.pathname==='/newest'"},
                                 wiki("Marie Curie")]}
proc = subprocess.run([sys.executable, str(FLEET)], input=json.dumps(spec), capture_output=True,
                      text=True, encoding="utf-8", timeout=600)
fleet = json.loads(proc.stdout)
assert fleet["complete"] == 4, fleet
serial = sum(r["wall_s"] for r in fleet["results"])
print(f"FLEET: 4/4 complete, wall {fleet['sec']}s vs serial sum {serial:.1f}s")
assert fleet["sec"] < serial, "no parallel speedup"
print("CDP+FLEET-OK")
