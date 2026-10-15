"""nitrolane fleet: run many subtasks in one call. Browser tasks run in parallel tabs on the
warm Chrome; desktop tasks run sequentially (one foreground). One JSON object in, one out:

    {"tasks": [<nitrolane request>, ...], "parallel": 4}
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LANE = Path(__file__).parent / "nitrolane.py"


def _run(req: dict) -> dict:
    started = time.perf_counter()
    proc = subprocess.run([sys.executable, str(LANE)], input=json.dumps(req), capture_output=True,
                          text=True, encoding="utf-8", timeout=900)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {"type": "error", "status": "ERROR", "error": (proc.stdout + proc.stderr)[-500:]}
    result["wall_s"] = round(time.perf_counter() - started, 2)
    return result


def main() -> int:
    raw = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    try:
        spec = json.loads(raw)
        tasks = spec["tasks"]
        if not isinstance(tasks, list) or not tasks:
            raise ValueError('"tasks" must be a non-empty array')
    except (ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"type": "error", "error": f"invalid input: {exc}"}))
        return 2

    started = time.perf_counter()
    results: list[dict | None] = [None] * len(tasks)
    browser_idx = [i for i, t in enumerate(tasks) if t.get("target") == "browser"]
    desktop_idx = [i for i, t in enumerate(tasks) if t.get("target") != "browser"]
    if browser_idx:
        # First browser task sequentially: starts the warm Chrome once (avoids launch races).
        first = browser_idx.pop(0)
        results[first] = _run(tasks[first])
        if browser_idx:
            with ThreadPoolExecutor(max_workers=max(1, int(spec.get("parallel", 4)))) as pool:
                for i, result in zip(browser_idx, pool.map(lambda i: _run(tasks[i]), browser_idx)):
                    results[i] = result
    for i in desktop_idx:  # one foreground: strictly sequential
        results[i] = _run(tasks[i])

    ok = sum(1 for r in results if r and r.get("status") == "SUBTASK_COMPLETE")
    print(json.dumps({"type": "fleet_result", "tasks": len(tasks), "complete": ok,
                      "sec": round(time.perf_counter() - started, 2), "results": results},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
