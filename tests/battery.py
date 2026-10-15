"""Regression battery for nitrolane: runs every task in battery.json, independent check per run.

Usage (needs the fixture server: python -m http.server 8765 --bind 127.0.0.1 in tests/pages):
    <venv python> battery.py [task-id-prefix ...]
Writes tests/last_run.json ({id: {expected, req, result}}) for jevify judging with the rubric in battery.json.
Desktop tasks take over mouse/keyboard focus while they run.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
LANE = HERE.parent / "nitrolane.py"
spec = json.loads((HERE / "battery.json").read_text(encoding="utf-8").replace("{TESTS}", str(HERE).replace("\\", "\\\\")))
# The battery's own fixture commands are the only extra launches it needs (nitrolane refuses others).
os.environ["NITROLANE_LAUNCH_ALLOW"] = ";".join({t["req"]["app"]["launch"] for t in spec["tasks"].values()
                                                 if "launch" in t["req"].get("app", {})})
prefixes = sys.argv[1:]
results = {}
for tid, task in spec["tasks"].items():
    if prefixes and not tid.startswith(tuple(prefixes)):
        continue
    if task.get("reset"):
        subprocess.run([sys.executable, str(HERE / "reset.py"), task["reset"]], capture_output=True)
    started = time.perf_counter()
    proc = subprocess.run([sys.executable, str(LANE)], input=json.dumps(task["req"]), capture_output=True,
                          text=True, encoding="utf-8", timeout=180)
    result = json.loads(proc.stdout) if proc.stdout.strip() else {"type": "error", "error": proc.stderr[-500:]}
    result["wall"] = round(time.perf_counter() - started, 2)
    if task.get("invert_check") and "check" in result:
        result["check"] = not result["check"]  # check names a forbidden effect; true now means it did not happen
    if task.get("close_fixture"):
        subprocess.run(["powershell", "-NoProfile", "-c", "Get-Process powershell -ErrorAction SilentlyContinue"
                        " | ? MainWindowTitle -eq 'nitrolane fixture' | Stop-Process"], capture_output=True)
    results[tid] = {"expected": task["expected"], "req": task["req"], "result": result}
    # A handback never submits, so its success check is expected to be false.
    ok = (result.get("status") == "SUBTASK_COMPLETE") == (task["expected"] == "complete") and (
        result.get("check") is not False or task["expected"] != "complete")
    print(f"{'ok ' if ok else 'BAD'} {tid:28} {result.get('status')} check={result.get('check')} "
          f"acts={result.get('actions')} run={(result.get('sec') or {}).get('run')}s {(result.get('reason') or '')[:80]}")
(HERE / "last_run.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
