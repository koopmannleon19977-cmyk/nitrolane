"""nitrolane: run one bounded UI subtask with arc-cua + TypeSafe JEV, print one JSON object.

Input: one JSON object on stdin (or a file path as argv[1]):
  {"target": "browser", "url": "https://...", "subtask": {...},
   "check": "<JS expression, truthy = independently verified>", "extract": "<JS expression, its value returned>",
   "headed": false}
  {"target": "desktop", "app": {"pid": 123} | {"title": "Editor"} | {"launch": "notepad.exe", "title": "Editor"},
   "subtask": {...}, "check": "<text that must appear in a control name/value afterwards>"}
Subtask fields: goal, verification[], inputs{}, constraints[], max_actions, shortcuts{}, allowed_risks[], secret_inputs[].
Exit code 0 whenever a result line was printed (whatever its status); 2 invalid input; 1 setup error.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from arc_cua import DesktopExecutor
from arc_cua.api import result_to_dict, subtask_from_dict
from arc_cua.policies import TypeSafeJevPolicy
from arc_cua.runtime import RuntimeConfig
from arc_cua.models import ActionKind, ExecutableAction

CDP_PORT = int(os.environ.get("NITROLANE_CDP_PORT") or os.environ.get("ARC_LANE_CDP_PORT", "9333"))
CDP = f"http://127.0.0.1:{CDP_PORT}"
PROFILE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "nitrolane" / "chrome-profile"
CACHE_DIR = Path(os.environ.get("NITROLANE_CACHE") or os.environ.get("ARC_LANE_CACHE", Path(os.environ.get("LOCALAPPDATA", Path.home())) / "nitrolane" / "cache"))
# Observation is viewport-only; a tall viewport saves SCROLL decisions (inventory row 57: 3/3 right vs. 0/3).
WINDOW = os.environ.get("NITROLANE_WINDOW") or os.environ.get("ARC_LANE_WINDOW", "1280,2400")
DETACH = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0


if sys.platform == "win32" and not os.environ.get("TYPESAFE_API_KEY"):
    # Processes started before `setx` (or by hosts with a frozen env) miss the user variable.
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as _k:
            os.environ["TYPESAFE_API_KEY"] = winreg.QueryValueEx(_k, "TYPESAFE_API_KEY")[0]
    except OSError:
        pass


def _cdp_alive() -> bool:
    import httpx

    try:
        return httpx.get(CDP + "/json/version", timeout=0.5).status_code == 200
    except httpx.HTTPError:
        return False


def _ensure_chrome(headed: bool) -> None:
    """Keep one warm Chrome (own profile, never the user's) alive between runs; cold start costs ~7 s."""
    if _cdp_alive():
        return
    from arc_cua.backends.cdp import find_chrome

    PROFILE.mkdir(parents=True, exist_ok=True)
    args = [find_chrome(), f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={PROFILE}",
            "--no-first-run", "--no-default-browser-check", f"--window-size={WINDOW}",
            "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling", *(() if headed else ("--headless=new",)), "about:blank"]
    subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=DETACH)
    deadline = time.monotonic() + 20
    while not _cdp_alive():
        if time.monotonic() > deadline:
            raise RuntimeError(f"Chrome did not open DevTools on {CDP}")
        time.sleep(0.1)


def _find_window(title: str, timeout_s: float) -> tuple[int, int]:
    from pywinauto import Desktop

    deadline = time.monotonic() + timeout_s
    needle = title.casefold()
    while True:
        for w in Desktop(backend="uia").windows():
            if needle in (w.window_text() or "").casefold() and w.is_visible():
                return w.process_id(), int(w.handle)
        if time.monotonic() > deadline:
            raise RuntimeError(f"No visible window whose title contains {title!r}")
        time.sleep(0.2)


def _desktop_backend(app: dict):
    from arc_cua.backends import WindowsUIABackend

    if "pid" in app:
        return WindowsUIABackend(int(app["pid"]))
    if "launch" in app:
        # Detached, no inherited pipes: otherwise a caller reading our stdout waits for the app to exit.
        subprocess.Popen(app["launch"], shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=DETACH)
    if "title" not in app:
        raise ValueError('desktop app needs "pid" or "title" (with optional "launch")')
    pid, hwnd = _find_window(app["title"], 15 if "launch" in app else 2)
    import ctypes

    user32 = ctypes.windll.user32
    if user32.IsIconic(ctypes.c_void_p(hwnd)):  # the backend refuses minimized windows
        user32.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE
        time.sleep(0.3)
    return WindowsUIABackend(pid, window_id=hwnd)


def _text_seen(backend, needle: str) -> bool:
    snap = backend.observe()
    return any(needle in (e.name or "") or needle in str(e.value or "") for e in snap.elements)


def _step(h: dict, rec) -> str:
    """One readable line per action: kind, target, value/key, JEV confidence, whether the UI changed."""
    parts = [h["action"]]
    if h.get("target_name"):
        parts.append(repr(h["target_name"]))
    if h.get("value") is not None:
        parts.append(f"= {h['value']!r}")
    parts += [f"+{k}" for k in (h.get("key"), h.get("hotkey")) if k]
    if rec.decision.confidence is not None:
        parts.append(f"conf={rec.decision.confidence:.2f}")
    if not h.get("state_changed"):
        parts.append("(no change)")
    return " ".join(parts)


def _cache_path(req: dict) -> Path:
    canonical = {"target": req["target"], "url": req.get("url"), "app": req.get("app"),
                 "subtask": req["subtask"], "check": req.get("check")}
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    return CACHE_DIR / f"{digest}.json"


