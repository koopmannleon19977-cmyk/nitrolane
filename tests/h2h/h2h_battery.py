"""Head-to-head on nitrolane's desktop battery tasks: same tasks, same independent checks.

Tasks (from tests/battery.json): D1 Notepad text, D4 Calculator 12 x 12, D7 WinForms form.
Tools: nitrolane (CLI per run: model run, then cached replays), desktop-touch-mcp, terminator-mcp-agent,
Windows-MCP. Competitors are driven WITHOUT a model, with known element ids/names/coordinates —
their best case. A stand-in user window holds the foreground; a 10 ms sampler counts samples where
the target app is in front. Correctness = the battery's whole-word check on the real UI afterwards.

Usage: python h2h_battery.py [tool ...]   (default: all)   -> battery_h2h_result.json
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
from mcpclient import Client  # noqa: E402
from pywinauto import Desktop  # noqa: E402

import nitrolane as lane  # noqa: E402

PY = sys.executable
FORM = str(HERE.parent / "form.ps1")
BATTERY = json.loads((HERE.parent / "battery.json").read_text(encoding="utf-8"))["tasks"]
ROUNDS = 3
TEXT = BATTERY["D1_notepad_line"]["req"]["subtask"]["inputs"]["text"]
TASKS = {
    "notepad": {"marker": "Notepad", "title": "– Notepad", "check": TEXT, "req": BATTERY["D1_notepad_line"]["req"]},
    "calc": {"marker": "Rechner", "title": "Rechner", "check": "Anzeige lautet 144",
             "req": {"target": "desktop", "app": {"title": "Rechner"},
                     "subtask": {"goal": "Using the calculator buttons in exactly this order: Clear, 1, 2, Multiply, 1, 2, Equals",
                                 "verification": ["The calculator display shows 144"], "max_actions": 10},
                     "check": "Anzeige lautet 144"}},
    "form": {"marker": "nitrolane fixture", "title": "nitrolane fixture", "check": "Hallo Jürgen aus Österreich",
             "req": {**BATTERY["D7_form_submit"]["req"], "app": {"title": "nitrolane fixture"}}},
}
CALC_IDS = ["clearButton", "num1Button", "num2Button", "multiplyButton", "num1Button", "num2Button", "equalButton"]
CALC_NAMES = ["Löschen", "Eins", "Zwei", "Multiplizieren mit", "Eins", "Zwei", "Gleich"]

user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = ctypes.c_void_p


def fg_title() -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(ctypes.c_void_p(int(user32.GetForegroundWindow() or 0)), buf, 256)
    return buf.value


def window(title_part: str):
    return next(w for w in Desktop(backend="uia").windows() if title_part in (w.window_text() or ""))


def ensure_apps() -> None:
    names = [w.window_text() for w in Desktop(backend="uia").windows()]
    if not any(n.endswith("– Notepad") for n in names):
        subprocess.Popen("notepad.exe")
        time.sleep(2.5)
    if "Rechner" not in names:
        subprocess.Popen("calc.exe", shell=True)
        time.sleep(3)


def close_form() -> None:
    subprocess.run(["powershell", "-NoProfile", "-c", "Get-Process powershell -ErrorAction SilentlyContinue"
                    " | ? MainWindowTitle -eq 'nitrolane fixture' | Stop-Process"], capture_output=True)


def prepare(task: str) -> None:
    if task == "form":
        close_form()
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", FORM],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        for _ in range(50):
            if any(w.window_text() == "nitrolane fixture" for w in Desktop(backend="uia").windows()):
                break
            time.sleep(0.1)
    else:
        ensure_apps()
        subprocess.run([PY, str(HERE.parent / "reset.py"), task], capture_output=True)
    window("h2h user window").set_focus()
    time.sleep(0.4)


def checked(task: str) -> bool:
    backend = lane._desktop_backend({"title": TASKS[task]["title"]})
    return lane._text_seen(backend, TASKS[task]["check"])


def measure(task: str, action) -> dict:
    prepare(task)
    marker, seen, stop = TASKS[task]["marker"], [], threading.Event()

    def sample():
        while not stop.is_set():
            if marker in fg_title():
                seen.append(1)
            time.sleep(0.01)

    th = threading.Thread(target=sample)
    th.start()
    t0 = time.perf_counter()
    note = None
    try:
        note = action()
    except Exception as exc:  # a tool failure is a result, not a harness crash
        note = f"{type(exc).__name__}: {exc}"[:300]
    total = round(time.perf_counter() - t0, 2)
    time.sleep(0.3)
    stop.set()
    th.join()
    ok = False
    try:
        ok = checked(task)
    except Exception as exc:
        note = (note or "") + f" | check failed: {exc}"[:200]
    if task == "form":
        close_form()
    return {"total_s": total, "correct": ok, "target_fg_samples": len(seen), "note": note}


class NitrolaneMCP:
    """nitrolane through its own MCP server: warm process, like the competitors' servers."""
    name = "nitrolane MCP (warm)"
    argv = [PY, str(ROOT / "nitrolane_mcp.py")]

    def __init__(self, c: Client):
        self.c = c

    def run(self, task, i):
        req = {**TASKS[task]["req"], "cache": True}
        if i == 0:
            lane._cache_path(req).unlink(missing_ok=True)
        out = json.loads(_text(self.c.tool("nitrolane_run", {"request": req}, timeout=180)[1]))
        return f"{'model' if i == 0 else 'replay'} status={out.get('status')} cache={out.get('cache')}"



