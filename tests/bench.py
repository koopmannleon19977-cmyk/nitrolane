"""Public micro-benchmark for nitrolane: a small fixed task set, median seconds per verified run.

Usage: <venv python> bench.py [repeats]   (default 2; desktop tasks take the foreground)
Writes bench_result.json next to this file. Success counts only when the independent check passes.
"""
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
LANE = HERE.parent / "nitrolane.py"
REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 2

FORM = {"goal": "Fill the pizza order form and submit it",
        "inputs": {"name": "Max Muster", "phone": "0123456", "email": "max@example.com"},
        "verification": ["The order was submitted and the response page is shown"],
        "constraints": ["Choose size Medium", "Select topping Bacon only"], "max_actions": 15}
FORM_B = json.loads(json.dumps(FORM))
FORM_B["inputs"] = {"name": "Erika Beispiel", "phone": "999000", "email": "erika@example.org"}
TASKS = {
    "browser_form_jev": {"target": "browser", "url": "https://httpbin.org/forms/post", "subtask": FORM,
                         "check": "document.body.innerText.includes('\"size\": \"medium\"')"},
    "browser_form_cached": {"target": "browser", "url": "https://httpbin.org/forms/post", "subtask": FORM,
                            "check": "document.body.innerText.includes('\"custname\": \"Max Muster\"') && "
                                     "document.body.innerText.includes('\"size\": \"medium\"')", "cache": True},
    "browser_form_param_b": {"target": "browser", "url": "https://httpbin.org/forms/post", "subtask": FORM_B,
                             "check": "document.body.innerText.includes('\"custname\": \"Erika Beispiel\"') && "
                                      "document.body.innerText.includes('\"size\": \"medium\"')", "cache": True},
    "browser_wiki_search": {"target": "browser", "url": "https://en.wikipedia.org",
                            "subtask": {"goal": "Open the Wikipedia article about Alan Turing",
                                        "inputs": {"query": "Alan Turing"},
                                        "verification": ["The article titled Alan Turing is open"]},
                            "check": "document.title.startsWith('Alan Turing')"},
    "desktop_notepad_text": {"target": "desktop", "app": {"launch": "notepad.exe", "title": "– Notepad"},
                             "subtask": {"goal": "Replace the document text with the supplied text",
                                         "inputs": {"text": "nitrolane bench"},
                                         "verification": ["The document text is exactly the supplied text"], "max_actions": 4},
                             "check": "nitrolane bench"},
    "desktop_calc_7clicks": {"target": "desktop", "app": {"launch": "calc.exe", "title": "Rechner"},
                             "subtask": {"goal": "Using the calculator buttons in exactly this order: Clear, 1, 2, Multiply, 1, 2, Equals",
                                         "verification": ["The calculator display shows 144"], "max_actions": 10},
                             "check": "Anzeige lautet 144"},
    "desktop_calc_cached": {"target": "desktop", "app": {"launch": "calc.exe", "title": "Rechner"},
                            "subtask": {"goal": "Using the calculator buttons in exactly this order: Clear, 1, 2, Multiply, 1, 2, Equals",
                                        "verification": ["The calculator display shows 144"], "max_actions": 10},
                            "check": "Anzeige lautet 144", "cache": True},
}


def run(req: dict) -> dict:
    proc = subprocess.run([sys.executable, str(LANE)], input=json.dumps(req), capture_output=True,
                          text=True, encoding="utf-8", timeout=180)
    return json.loads(proc.stdout)


results = {}
for tid, req in TASKS.items():
    runs = []
    if req.get("cache"):
        run(req)  # warmup: first run stores the template; measured runs are replays
    for _ in range(REPEATS):
        started = time.perf_counter()
        r = run(req)
        runs.append({"status": r.get("status"), "check": r.get("check"), "actions": r.get("actions"),
                     "run_s": (r.get("sec") or {}).get("run"), "wall_s": round(time.perf_counter() - started, 2),
                     "cache": r.get("cache")})
    ok = [r for r in runs if r["status"] == "SUBTASK_COMPLETE" and r["check"] is True]
    results[tid] = {"success": f"{len(ok)}/{len(runs)}",
                    "median_run_s": round(statistics.median([r["run_s"] for r in ok]), 2) if ok else None,
                    "runs": runs}
    print(f"{tid:26} {results[tid]['success']}  median {results[tid]['median_run_s']}s")
(HERE / "bench_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

# Fleet: four independent browser tasks in parallel tabs (one warm-up task runs first inside fleet).
def _wiki(name: str) -> dict:
    return {"target": "browser", "url": "https://en.wikipedia.org",
            "subtask": {"goal": f"Open the Wikipedia article about {name}", "inputs": {"query": name},
                        "verification": [f"The article titled {name} is open"]},
            "check": f"document.title.startsWith({name!r})"}


fleet_proc = subprocess.run([sys.executable, str(HERE.parent / "nitrolane_fleet.py")],
                            input=json.dumps({"parallel": 4, "tasks": [_wiki("Alan Turing"), _wiki("Ada Lovelace"),
                                                                        _wiki("Marie Curie"), _wiki("Grace Hopper")]}),
                            capture_output=True, text=True, encoding="utf-8", timeout=600)
fleet = json.loads(fleet_proc.stdout)
results["fleet_4_browser_tasks"] = {"success": f"{fleet['complete']}/4", "wall_s": fleet["sec"],
                                    "serial_sum_s": round(sum(r["wall_s"] for r in fleet["results"]), 2)}
print(f"{'fleet_4_browser_tasks':26} {results['fleet_4_browser_tasks']['success']}  wall {fleet['sec']}s")
(HERE / "bench_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

import datetime

lines = ["# nitrolane micro-benchmark", "",
         f"Measured {datetime.date.today().isoformat()} on this machine (Windows 11) with `tests/bench.py`.",
         "Success counts only when the independent `check` passes. `run` excludes process start and page setup.", "",
         "| Task | Success | Median run (s) |", "|---|---:|---:|"]
for tid, r in results.items():
    if tid == "fleet_4_browser_tasks":
        lines.append(f"| {tid} | {r['success']} | wall {r['wall_s']} (serial sum {r['serial_sum_s']}) |")
    else:
        lines.append(f"| {tid} | {r['success']} | {r['median_run_s']} |")
(HERE / "bench_result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
