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

__version__ = "0.6.0"

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from arc_cua import DesktopExecutor
from arc_cua.api import result_to_dict, subtask_from_dict
from arc_cua.policies import TypeSafeJevPolicy
from arc_cua.errors import StaleDesktopState
from arc_cua.runtime import RuntimeConfig
from arc_cua.models import ActionKind, DesktopElement, DesktopSnapshot, ExecutableAction

# Port 0 = Chrome picks a free port per start; set NITROLANE_CDP_PORT only if you need a fixed one.
CDP_PORT = int(os.environ.get("NITROLANE_CDP_PORT") or os.environ.get("ARC_LANE_CDP_PORT") or 0)
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


def _own_cdp() -> str | None:
    """CDP URL of nitrolane's own Chrome, or None when it is not running.

    Chrome writes its port and browser-target path to <profile>/DevToolsActivePort. A listener is
    only trusted when /json/version reports that exact target: a stale or foreign process on the
    port (which would then drive every run) is never attached to.
    """
    import httpx

    try:
        port, path = (PROFILE / "DevToolsActivePort").read_text(encoding="utf-8").split()[:2]
        url = f"http://127.0.0.1:{int(port)}"
        ws = httpx.get(url + "/json/version", timeout=0.5).json().get("webSocketDebuggerUrl", "")
    except (OSError, ValueError, httpx.HTTPError):
        return None
    return url if ws.endswith(path) else None


def _ensure_chrome(headed: bool) -> str:
    """Keep one warm Chrome (own profile, never the user's) alive between runs; cold start costs ~7 s."""
    if url := _own_cdp():
        return url
    from arc_cua.backends.cdp import find_chrome

    PROFILE.mkdir(parents=True, exist_ok=True)
    (PROFILE / "DevToolsActivePort").unlink(missing_ok=True)
    args = [find_chrome(), f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={PROFILE}",
            "--no-first-run", "--no-default-browser-check", f"--window-size={WINDOW}",
            "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling", *(() if headed else ("--headless=new",)), "about:blank"]
    subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=DETACH)
    deadline = time.monotonic() + 20
    while not (url := _own_cdp()):
        if time.monotonic() > deadline:
            raise RuntimeError("nitrolane's Chrome did not open DevTools (or its port is taken)")
        time.sleep(0.1)
    return url


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


# Built-in apps launchable without configuration; anything else must be listed verbatim in the
# user's NITROLANE_LAUNCH_ALLOW (";"-separated command lines). Requests come from agents/MCP
# callers, so a request alone must never be able to run an arbitrary command.
SAFE_LAUNCH = {"notepad.exe", "calc.exe", "mspaint.exe", "notepad", "calc", "mspaint"}


def _launch_argv(cmd: str) -> list[str]:
    import shlex

    allowed = {c.strip() for c in (_user_env("NITROLANE_LAUNCH_ALLOW") or "").split(";") if c.strip()}
    if cmd.strip().lower() not in SAFE_LAUNCH and cmd.strip() not in allowed:
        raise ValueError(f"launch {cmd!r} not allowed; add the exact command line to NITROLANE_LAUNCH_ALLOW")
    return [a.strip('"') for a in shlex.split(cmd, posix=False)]


