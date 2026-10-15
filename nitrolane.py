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


class _ReplayFailed(Exception):
    """Replay stopped after `done` executed steps; the caller decides whether resetting is safe."""

    def __init__(self, done: int, cause: Exception):
        super().__init__(f"replay failed after {done} steps: {cause}")
        self.done = done


def _subs(inputs: dict) -> list[tuple[str, str]]:
    """(literal value, input key) pairs, longest first so replacements never shadow each other."""
    return sorted(((str(v), k) for k, v in inputs.items() if str(v)), key=lambda t: -len(t[0]))


def _templatize(node, subs):
    if isinstance(node, str):
        for value, key in subs:
            node = node.replace(value, "{" + key + "}")
        return node
    if isinstance(node, dict):
        return {k: (sorted(inputs) if k == "inputs" and isinstance(v, dict) else _templatize(v, subs))
                for k, v in node.items() for inputs in [v]}
    if isinstance(node, list):
        return [_templatize(x, subs) for x in node]
    return node


def _cache_path(req: dict) -> Path:
    """Template identity: same task with different input values maps to the same entry."""
    subs = _subs(req["subtask"].get("inputs") or {})
    canonical = _templatize({"target": req["target"], "url": req.get("url"), "app": req.get("app"),
                             "subtask": req["subtask"], "check": req.get("check")}, subs)
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    return CACHE_DIR / f"t-{digest}.json"


def _recorded_steps(history_dicts: list[dict], inputs: dict) -> list[dict]:
    """Name-based trajectory: element ids die with the session, names+bounds are resolvable again.

    Values that came from `inputs` are stored as {"$input": key} so the template replays with new data.
    """
    subs = _subs(inputs)
    steps = []
    for h in history_dicts:
        s = {k: h.get(k) for k in ("action", "target_name", "target_bounds", "value", "key", "hotkey",
                                    "click_modifier", "scroll_direction")}
        for value, key in subs:
            if s["value"] == value or (isinstance(s["value"], (int, float)) and str(s["value"]) == value):
                s["value"] = {"$input": key}
            if s["target_name"] and value in s["target_name"]:
                s["target_name"] = s["target_name"].replace(value, "{" + key + "}")
        steps.append(s)
    return steps


def _settle(backend, before_revision: str, timeout_s: float = 1.2):
    """Wait for the UI to go quiet, mirroring the executor: cheap probe if the backend has one.

    Full-revision polling was slower than blind sleeps (browser revisions keep changing),
    so probe-less backends (Windows UIA, synchronous input) just take a short fixed pause.
    """
    probe = getattr(backend, "settle_probe", None)
    if probe is None:
        time.sleep(0.15)
        return backend.observe()
    deadline = time.perf_counter() + timeout_s
    started = time.perf_counter()
    last = object()
    while time.perf_counter() < deadline:
        current = probe()
        if current == last and time.perf_counter() - started >= 0.09:
            break
        last = current
        time.sleep(0.03)
    return backend.observe()


def _replay(backend, steps: list[dict], inputs: dict) -> None:
    """Re-execute a verified trajectory without any model call. Raises _ReplayFailed on any mismatch."""
    snap = backend.observe()
    for i, s in enumerate(steps):
        try:
            kind = ActionKind(s["action"])
            name = s.get("target_name")
            if name is not None:
                for key, value in inputs.items():
                    name = name.replace("{" + key + "}", str(value))
            value = s.get("value")
            if isinstance(value, dict) and "$input" in value:
                if value["$input"] not in inputs:
                    raise LookupError(f"replay needs input {value['$input']!r}")
                value = inputs[value["$input"]]
            target = None
            if name is not None:
                cands = [e for e in snap.elements if e.visible and e.enabled and e.name == name and kind in e.actions]
                if not cands:
                    raise LookupError(f"replay target not offered: {s['action']} {name!r}")
                b = s.get("target_bounds")
                if len(cands) > 1 and b:
                    cands.sort(key=lambda e: (abs(e.bounds.x - b["x"]) + abs(e.bounds.y - b["y"])) if e.bounds else 1e18)
                target = cands[0]
            before = snap.revision
            backend.execute(snap, ExecutableAction(kind=kind, target_id=target.id if target else None,
                                                   target_guard=target.semantic_guard() if target else None,
                                                   value=value, key=s.get("key"), hotkey=s.get("hotkey"),
                                                   click_modifier=s.get("click_modifier"),
                                                   scroll_direction=s.get("scroll_direction")))
            snap = _settle(backend, before)
            if kind == ActionKind.TYPE_TEXT and s.get("key"):  # runtime submits the key after the value lands
                before = snap.revision
                backend.execute(snap, ExecutableAction(kind=ActionKind.PRESS_KEY, key=s["key"]))
                snap = _settle(backend, before)
        except Exception as exc:
            raise _ReplayFailed(i, exc) from exc