def _recorded_steps(history_dicts: list[dict]) -> list[dict]:
    """Name-based trajectory: element ids die with the session, names+bounds are resolvable again."""
    return [{k: h.get(k) for k in ("action", "target_name", "target_bounds", "value", "key", "hotkey",
                                    "click_modifier", "scroll_direction")}
            for h in history_dicts]


def _replay(backend, steps: list[dict]) -> None:
    """Re-execute a verified trajectory without any model call. Raises on any mismatch."""
    for s in steps:
        kind = ActionKind(s["action"])
        snap = backend.observe()
        target = None
        if s.get("target_name") is not None:
            cands = [e for e in snap.elements if e.visible and e.enabled and e.name == s["target_name"] and kind in e.actions]
            if not cands:
                raise LookupError(f"replay target not offered: {s['action']} {s['target_name']!r}")
            b = s.get("target_bounds")
            if len(cands) > 1 and b:
                cands.sort(key=lambda e: (abs(e.bounds.x - b["x"]) + abs(e.bounds.y - b["y"])) if e.bounds else 1e18)
            target = cands[0]
        backend.execute(snap, ExecutableAction(kind=kind, target_id=target.id if target else None,
                                               target_guard=target.semantic_guard() if target else None,
                                               value=s.get("value"), key=s.get("key"), hotkey=s.get("hotkey"),
                                               click_modifier=s.get("click_modifier"),
                                               scroll_direction=s.get("scroll_direction")))
        time.sleep(0.3)  # executor normally waits for the UI to settle between steps
        if kind == ActionKind.TYPE_TEXT and s.get("key"):  # runtime submits the key after the value lands
            backend.execute(backend.observe(), ExecutableAction(kind=ActionKind.PRESS_KEY, key=s["key"]))
            time.sleep(0.3)



def main() -> int:
    raw = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    try:
        req = json.loads(raw)
        subtask = subtask_from_dict(req["subtask"])
        target = req["target"]
        if target not in ("browser", "desktop"):
            raise ValueError('target must be "browser" or "desktop"')
    except (ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"type": "error", "error": f"invalid input: {exc}"}))
        return 2

    # 0.45: in our battery every correct action scored >= 0.5, every wrong-target action <= 0.43.
    # Completions score lower on correct runs (0.38-0.43), hence their own, lower gate.
    config = RuntimeConfig(timeout_s=req.get("timeout_s", 90), min_confidence=req.get("min_confidence", 0.45),
                           min_completion_confidence=req.get("min_completion_confidence", 0.3),
                           min_margin=req.get("min_margin"))
    t0 = time.perf_counter()
    try:
        if target == "browser":
            from arc_cua.backends import ChromeBackend

            _ensure_chrome(bool(req.get("headed")))
            backend = ChromeBackend.connect(CDP, url=req.get("url", "about:blank"))
        else:
            backend = _desktop_backend(req.get("app") or {})
    except Exception as exc:  # setup failures are reported, never raised into the caller's shell
        print(json.dumps({"type": "error", "error": f"{type(exc).__name__}: {exc}"}))
        return 1

    t1 = time.perf_counter()
    out: dict = {"type": "result", "target": target}
    try:
        check = req.get("check")
        # Cache only verified work: no independent check, no recording and no replay.
        cache_path = _cache_path(req) if req.get("cache") and check else None
        replayed, history_dicts = False, []
        if cache_path and cache_path.exists():
            steps = json.loads(cache_path.read_text(encoding="utf-8"))["steps"]
            try:
                _replay(backend, steps)
                replayed = True
                out.update(status="SUBTASK_COMPLETE", reason=None, needs_input=None, actions=len(steps),
                           steps=[f"{s['action']} {s.get('target_name')!r} (replay)" for s in steps], cache="hit")
            except Exception:
                out["cache"] = "invalidated"
                if target == "browser":
                    backend.navigate(req.get("url", "about:blank"))  # reset partial replay before the model retries
        if not replayed:
            result = DesktopExecutor(backend, TypeSafeJevPolicy(), config=config).run(subtask)
            d = result_to_dict(result)
            history_dicts = d["history"]
            out.update(status=d["status"], reason=d.get("reason"), needs_input=d.get("needs_input"),
                       actions=d.get("actions_taken"), steps=[_step(h, rec) for h, rec in zip(d["history"], result.history)])
            if cache_path and "cache" not in out:
                out["cache"] = "miss"
        t2 = time.perf_counter()
        if target == "browser":
            ev = lambda expr: backend._call("Runtime.evaluate", {"expression": expr, "returnByValue": True})["result"].get("value")
            out["page"] = {"url": ev("location.href"), "title": ev("document.title")}
            if check:
                out["check"] = bool(ev(check))
            if req.get("extract"):  # read the resulting page in the same call instead of a second run
                out["extract"] = ev(req["extract"])
        elif check:
            out["check"] = _text_seen(backend, check)
        if cache_path and out.get("check") is True and not replayed and out.get("status") == "SUBTASK_COMPLETE":
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"steps": _recorded_steps(history_dicts)}, ensure_ascii=False), encoding="utf-8")
            out["cache"] = "stored"
        elif cache_path and replayed and out.get("check") is not True:
            cache_path.unlink(missing_ok=True)  # stale entry; state already changed, so hand back instead of re-running blind
            out.update(status="NEEDS_AGENT", reason="Cached replay ran but the check failed; entry deleted.", cache="stale")
        out["sec"] = {"setup": round(t1 - t0, 2), "run": round(t2 - t1, 2)}
    except Exception as exc:
        out.update(status="ERROR", reason=f"{type(exc).__name__}: {exc}")
    finally:
        if target == "browser" and not req.get("keep_tab"):
            backend.close()
    # Indented: short lines, so tool output is never cut mid-line.
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