# ---- tools -------------------------------------------------------------------------------

def run_nitrolane(task: str, i: int):
    req = {**TASKS[task]["req"], "cache": True}
    if i == 0:
        lane._cache_path(req).unlink(missing_ok=True)
    out = json.loads(subprocess.run([PY, str(ROOT / "nitrolane.py")], input=json.dumps(req), capture_output=True,
                                    text=True, encoding="utf-8").stdout)
    return f"{'model' if i == 0 else 'replay'} status={out.get('status')} cache={out.get('cache')}"


def _text(r: dict) -> str:
    if "error" in r:
        raise RuntimeError(json.dumps(r["error"], ensure_ascii=False)[:300])
    res = r.get("result") or {}
    t = " ".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
    if res.get("isError") or '"ok":false' in t.replace(" ", ""):
        raise RuntimeError(t[:300])
    return t


class DesktopTouch:
    name = "desktop-touch-mcp 2.3.1"
    argv = "npx.cmd -y @harusame64/desktop-touch-mcp@2.3.1"

    def __init__(self, c: Client):
        self.c = c

    def hwnd(self, task):
        return str(int(window(TASKS[task]["title"]).handle))

    def lease(self, hwnd, label, query=None):
        d = json.loads(_text(self.c.tool("desktop_discover", {"target": {"hwnd": hwnd}, "query": query or label})[1]))
        ent = next(e for e in d.get("entities", []) if e["label"] == label)
        return ent["lease"]

    def run(self, task, i):
        h = self.hwnd(task)
        if task == "calc":
            for aid in CALC_IDS:
                _text(self.c.tool("click_element", {"hwnd": h, "windowTitle": "Rechner", "automationId": aid})[1])
        elif task == "notepad":
            _text(self.c.tool("desktop_act", {"lease": self.lease(h, "Text-Editor"), "action": "setValue", "text": TEXT})[1])
        else:
            _text(self.c.tool("desktop_act", {"lease": self.lease(h, "Customer name"), "action": "setValue", "text": "Jürgen"})[1])
            try:
                _text(self.c.tool("desktop_act", {"lease": self.lease(h, "Country"), "action": "setValue", "text": "Österreich"})[1])
            except Exception:  # drop-down list: open it, then click the item
                _text(self.c.tool("desktop_act", {"lease": self.lease(h, "Country"), "action": "click"})[1])
                _text(self.c.tool("desktop_act", {"lease": self.lease(h, "Österreich"), "action": "click"})[1])
            _text(self.c.tool("click_element", {"hwnd": h, "windowTitle": "nitrolane fixture", "name": "Submit"})[1])


class Terminator:
    name = "terminator-mcp-agent"
    argv = "npx.cmd -y terminator-mcp-agent@latest"

    def __init__(self, c: Client):
        self.c = c
        self.schemas = {t["name"]: t.get("inputSchema") or {} for t in c.tools()}

    def call(self, tool, args):
        sch = self.schemas[tool]
        for key in sch.get("required", []):  # fill required flags/strings with neutral values
            if key not in args:
                typ = (sch["properties"].get(key) or {}).get("type")
                args[key] = False if typ == "boolean" else ""
        return _text(self.c.tool(tool, args, timeout=120)[1])

    def run(self, task, i):
        if task == "calc":
            for aid in CALC_IDS:
                self.call("invoke_element", {"process": "ApplicationFrameHost", "selector": f"nativeid:{aid}"})
        elif task == "notepad":
            self.call("set_value", {"process": "Notepad", "selector": "role:Document", "value": TEXT})
        else:
            self.call("set_value", {"process": "powershell", "selector": "name:Customer name", "value": "Jürgen"})
            self.call("select_option", {"process": "powershell", "selector": "name:Country", "option_name": "Österreich"})
            self.call("invoke_element", {"process": "powershell", "selector": "name:Submit"})