def _desktop_backend(app: dict):
    from arc_cua.backends import WindowsUIABackend

    if "pid" in app:
        return WindowsUIABackend(int(app["pid"]))
    if "title" not in app:  # validate before any side effect
        raise ValueError('desktop app needs "pid" or "title" (with optional "launch")')
    found = None
    if "launch" in app:
        try:  # already open: launching again re-activates single-instance apps (measured: Calculator stole focus)
            found = _find_window(app["title"], 0)
        except RuntimeError:
            # No shell, no inherited pipes (a caller reading our stdout would wait for the app to exit).
            # Not DETACHED: console hosts (powershell fixtures) exit at once without a console; a hidden
            # one keeps them alive and leaves GUI apps unaffected.
            subprocess.Popen(_launch_argv(app["launch"]), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    pid, hwnd = found or _find_window(app["title"], 15 if "launch" in app else 2)
    import ctypes

    user32 = ctypes.windll.user32
    if user32.IsIconic(ctypes.c_void_p(hwnd)):  # the backend refuses minimized windows
        user32.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE
        time.sleep(0.3)
    return WindowsUIABackend(pid, window_id=hwnd)


def _text_seen(backend, needle: str) -> bool:
    """Desktop check: `needle` appears in an element name/value as whole words.

    Plain substring matching passed "Anzeige lautet 15" on "Anzeige lautet 156" (and "Done" on
    "Undone"), so a wrong run could be verified and cached as a template.
    """
    import re

    pattern = re.compile(r"(?<!\w)" + re.escape(" ".join(needle.split())) + r"(?!\w)")
    snap = backend.observe()
    return any(pattern.search(" ".join(str(t).split())) for e in snap.elements for t in (e.name, e.value) if t)


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

    Probe-less backends (Windows UIA, ~55 ms per observe): return once the revision changed and
    one more observe agrees, or after 0.15 s without change (the old fixed pause, now the cap).
    """
    probe = getattr(backend, "settle_probe", None)
    if probe is None:
        quiet_until = time.perf_counter() + 0.15
        hard_stop = time.perf_counter() + timeout_s  # a ticking clock/animation never settles
        snap = backend.observe()
        while time.perf_counter() < hard_stop:
            if snap.revision != before_revision:
                again = backend.observe()
                if again.revision == snap.revision:
                    return again
                snap = again
            elif time.perf_counter() >= quiet_until:
                return snap
            else:
                time.sleep(0.02)
                snap = backend.observe()
        return snap
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


def _replay(backend, steps: list[dict], inputs: dict, heal=None) -> int:
    """Re-execute a verified trajectory without model calls; returns how many steps were healed.

    A step whose target name is gone (renamed/translated UI) is re-targeted by `heal` (one
    model decision on that step only); its new name is written into `steps`. Raises
    _ReplayFailed when a step can neither be found nor healed.
    """
    snap = backend.observe()
    healed = 0
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
                def offered(sn):
                    return [e for e in sn.elements if e.visible and e.enabled and e.name == name and kind in e.actions]
                # No fixed settle after each step: observe once, and only poll while the next target
                # is not there yet (a dialog opening, a page loading). Measured settle cost was
                # 0.06-0.15 s per step, now paid only by steps that actually wait.
                cands, deadline = offered(snap), time.perf_counter() + 1.5
                while not cands and time.perf_counter() < deadline:
                    time.sleep(0.03)
                    snap = backend.observe()
                    cands = offered(snap)
                if not cands and heal is not None and (fixed := heal(snap, kind, name)) is not None:
                    cands, s["target_name"], s["target_bounds"] = [fixed], fixed.name, None
                    healed += 1
                if not cands:
                    raise LookupError(f"replay target not offered: {s['action']} {name!r}")
                b = s.get("target_bounds")
                if len(cands) > 1 and b:
                    cands.sort(key=lambda e: (abs(e.bounds.x - b["x"]) + abs(e.bounds.y - b["y"])) if e.bounds else 1e18)
                target = cands[0]
            action = ExecutableAction(kind=kind, target_id=target.id if target else None,
                                      target_guard=target.semantic_guard() if target else None,
                                      value=value, key=s.get("key"), hotkey=s.get("hotkey"),
                                      click_modifier=s.get("click_modifier"),
                                      scroll_direction=s.get("scroll_direction"))
            try:
                backend.execute(snap, action)
            except StaleDesktopState:
                # The UI was still moving when observed (no settle anymore): act once on a fresh view.
                import dataclasses

                snap = backend.observe()
                fresh = next((e for e in snap.elements if target and e.name == target.name and kind in e.actions), None)
                if fresh is not None:
                    action = dataclasses.replace(action, target_id=fresh.id, target_guard=fresh.semantic_guard())
                backend.execute(snap, action)
            snap = backend.observe()
            if kind == ActionKind.TYPE_TEXT and s.get("key"):  # runtime submits the key after the value lands
                backend.execute(snap, ExecutableAction(kind=ActionKind.PRESS_KEY, key=s["key"]))
                snap = backend.observe()
        except Exception as exc:
            raise _ReplayFailed(i, exc) from exc
    return healed


def _healer(make_policy, inputs: dict):
    """One decision per broken step: which element now plays the recorded element's role."""
    def heal(snap, kind, name):
        sub = subtask_from_dict({"goal": f"{kind.value} the element that replaced {name!r} "
                                         f"(the app's UI was renamed or translated)",
                                 "inputs": inputs, "verification": [f"{kind.value} on that element was done"]})
        d = make_policy().decide(subtask=sub, snapshot=snap, history=())
        # Stricter than the 0.35 action gate: a wrong heal is written into the template.
        if d.kind != kind or not d.target_id or (d.confidence or 0) < 0.6:
            return None
        return snap.element(d.target_id)
    return heal


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
    """Decision provider: jev (default) | openai (Decisions API) | chat (any OpenAI-compatible endpoint).

    A request may pick the provider name and model only. Endpoint and key come from the user's
    environment: otherwise any MCP caller could send a stored key to a host of its choosing.
    """
    p = req.get("provider") or {}
    if {"base_url", "api_key", "api_key_env"} & set(p):
        raise ValueError("provider base_url/api_key come from NITROLANE_BASE_URL/NITROLANE_API_KEY only")
    name = (p.get("name") or os.environ.get("NITROLANE_PROVIDER") or "jev").lower()
    key = _user_env("NITROLANE_API_KEY") if name != "jev" else None
    model = p.get("model") or os.environ.get("NITROLANE_MODEL") or None
    base = _user_env("NITROLANE_BASE_URL")
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


class _CuaSession:
    """One long-lived `cua-driver mcp` child per nitrolane process, in its own session.

    Measured per background click on Calculator: fresh `cua-driver` CLI process 0.28-0.30 s;
    this channel 0.58-0.70 s with the session's animated agent cursor, 0.13-0.16 s with it off.
    """

    SESSION = "nitrolane"

    @staticmethod
    @__import__("functools").cache
    def exe() -> str | None:
        return shutil.which("cua-driver")  # PATH scan cost ~12 ms per action before caching

    _lock = __import__("threading").Lock()
    _proc = None
    _next_id = 0

    @classmethod
    def _start(cls, exe: str):
        import queue
        import threading

        proc = subprocess.Popen([exe, "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)
        lines: queue.Queue = queue.Queue()
        threading.Thread(target=lambda: [lines.put(line) for line in proc.stdout], daemon=True).start()
        proc.lines = lines
        cls._proc = proc
        cls._send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "nitrolane", "version": __version__}}, timeout_s=10)
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        # Session-scoped: the user's own cua-driver config and other sessions keep their cursor.
        cls._send("tools/call", {"name": "set_agent_cursor_enabled",
                                 "arguments": {"enabled": False, "session": cls.SESSION}}, timeout_s=10)

    @classmethod
    def _send(cls, method: str, params: dict, timeout_s: float) -> dict:
        import queue

        cls._next_id += 1
        mid = cls._next_id
        cls._proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params}) + "\n")
        cls._proc.stdin.flush()
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                msg = json.loads(cls._proc.lines.get(timeout=max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                raise TimeoutError(f"cua-driver {method} took over {timeout_s} s") from None
            if msg.get("id") == mid:
                return msg

    @classmethod
    def run_steps(cls, exe: str, args: dict) -> dict | None:
        """structuredContent of run_steps; None if the channel could not be used (nothing was sent)."""
        with cls._lock:
            try:
                if cls._proc is None or cls._proc.poll() is not None:
                    cls._start(exe)
            except (OSError, ValueError, TimeoutError):
                cls._proc = None
                return None
            try:
                msg = cls._send("tools/call", {"name": "run_steps", "arguments": {**args, "session": cls.SESSION}},
                                timeout_s=20)
            except TimeoutError:
                # The action may still land: retrying via the pattern path could act twice, so stop the run.
                cls._proc.kill()
                cls._proc = None
                raise RuntimeError("cua-driver did not answer within 20 s; action state unknown") from None
            except (OSError, ValueError):
                cls._proc = None
                return None
            return (msg.get("result") or {}).get("structuredContent") or {}


def _cua_background(backend, snapshot, action) -> bool:
    """Background tier: UIA Invoke/Toggle/ValuePattern performed by the cua-driver daemon.

    Measured on Win11: the same Invoke from nitrolane's own process lets Calculator/Notepad take
    the foreground (the process holds foreground rights from the user's terminal), while the
    cua-driver daemon has none, so the window stays behind (0 foreground samples). Keys are not
    routed here: PostMessage keys/text into WinUI Notepad landed only in some focus states.
    False = not handled (no cua-driver, unnamed/ambiguous target, keys, no UIA route); the
    executor then takes its pattern/foreground path as before.
    """
    if action.kind == ActionKind.PRESS_KEY:
        # A TAB that only moves focus after a typed value: the value was set through a UIA
        # pattern and later steps target elements by pattern too, so the focus move is not
        # needed, and sending it was the only thing that brought a background form to the
        # front (measured: 0 -> ~110-150 foreground samples per replay). ENTER etc. still run.
        skip = action.key == "TAB" and getattr(backend, "_nl_tab_after_value", False)
        backend._nl_tab_after_value = False
        return skip
    backend._nl_tab_after_value = action.kind == ActionKind.TYPE_TEXT and action.key == "TAB"
    exe = _CuaSession.exe()
    if not exe or action.kind not in (ActionKind.CLICK, ActionKind.SET_VALUE, ActionKind.TYPE_TEXT):
        return False
    try:
        el = snapshot.element(action.target_id)
    except KeyError:
        return False
    same = [e for e in snapshot.elements if e.role == el.role and e.name == el.name]
    if not el.name or len(same) != 1 or el.role == "ComboBox":  # combos: select_option in the pattern path
        return False
    target = {"role": el.role.lower(), "name": el.name}
    step = {"click": target} if action.kind == ActionKind.CLICK else {"set_value": {**target, "value": str(action.value)}}
    res = _CuaSession.run_steps(exe, {"pid": backend.pid, "window_id": backend.window_id, "steps": [step]})
    # Only semantic UIA routes count; a pixel/PostMessage fallback is unverifiable here.
    if not res or not res.get("ok") or "UIA" not in (res.get("steps") or [{}])[0].get("message", ""):
        return False
    if action.kind == ActionKind.CLICK:
        return True
    try:
        ref = backend._refs[action.target_id]
        ref = ref.live() if hasattr(ref, "live") else ref
        landed = str(ref.iface_value.CurrentValue).replace("\r\n", "\n").replace("\r", "\n")
    except Exception:
        return False
    return landed == str(action.value).replace("\r\n", "\n")


def _doctor(argv: list[str]) -> int:
    """Report whether this machine can run nitrolane; never prints secret values.

    `doctor --deep` also sends one real choice decision to the provider, so a broken
    key/endpoint/model shows up here instead of as the first run's ERROR.
    """
    checks: dict = {"python": sys.version.split()[0]}
    try:
        from arc_cua.backends.cdp import find_chrome

        checks["chrome"] = find_chrome()
    except Exception as exc:
        checks["chrome"] = f"missing ({exc})"
    checks["chrome_cdp_alive"] = _own_cdp() is not None
    checks["typesafe_key"] = bool(_user_env("TYPESAFE_API_KEY"))
    checks["provider"] = os.environ.get("NITROLANE_PROVIDER", "jev (default)")
    checks["cache_dir"] = str(CACHE_DIR)
    checks["cua_driver_background"] = bool(shutil.which("cua-driver"))
    if sys.platform == "win32":
        try:
            from pywinauto import Desktop

            checks["uia_windows"] = len(Desktop(backend="uia").windows())
        except Exception as exc:
            checks["uia_windows"] = f"unavailable ({type(exc).__name__})"
    ok = isinstance(checks["chrome"], str) and not checks["chrome"].startswith("missing") and checks["typesafe_key"]
    if "--deep" in argv:
        try:
            policy = _policy({})
            answer = policy.decide(subtask=subtask_from_dict({
                "goal": "Pick the first offered option", "verification": ["A choice was made"]}),
                snapshot=DesktopSnapshot(application="doctor", window="doctor", revision="r",
                                         elements=(DesktopElement(id="d1", role="Button", name="OK",
                                                                  actions=(ActionKind.CLICK,)),)),
                history=())
            checks["deep_decision"] = {"choice": answer.kind.value if answer.kind else answer.terminal.value,
                                       "confidence": answer.confidence}
        except Exception as exc:
            checks["deep_decision"] = f"failed ({type(exc).__name__}: {str(exc)[:120]})"
            ok = False
    checks["ok"] = bool(ok)
    print(json.dumps(checks, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def _ocr_lines(backend) -> tuple[dict, object]:
    """Screenshot the target window and OCR it (Windows.Media.Ocr via ocr_capture.ps1)."""
    import tempfile

    from pywinauto import Desktop

    backend.observe()  # resolves window_id
    rect = Desktop(backend="uia").window(handle=backend.window_id).rectangle()
    # Unique per call (concurrent MCP runs) and deleted afterwards: it shows private window content.
    fd, name = tempfile.mkstemp(prefix="nitrolane_ocr_", suffix=".png")
    os.close(fd)
    png = Path(name)
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                               str(Path(__file__).parent / "ocr_capture.ps1"),
                               "-X", str(rect.left), "-Y", str(rect.top), "-W", str(rect.width()),
                               "-H", str(rect.height()), "-Png", str(png)],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
    finally:
        png.unlink(missing_ok=True)
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
    if sys.argv[1:2] == ["doctor"]:
        return _doctor(sys.argv[2:])
    raw = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    try:
        req = json.loads(raw)
    except ValueError as exc:
        out, code = {"type": "error", "error": f"invalid input: {exc}"}, 2
    else:
        out, code = run(req)
    # Indented: short lines, so tool output is never cut mid-line.
    print(json.dumps(out, ensure_ascii=False, indent=1 if out.get("type") == "result" else None))
    return code


def run(req: dict) -> tuple[dict, int]:
    """One subtask in this process: (result object, exit code). Used by main, the MCP server and the fleet."""
    try:
        if not isinstance(req, dict):
            raise TypeError("request must be a JSON object")
        spec = req.get("subtask") or {"goal": f"OCR action on {req['ocr']['text']!r}",
                                      "verification": ["The OCR action completed"]}
        subtask = subtask_from_dict(spec)
        # "steps": ordered one-action sub-goals ("Click 7", "Click plus", ...), each run as its own
        # decision with a budget of one action. Choice models pick goal parts in any order ("7 plus 8"
        # -> 7, 8, plus in 3/3 runs; order hints in the goal did not fix it: 1/3, 0/3), and per-step
        # completion checks failed on no-visible-change steps, so the final `check` is the verdict.
        ordered = [subtask_from_dict({"goal": f"{s} (step {i} of {len(req['steps'])} towards: {spec['goal']})",
                                      "inputs": spec.get("inputs") or {},
                                      "verification": [f"Done: {s}"], "max_actions": 1})
                   for i, s in enumerate(req.get("steps") or [], 1)]
        if ordered and not req.get("check"):
            raise ValueError('"steps" needs a "check": the final state is the only verdict')
        target = req["target"]
        if target not in ("browser", "desktop"):
            raise ValueError('target must be "browser" or "desktop"')
    except (ValueError, KeyError, TypeError) as exc:
        return {"type": "error", "error": f"invalid input: {exc}"}, 2

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
                from urllib.parse import urlparse

                if urlparse(endpoint).hostname not in ("127.0.0.1", "localhost", "::1"):
                    raise ValueError("cdp endpoint must be on this machine (127.0.0.1/localhost)")
                backend = ChromeBackend.connect(endpoint, url=req.get("url", "about:blank"))
            else:
                cdp = _ensure_chrome(bool(req.get("headed")))
                backend = ChromeBackend.connect(cdp, url=req.get("url", "about:blank"))
        else:
            backend = _desktop_backend(req.get("app") or {})
            if req.get("background", True):
                backend.adapter.background = _cua_background
    except Exception as exc:  # setup failures are reported, never raised into the caller's shell
        return {"type": "error", "error": f"{type(exc).__name__}: {exc}"}, 1

    t1 = time.perf_counter()
    out: dict = {"type": "result", "target": target}

    try:
        check = req.get("check")
        handled = False
        if target == "desktop" and req.get("ocr"):
            out.update(_ocr_action(backend, req))
            handled = True
        # A desktop check that already holds before the run proves nothing about the run.
        if target == "desktop" and check and not handled and _text_seen(backend, check):
            out["check_before"] = True
        # Cache only verified work: no independent check, no recording and no replay.
        cache_path = (_cache_path(req) if req.get("cache") and check and not handled
                      and not out.get("check_before") else None)
        replayed, history_dicts, prefix, healed = False, [], [], 0
        if cache_path and cache_path.exists():
            steps = json.loads(cache_path.read_text(encoding="utf-8"))["steps"]
            inputs = req["subtask"].get("inputs") or {}
            try:
                healed = _replay(backend, steps, inputs, heal=_healer(lambda: _policy(req), inputs))
                replayed = True
                out.update(status="SUBTASK_COMPLETE", reason=None, needs_input=None, actions=len(steps),
                           steps=[f"{s['action']} {s.get('target_name')!r} (replay)" for s in steps],
                           cache="healed" if healed else "hit")
            except _ReplayFailed as failed:
                # Delta fallback: the model continues from the state the replay reached.
                # Only a browser that already navigated/submitted is reset to a clean page.
                out["cache"] = "delta"
                if target == "browser" and failed.done > 0:
                    backend.navigate(req.get("url", "about:blank"))
                else:
                    prefix = steps[:failed.done]  # still valid: the model only redoes the broken tail
        if not replayed and not handled:
            executor = DesktopExecutor(backend, _policy(req), config=config)
            transitions = req.get("transitions") or {}
            violated = None
            runs = []
            if ordered:
                for sub in ordered:  # exactly one executed action per step, else stop and hand back
                    runs.append(executor.run(sub))
                    if len(runs[-1].history) != 1:
                        break
            elif not transitions:
                runs.append(executor.run(subtask))
            else:
                # Verify expected state after specific actions, not just at the end:
                # a right-looking screen after the wrong action is a failure (transition, not state).
                for event in executor.run_iter(subtask):
                    if event.result is not None:
                        runs.append(event.result)
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
            ds = [result_to_dict(r) for r in runs]
            d = ds[-1]
            history_dicts = [h for x in ds for h in x["history"]]
            out.update(status=d["status"], reason=d.get("reason"), needs_input=d.get("needs_input"),
                       actions=sum(x.get("actions_taken") or 0 for x in ds),
                       steps=[_step(h, rec) for x, r in zip(ds, runs) for h, rec in zip(x["history"], r.history)])
            if violated is not None:
                out.update(status="NEEDS_AGENT", reason=f"Transition check failed after step {violated}: {transitions[str(violated)]!r}",
                           transitions={"failed_step": violated})
            if ordered:
                done = len(runs) == len(ordered) and all(len(r.history) == 1 for r in runs)
                out.update(status="SUBTASK_COMPLETE" if done else "NEEDS_AGENT", reason=None if done else
                           f"Step {len(runs)} {req['steps'][len(runs) - 1]!r} did not run exactly one action: {d.get('reason')}")
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
        if ordered and out.get("status") == "SUBTASK_COMPLETE" and out.get("check") is not True:
            out.update(status="NEEDS_AGENT", reason="All steps ran but the check failed")
        if cache_path and out.get("check") is True and not replayed and out.get("status") == "SUBTASK_COMPLETE":
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            # A delta run stores kept prefix + the model's tail, so the next run is a full replay again.
            fresh = prefix + _recorded_steps(history_dicts, req["subtask"].get("inputs") or {})
            cache_path.write_text(json.dumps({"steps": fresh}, ensure_ascii=False), encoding="utf-8")
            out["cache"] = "rebuilt" if out.get("cache") == "delta" else "stored"
        elif cache_path and replayed and healed and out.get("check") is True:
            cache_path.write_text(json.dumps({"steps": steps}, ensure_ascii=False), encoding="utf-8")  # healed names
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
    return out, 0


if __name__ == "__main__":
    sys.exit(main())