class ChatChoiceTransport:
    """Finite-choice decisions from any OpenAI-compatible chat endpoint (OpenAI, OpenRouter, Ollama, LM Studio, …).

    The model only picks offered criteria keys; ChoicePolicy validates every answer.
    """

    name = "Chat (OpenAI-compatible)"
    full_distribution = False  # chat models report a choice + confidence, not a distribution

    def __init__(self, model: str, base_url: str = "https://api.openai.com/v1", api_key: str | None = None, timeout_s: float = 60):
        import httpx

        self.model, self.base_url = model, base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout_s, headers={"Authorization": f"Bearer {api_key}"} if api_key else {})

    def ask(self, state, questions, *, images=()):
        if images:
            raise ValueError("Chat transport takes no screenshots in nitrolane")
        body = {"model": self.model, "temperature": 0, "messages": [
            {"role": "system", "content": "You answer UI choice questions. For EVERY question choose exactly one key "
                                          "from its criteria. Reply with ONLY this JSON: "
                                          "{\"answers\": {\"<question>\": {\"choice\": \"<key>\", \"confidence\": 0.0-1.0}}}"},
            {"role": "user", "content": json.dumps({"state": state, "questions": questions}, ensure_ascii=False)}]}
        response = self.client.post(f"{self.base_url}/chat/completions", json=body)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        parsed = json.loads(content[content.index("{"):content.rindex("}") + 1])
        return {"answers": parsed["answers"], "model": self.model}


def _user_env(name: str) -> str | None:
    """Process env first, then the Windows user environment (hosts with a frozen env miss setx values)."""
    if os.environ.get(name):
        return os.environ[name]
    if sys.platform == "win32" and name:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None
    return None


def _policy(req: dict):
    """Decision provider: jev (default) | openai (Decisions API) | chat (any OpenAI-compatible endpoint)."""
    p = req.get("provider") or {}
    name = (p.get("name") or os.environ.get("NITROLANE_PROVIDER") or "jev").lower()
    key = p.get("api_key") or _user_env(p.get("api_key_env") or "")
    model = p.get("model") or os.environ.get("NITROLANE_MODEL") or None
    base = p.get("base_url") or os.environ.get("NITROLANE_BASE_URL") or None
    if name == "jev":
        return TypeSafeJevPolicy(api_key=key, model=model)
    from arc_cua.policies import ChoicePolicy

    if name == "openai":
        from arc_cua.policies._openai_decisions import OpenAIDecisionsTransport

        return ChoicePolicy(OpenAIDecisionsTransport(api_key=key, model=model, base_url=base))
    if name == "chat":
        if not model:
            raise ValueError('provider "chat" needs a model (provider.model or NITROLANE_MODEL)')
        return ChoicePolicy(ChatChoiceTransport(model, base_url=base or "https://api.openai.com/v1",
                                                 api_key=key or _user_env("OPENAI_API_KEY")))
    raise ValueError(f'unknown provider {name!r}; use "jev", "openai" or "chat"')




def _foreground_hwnd() -> int:
    import ctypes

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    return int(user32.GetForegroundWindow() or 0)


def _restore_foreground(hwnd: int) -> None:
    """Give the user's window its focus back after a foreground desktop run."""
    import ctypes

    if not hwnd:
        return
    user32 = ctypes.windll.user32
    if int(user32.GetForegroundWindow() or 0) == hwnd or not user32.IsWindow(ctypes.c_void_p(hwnd)):
        return
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 0x0002, 0)
    user32.SetForegroundWindow(ctypes.c_void_p(hwnd))


