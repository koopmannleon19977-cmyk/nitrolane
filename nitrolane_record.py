"""nitrolane demo recorder: watch a human demonstration in one window, emit a replayable request.

Records mouse clicks (resolved to UIA element names) and typed text (focused field values)
in the target window, parameterizes typed values as inputs, writes a nitrolane request JSON
and installs the recorded trajectory as a cache template for that request.

    nitrolane_record.py --title "nitrolane fixture" --seconds 20 --out request.json \
        --goal "Submit the form" --check "Hallo Jürgen aus Österreich"
"""
import argparse
import ctypes
import ctypes.wintypes
import importlib.util
import json
import sys
import time
from pathlib import Path

_VENDOR_SRC = Path(__file__).parent / "vendor" / "arc-cua-windows" / "src"
if _VENDOR_SRC.exists():
    sys.path.insert(0, str(_VENDOR_SRC))
from pywinauto import Desktop  # noqa: E402
from arc_cua.backends import WindowsUIABackend  # noqa: E402

spec = importlib.util.spec_from_file_location("nitrolane", Path(__file__).parent / "nitrolane.py")
lane = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lane)

user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p]
user32.CallNextHookEx.restype = ctypes.c_long
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
VK_LBUTTON, VK_RETURN = 0x01, 0x0D