class WindowsMCP:
    name = "Windows-MCP"
    argv = ["uvx", "windows-mcp", "serve"]
    BUDGET_S = 120

    def __init__(self, c: Client):
        self.c = c
        self.yield_timeouts = 0  # after two runs lost to user activity, the rest is skipped (and reported)

    def call(self, tool, args, deadline):
        while True:  # the server hands control to the human on any input; wait as it asks
            r = self.c.tool(tool, args, timeout=max(5, deadline - time.monotonic()))[1]
            res = r.get("result") or {}
            t = " ".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
            if any(code in t for code in ("CONTROL_PREEMPTED", "USER_CONTROL", "TAKEOVER_PENDING")):
                if time.monotonic() > deadline:
                    self.yield_timeouts += 1
                    raise TimeoutError("yielded to user input until the budget ran out")
                try:
                    wait = json.loads(t)["status"].get("wait_seconds") or 2
                except Exception:
                    wait = 2
                time.sleep(min(wait + 0.3, 15))
                continue
            return _text(r)

    @staticmethod
    def center(el):
        r = el.rectangle()
        return [int((r.left + r.right) / 2), int((r.top + r.bottom) / 2)]

    def run(self, task, i):
        if self.yield_timeouts >= 2:
            raise TimeoutError("skipped: two earlier runs were lost to user activity")
        deadline = time.monotonic() + self.BUDGET_S
        win = window(TASKS[task]["title"])
        if task == "calc":
            for name in CALC_NAMES:
                el = win.descendants(control_type="Button", title=name)[0]
                self.call("Click", {"loc": self.center(el)}, deadline)
        elif task == "notepad":
            doc = win.descendants(control_type="Document")[0]
            self.call("Type", {"loc": self.center(doc), "text": TEXT, "clear": True}, deadline)
        else:
            self.call("Type", {"loc": self.center(win.descendants(control_type="Edit")[0]), "text": "Jürgen", "clear": True}, deadline)
            self.call("Click", {"loc": self.center(win.descendants(control_type="ComboBox")[0])}, deadline)
            time.sleep(0.4)
            item = next(i for w in Desktop(backend="uia").windows() for i in w.descendants(control_type="ListItem")
                        if i.window_text() == "Österreich")
            self.call("Click", {"loc": self.center(item)}, deadline)
            self.call("Click", {"loc": self.center(win.descendants(control_type="Button", title="Submit")[0])}, deadline)


def main() -> int:
    wanted = sys.argv[1:] or ["nitrolane", "nitrolane-mcp", "desktop-touch", "terminator", "windows-mcp"]
    os.environ["NITROLANE_LAUNCH_ALLOW"] = ""
    user = subprocess.Popen([PY, "-c", "import tkinter as t; r=t.Tk(); r.title('h2h user window'); "
                             "r.geometry('300x80+40+40'); r.mainloop()"])
    time.sleep(1.5)
    out_path = HERE / "battery_h2h_result.json"
    results = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    try:
        for tool in wanted:
            rows = {}
            if tool == "nitrolane":
                for task in TASKS:
                    rows[task] = [measure(task, lambda i=i, task=task: run_nitrolane(task, i)) for i in range(ROUNDS + 1)]
            else:
                cls = {"nitrolane-mcp": NitrolaneMCP, "desktop-touch": DesktopTouch, "terminator": Terminator,
                       "windows-mcp": WindowsMCP}[tool]
                rounds = ROUNDS + 1 if tool == "nitrolane-mcp" else ROUNDS  # first nitrolane round = model run
                t0 = time.perf_counter()
                client = Client(cls.argv)
                adapter = cls(client)
                rows["_startup_s"] = round(time.perf_counter() - t0, 2)
                try:
                    for task in TASKS:
                        rows[task] = [measure(task, lambda i=i, task=task: adapter.run(task, i)) for i in range(rounds)]
                finally:
                    client.close()
            results[tool] = rows
            print(tool, json.dumps(rows, ensure_ascii=False), flush=True)
            out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    finally:
        user.kill()
        close_form()
    return 0


if __name__ == "__main__":
    sys.exit(main())