def _doctor() -> int:
    """Report whether this machine can run nitrolane; never prints secret values."""
    checks: dict = {"python": sys.version.split()[0]}
    try:
        from arc_cua.backends.cdp import find_chrome

        checks["chrome"] = find_chrome()
    except Exception as exc:
        checks["chrome"] = f"missing ({exc})"
    checks["chrome_cdp_alive"] = _cdp_alive()
    checks["typesafe_key"] = bool(_user_env("TYPESAFE_API_KEY"))
    checks["provider"] = os.environ.get("NITROLANE_PROVIDER", "jev (default)")
    checks["cache_dir"] = str(CACHE_DIR)
    if sys.platform == "win32":
        try:
            from pywinauto import Desktop

            checks["uia_windows"] = len(Desktop(backend="uia").windows())
        except Exception as exc:
            checks["uia_windows"] = f"unavailable ({type(exc).__name__})"
    ok = isinstance(checks["chrome"], str) and not checks["chrome"].startswith("missing") and checks["typesafe_key"]
    checks["ok"] = bool(ok)
    print(json.dumps(checks, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def _ocr_lines(backend) -> tuple[dict, object]:
    """Screenshot the target window and OCR it (Windows.Media.Ocr via ocr_capture.ps1)."""
    import tempfile

    from pywinauto import Desktop

    backend.observe()  # resolves window_id
    rect = Desktop(backend="uia").window(handle=backend.window_id).rectangle()
    png = Path(tempfile.gettempdir()) / "nitrolane_ocr.png"
    proc = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(Path(__file__).parent / "ocr_capture.ps1"),
                           "-X", str(rect.left), "-Y", str(rect.top), "-W", str(rect.width()),
                           "-H", str(rect.height()), "-Png", str(png)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    if proc.returncode:
        raise RuntimeError(f"OCR failed: {proc.stderr[-300:]}")
    return json.loads(proc.stdout), rect


def _ocr_find(data: dict, needle: str) -> tuple[float, float] | None:
    """Center (image coordinates) of the first OCR line containing `needle`, else None."""
    want = " ".join(needle.lower().split())
    for line in data.get("lines", []):
        if want in " ".join(line["text"].lower().split()) and line["words"]:
            x0 = min(w["x"] for w in line["words"])
            x1 = max(w["x"] + w["w"] for w in line["words"])
            y0 = min(w["y"] for w in line["words"])
            y1 = max(w["y"] + w["h"] for w in line["words"])
            return (x0 + x1) / 2, (y0 + y1) / 2
    return None


def _ocr_action(backend, req: dict) -> dict:
    """Last-resort path for pixels-only UIs: find text by OCR and click it. UIA stays first choice."""
    import ctypes

    ocr = req["ocr"]
    text = ocr["text"]
    data, rect = _ocr_lines(backend)
    hit = _ocr_find(data, text)
    if hit is None:
        return {"status": "NEEDS_AGENT", "reason": f"OCR did not find {text!r}", "steps": [],
                "ocr": {"lines": len(data.get("lines", []))}}
    steps = []
    if ocr.get("action", "click") == "click":
        x = int(rect.left + hit[0] * (rect.width() / data["width"]))
        y = int(rect.top + hit[1] * (rect.height() / data["height"]))
        backend.adapter.foreground(backend.pid, backend.window_id)
        user32 = ctypes.windll.user32
        pos = ctypes.wintypes.POINT() if hasattr(ctypes, "wintypes") else None
        user32.SetCursorPos(x, y)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        steps.append(f"OCR_CLICK {text!r} @{x},{y}")
        time.sleep(0.5)
    result: dict = {"status": "SUBTASK_COMPLETE", "reason": None, "needs_input": None,
                    "actions": len(steps), "steps": steps, "ocr": {"found": text, "lines": len(data.get("lines", []))}}
    if ocr.get("check_text"):
        data2, _ = _ocr_lines(backend)
        result["check"] = _ocr_find(data2, ocr["check_text"]) is not None
        if not result["check"]:
            result.update(status="NEEDS_AGENT", reason=f"OCR check text not found after action: {ocr['check_text']!r}")
    elif req.get("check"):
        result["check"] = _text_seen(backend, req["check"])
    return result
def main() -> int:
    if sys.argv[1:] == ["doctor"]:
        return _doctor()
    raw = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    try:
        req = json.loads(raw)
        subtask = subtask_from_dict(req.get("subtask") or {"goal": f"OCR action on {req['ocr']['text']!r}",
                                                            "verification": ["The OCR action completed"]})
        target = req["target"]
        if target not in ("browser", "desktop"):
            raise ValueError('target must be "browser" or "desktop"')
    except (ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"type": "error", "error": f"invalid input: {exc}"}))
        return 2

    # 0.35: multi-field tasks split confidence across equally valid first steps (correct form
    # SET_VALUE scored 0.33-0.43); the 0.43 wrong-target evidence came from the old 900px viewport.
    # Completions score lower on correct runs (0.38-0.43), hence their own, lower gate.
    config = RuntimeConfig(timeout_s=req.get("timeout_s", 90), min_confidence=req.get("min_confidence", 0.35),
                           min_completion_confidence=req.get("min_completion_confidence", 0.3),
                           min_margin=req.get("min_margin"))
    t0 = time.perf_counter()
    user_hwnd = _foreground_hwnd() if target == "desktop" and sys.platform == "win32" else 0
    try:
        if target == "browser":
            from arc_cua.backends import ChromeBackend

            # "cdp": attach to an already-running Chrome (--remote-debugging-port) instead of
            # nitrolane's own warm instance — e.g. a browser the user is logged into. Opt-in only:
            # that browser's tabs and session are the user's, so the subtask acts as them.
            endpoint = req.get("cdp")
            if endpoint:
                backend = ChromeBackend.connect(endpoint, url=req.get("url", "about:blank"))
            else:
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
        handled = False
        if target == "desktop" and req.get("ocr"):
            out.update(_ocr_action(backend, req))
            handled = True
        # Cache only verified work: no independent check, no recording and no replay.
        cache_path = _cache_path(req) if req.get("cache") and check and not handled else None
        replayed, history_dicts = False, []
        if cache_path and cache_path.exists():
            steps = json.loads(cache_path.read_text(encoding="utf-8"))["steps"]
            try:
                _replay(backend, steps, req["subtask"].get("inputs") or {})
                replayed = True
                out.update(status="SUBTASK_COMPLETE", reason=None, needs_input=None, actions=len(steps),
                           steps=[f"{s['action']} {s.get('target_name')!r} (replay)" for s in steps], cache="hit")
            except _ReplayFailed as failed:
                # Delta fallback: the model continues from the state the replay reached.
                # Only a browser that already navigated/submitted is reset to a clean page.
                out["cache"] = "delta"
                if target == "browser" and failed.done > 0:
                    backend.navigate(req.get("url", "about:blank"))
        if not replayed and not handled:
            executor = DesktopExecutor(backend, _policy(req), config=config)
            transitions = req.get("transitions") or {}
            violated = None
            if not transitions:
                result = executor.run(subtask)
            else:
                # Verify expected state after specific actions, not just at the end:
                # a right-looking screen after the wrong action is a failure (transition, not state).
                result = None
                for event in executor.run_iter(subtask):
                    if event.result is not None:
                        result = event.result
                        break
                    if event.record is not None and str(event.record.step) in transitions:
                        expr = transitions[str(event.record.step)]
                        if target == "browser":
                            ok = bool(backend._call("Runtime.evaluate", {"expression": expr, "returnByValue": True})["result"].get("value"))
                        else:
                            ok = any(expr in (e.name or "") or expr in str(e.value or "") for e in event.snapshot.elements)
                        if not ok:
                            violated = event.record.step
                            executor.cancel()
            d = result_to_dict(result)
            history_dicts = d["history"]
            out.update(status=d["status"], reason=d.get("reason"), needs_input=d.get("needs_input"),
                       actions=d.get("actions_taken"), steps=[_step(h, rec) for h, rec in zip(d["history"], result.history)])
            if violated is not None:
                out.update(status="NEEDS_AGENT", reason=f"Transition check failed after step {violated}: {transitions[str(violated)]!r}",
                           transitions={"failed_step": violated})
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
        elif check and not handled:
            out["check"] = _text_seen(backend, check)
        if cache_path and out.get("check") is True and not replayed and out.get("status") == "SUBTASK_COMPLETE":
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"steps": _recorded_steps(history_dicts, req["subtask"].get("inputs") or {})}, ensure_ascii=False), encoding="utf-8")
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
        if user_hwnd:
            _restore_foreground(user_hwnd)
    # Indented: short lines, so tool output is never cut mid-line.
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