def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--title", required=True, help="window title substring to record in")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--out", default="recorded_request.json")
    ap.add_argument("--goal", default="Replay the recorded demonstration")
    ap.add_argument("--check", default=None, help="desktop check text for the generated request")
    args = ap.parse_args()

    win = next(w for w in Desktop(backend="uia").windows() if args.title in (w.window_text() or ""))
    pid, hwnd = win.process_id(), int(win.handle)
    backend = WindowsUIABackend(pid, window_id=hwnd)
    title = win.window_text()
    print(f"Recording {title!r} (pid {pid}) for {args.seconds}s — demonstrate now.", flush=True)

    steps: list[dict] = []
    inputs: dict[str, str] = {}
    pending: dict | None = None  # {name, initial, bounds} of the field being edited
    combo_values: dict[str, str] = {}
    held_combo: dict | None = None  # combo-open click held until its outcome is known

    def observe():
        try:
            return backend.observe()
        except Exception:  # UIA can fail transiently while the UI transitions (dropdown opening)
            time.sleep(0.3)
            return backend.observe()

    def flush_text(key: str | None = None) -> None:
        nonlocal pending
        if pending is None:
            return
        snap = observe()
        el = next((e for e in snap.elements if e.name == pending["name"] and e.role == "TextField"), None)
        value = "" if el is None or el.value is None else str(el.value)
        if value and value != pending["initial"]:
            key_name = f"text{len(inputs) + 1}"
            inputs[key_name] = value
            steps.append({"action": "TYPE_TEXT", "target_name": pending["name"], "target_bounds": pending["bounds"],
                          "value": {"$input": key_name}, "key": key, "hotkey": None,
                          "click_modifier": None, "scroll_direction": None})
        pending = None

    def track_focus() -> None:
        nonlocal pending
        snap = observe()
        refresh_combo_values(snap)
        focused = next((e for e in snap.elements if e.focused and e.role == "TextField"), None)
        if focused is not None and (pending is None or pending["name"] != focused.name):
            flush_text()
            b = focused.bounds
            pending = {"name": focused.name, "initial": "" if focused.value is None else str(focused.value),
                       "bounds": {"x": b.x, "y": b.y, "width": b.width, "height": b.height} if b else None}

    def refresh_combo_values(snap) -> None:
        for e in snap.elements:
            if e.role == "ComboBox":
                combo_values[e.name] = "" if e.value is None else str(e.value)

    def settle_combo() -> bool:
        """Resolve a held combo-open click: selection changed -> SET_VALUE, else keep the click."""
        nonlocal held_combo
        if held_combo is None:
            return False
        time.sleep(0.35)
        try:
            refresh_combo_values(observe())
        except Exception:
            return False
        name = held_combo["name"]
        current = combo_values.get(name, "")
        if current != held_combo["before"]:
            steps.append({"action": "SET_VALUE", "target_name": name,
                          "target_bounds": held_combo["step"]["target_bounds"], "value": current,
                          "key": None, "hotkey": None, "click_modifier": None, "scroll_direction": None})
            print(f"  SET_VALUE {name!r} = {current!r}", flush=True)
            held_combo = None
            return True
        steps.append(held_combo["step"])
        print(f"  CLICK {name!r}", flush=True)
        held_combo = None
        return False

    deadline = time.time() + args.seconds

    # Low-level hooks see physical and injected input alike; GetAsyncKeyState misses the latter.
    events: list = []

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class MSLL(ctypes.Structure):
        _fields_ = [("pt", POINT), ("mouseData", ctypes.c_ulong), ("flags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("extra", ctypes.c_size_t)]

    class KBDLL(ctypes.Structure):
        _fields_ = [("vk", ctypes.c_ulong), ("scan", ctypes.c_ulong), ("flags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("extra", ctypes.c_size_t)]

    HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p)

    def mouse_proc(nCode, wParam, lParam):
        if nCode >= 0 and wParam == 0x0201:  # WM_LBUTTONDOWN
            ms = ctypes.cast(lParam, ctypes.POINTER(MSLL)).contents
            events.append(("click", ms.pt.x, ms.pt.y))
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def key_proc(nCode, wParam, lParam):
        if nCode >= 0 and wParam == 0x0100:  # WM_KEYDOWN
            if ctypes.cast(lParam, ctypes.POINTER(KBDLL)).contents.vk == VK_RETURN:
                events.append(("enter",))
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    mouse_cb, key_cb = HOOKPROC(mouse_proc), HOOKPROC(key_proc)  # keep refs alive for the hook lifetime
    hooks = [user32.SetWindowsHookExW(14, mouse_cb, None, 0), user32.SetWindowsHookExW(13, key_cb, None, 0)]

    class MSG(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint), ("wParam", ctypes.c_size_t),
                    ("lParam", ctypes.c_size_t), ("time", ctypes.c_ulong), ("pt", POINT)]

    msg = MSG()
    last_combo: dict = {"name": None}
    try:
        refresh_combo_values(observe())
    except Exception:
        pass
    while time.time() < deadline:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        while events:
            ev = events.pop(0)
            if int(user32.GetForegroundWindow() or 0) != hwnd:
                continue
            if ev[0] == "enter":
                flush_text(key="ENTER")
                continue
            _, x, y = ev
            flush_text()
            if held_combo is not None and settle_combo():
                time.sleep(0.25)  # this click was the drop-down pick; it is now a SET_VALUE step
                track_focus()
                continue
            # Resolve at the point (covers popup windows like drop-down lists), fall back to the window tree.
            name = role = bounds = None
            try:
                from pywinauto.uia_element_info import UIAElementInfo

                info = UIAElementInfo.from_point(x, y)
                name, role = info.name, info.control_type
                r = info.rectangle
                bounds = {"x": r.left, "y": r.top, "width": r.right - r.left, "height": r.bottom - r.top}
            except Exception:
                snap = observe()
                hits = [e for e in snap.elements if e.bounds and e.visible
                        and e.bounds.x <= x <= e.bounds.x + e.bounds.width
                        and e.bounds.y <= y <= e.bounds.y + e.bounds.height]
                if hits:
                    el = min(hits, key=lambda e: e.bounds.width * e.bounds.height)
                    name, role = el.name, el.role
                    bounds = {"x": el.bounds.x, "y": el.bounds.y, "width": el.bounds.width, "height": el.bounds.height}
            if name is not None:
                step = {"action": "CLICK", "target_name": name, "target_bounds": bounds,
                        "value": None, "key": None, "hotkey": None,
                        "click_modifier": None, "scroll_direction": None}
                if role == "ComboBox":
                    last_combo["name"] = name
                    held_combo = {"name": name, "before": combo_values.get(name, ""), "step": step}
                elif role == "ListItem" and last_combo["name"]:
                    # A drop-down pick replays cleanly as SET_VALUE on the combo, not as a popup click.
                    steps.append({"action": "SET_VALUE", "target_name": last_combo["name"], "target_bounds": bounds,
                                  "value": name, "key": None, "hotkey": None,
                                  "click_modifier": None, "scroll_direction": None})
                    held_combo = None
                    print(f"  SET_VALUE {last_combo['name']!r} = {name!r}", flush=True)
                else:
                    steps.append(step)
                    print(f"  CLICK {name!r}", flush=True)
            time.sleep(0.25)  # let focus land before tracking text
            track_focus()
        time.sleep(0.02)
    for hook in hooks:
        user32.UnhookWindowsHookEx(hook)
    if held_combo is not None:
        settle_combo()
    flush_text()
    # A combo-open click right before its SET_VALUE is redundant (and its open popup breaks UIA reads).
    steps = [s for i, s in enumerate(steps)
             if not (s["action"] == "CLICK" and i + 1 < len(steps)
                     and steps[i + 1]["action"] == "SET_VALUE" and steps[i + 1]["target_name"] == s["target_name"])]

    request = {"target": "desktop", "app": {"title": title},
               "subtask": {"goal": args.goal, "inputs": inputs,
                           "verification": ["The recorded workflow completed"]},
               "cache": True}
    if args.check:
        request["check"] = args.check
    Path(args.out).write_text(json.dumps(request, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.check:  # lane cache requires an independent check
        path = lane._cache_path(request)
        lane.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"steps": steps}, ensure_ascii=False), encoding="utf-8")
        print(f"Template installed: {path}")
    print(f"Recorded {len(steps)} steps -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
