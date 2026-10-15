"""nitrolane fleet: run many subtasks in one call. Browser tasks run in parallel tabs on the
warm Chrome; desktop tasks run sequentially (one foreground). One JSON object in, one out:

    {"tasks": [<nitrolane request>, ...], "parallel": 4, "task_timeout_s": 300}

Tasks run in this process (no interpreter start per task). A browser task that exceeds
task_timeout_s is reported as TIMEOUT; the others keep their results. Desktop tasks are bounded
by each request's own timeout_s.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import nitrolane as lane  # noqa: E402


def _run(req: dict) -> dict:
    started = time.perf_counter()
    try:
        result, _ = lane.run(req)
    except Exception as exc:  # one task must not lose the batch
        result = {"type": "error", "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
    result["wall_s"] = round(time.perf_counter() - started, 2)
    return result


def _collect(future, timeout_s: float) -> dict:
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeout:
        return {"type": "result", "status": "TIMEOUT", "reason": f"task exceeded {timeout_s:.0f} s"}


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

    timeout_s = float(spec.get("task_timeout_s", 300))
    started = time.perf_counter()
    results: list[dict | None] = [None] * len(tasks)
    browser_idx = [i for i, t in enumerate(tasks) if t.get("target") == "browser"]
    desktop_idx = [i for i, t in enumerate(tasks) if t.get("target") != "browser"]
    # Not a `with` block: shutdown(wait=True) would block on a timed-out task forever.
    pool = ThreadPoolExecutor(max_workers=max(1, int(spec.get("parallel", 4))))
    with contextlib.redirect_stdout(sys.stderr):  # stdout carries only the fleet result
        if browser_idx:
            # First browser task alone: starts the warm Chrome once (avoids launch races).
            first = browser_idx.pop(0)
            results[first] = _collect(pool.submit(_run, tasks[first]), timeout_s)
            futures = {i: pool.submit(_run, tasks[i]) for i in browser_idx}
            deadline = time.monotonic() + timeout_s
            for i, fut in futures.items():
                results[i] = _collect(fut, max(0.0, deadline - time.monotonic()))
        # One foreground, and UIA/COM objects belong to the thread that created them.
        for i in desktop_idx:
            results[i] = _run(tasks[i])
    pool.shutdown(wait=False, cancel_futures=True)

    ok = sum(1 for r in results if r and r.get("status") == "SUBTASK_COMPLETE")
    print(json.dumps({"type": "fleet_result", "tasks": len(tasks), "complete": ok,
                      "sec": round(time.perf_counter() - started, 2), "results": results},
                     ensure_ascii=False, indent=1), flush=True)
    if any(r.get("status") == "TIMEOUT" for r in results):
        os._exit(0)  # a hung task thread would otherwise keep the interpreter alive at exit
    return 0


if __name__ == "__main__":
    sys.exit(main())
