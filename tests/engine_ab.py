"""Engine A/B: same nitrolane browser tasks against warm Chrome (default) vs Moli (CDP endpoint)."""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
LANE = HERE.parent / "nitrolane.py"
MOLI = Path(r"C:\Users\koopm\scratch-tools\engines\moli\moli-v1.1.17-x86_64-pc-windows-msvc\moli.exe")
PORT = 9224

TASKS = {
    "wiki_search": {"target": "browser", "url": "https://en.wikipedia.org",
                    "subtask": {"goal": "Open the Wikipedia article about Alan Turing",
                                "inputs": {"query": "Alan Turing"},
                                "verification": ["The article titled Alan Turing is open"]},
                    "check": "document.title.startsWith('Alan Turing')"},
    "hn_newest": {"target": "browser", "url": "https://news.ycombinator.com",
                  "subtask": {"goal": "Open the list of newest submissions",
                              "verification": ["The newest submissions page is shown"]},
                  "check": "location.pathname==='/newest'"},
    "httpbin_form": {"target": "browser", "url": "https://httpbin.org/forms/post",
                     "subtask": {"goal": "Fill the pizza order form and submit it",
                                 "inputs": {"name": "Max Muster", "phone": "0123456", "email": "max@example.com"},
                                 "verification": ["The order was submitted and the response page is shown"],
                                 "constraints": ["Choose size Medium", "Select topping Bacon only"], "max_actions": 15},
                     "check": "document.body.innerText.includes('\"size\": \"medium\"')"},
}


def lane(req: dict) -> dict:
    started = time.perf_counter()
    proc = subprocess.run([sys.executable, str(LANE)], input=json.dumps(req), capture_output=True,
                          text=True, encoding="utf-8", timeout=300)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        out = {"status": "ERROR", "reason": (proc.stdout + proc.stderr)[-300:]}
    out["wall_s"] = round(time.perf_counter() - started, 2)
    return out


results = {"chrome": {}, "moli": {}}
for name, req in TASKS.items():
    r = lane(req)
    results["chrome"][name] = {"status": r.get("status"), "check": r.get("check"),
                               "run_s": (r.get("sec") or {}).get("run"), "wall_s": r["wall_s"]}
    print("chrome", name, results["chrome"][name])

moli = subprocess.Popen([str(MOLI), "serve", "--port", str(PORT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=2)
            break
        except Exception:
            time.sleep(0.2)
    for name, req in TASKS.items():
        r = lane({**req, "cdp": f"http://127.0.0.1:{PORT}"})
        results["moli"][name] = {"status": r.get("status"), "check": r.get("check"),
                                 "run_s": (r.get("sec") or {}).get("run"), "wall_s": r["wall_s"],
                                 "reason": (r.get("reason") or r.get("error") or "")[:160]}
        print("moli  ", name, results["moli"][name])
finally:
    moli.terminate()

(HERE / "engine_ab_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({e: sum(1 for t in v.values() if t["status"] == "SUBTASK_COMPLETE" and t["check"] is True)
                  for e, v in results.items()}))
