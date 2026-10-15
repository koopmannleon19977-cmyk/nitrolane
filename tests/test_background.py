"""Prove the background tier: desktop runs never hand the foreground to the target app.

A stand-in "user" window gets the foreground; a sampler reads GetForegroundWindow every
10 ms during each run and counts samples where the target app's window is in front, so a
steal is caught even though nitrolane restores focus at the end (and a human switching
windows meanwhile does not count). Each task also runs with "background": false as the control.
Usage: python test_background.py <nitrolane.py>   (needs cua-driver on PATH)
"""
import ctypes
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from pywinauto import Desktop

user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = ctypes.c_void_p
HERE = Path(__file__).parent
TASKS = {
    "notepad": {"target": "desktop", "app": {"title": "– Notepad"},
                "subtask": {"goal": "Replace the document text with the supplied text",
                            "inputs": {"text": "nitrolane background"},
                            "verification": ["The document text is exactly the supplied text"], "max_actions": 3},
                "check": "nitrolane background"},
    "calc": {"target": "desktop", "app": {"title": "Rechner"},
             "subtask": {"goal": "Compute 7 times 6 by clicking 7, multiply, 6, equals in this order",
                         "verification": ["The display shows 42"], "max_actions": 6},
             "check": "Die Anzeige lautet 42"},
}


def title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(200)
    user32.GetWindowTextW(ctypes.c_void_p(hwnd), buf, 200)
    return buf.value


def run(task: str, background: bool) -> tuple[dict, list]:
    subprocess.run([sys.executable, str(HERE / "reset.py"), task], check=True)
    win = next(w for w in Desktop(backend="uia").windows() if w.window_text() == "nitrolane user window")
    win.set_focus()
    time.sleep(0.3)
    marker = TASKS[task]["app"]["title"]
    seen, stop = [], threading.Event()

    def sample():
        while not stop.is_set():
            name = title(int(user32.GetForegroundWindow() or 0))
            if marker in name:
                seen.append(name)
            time.sleep(0.01)

    t = threading.Thread(target=sample)
    t.start()
    proc = subprocess.run([sys.executable, sys.argv[1]], input=json.dumps({**TASKS[task], "background": background}),
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    stop.set()
    t.join()
    return json.loads(proc.stdout), seen


for exe, marker in (("notepad.exe", "– Notepad"), ("calc.exe", "Rechner")):  # open before any sampling
    if not any(marker in w.window_text() for w in Desktop(backend="uia").windows()):
        subprocess.Popen(exe, shell=True)
        time.sleep(2.5)
user_app = subprocess.Popen([sys.executable, "-c", "import tkinter as t; r=t.Tk(); r.title('nitrolane user window'); "
                             "r.geometry('300x80+40+40'); r.mainloop()"])
failures = []
try:
    for _ in range(50):
        if any(w.window_text() == "nitrolane user window" for w in Desktop(backend="uia").windows()):
            break
        time.sleep(0.1)
    for task in TASKS:
        for background in (True, False):
            r, seen = run(task, background)
            print(f"{task} background={background}: {r.get('status')} check={r.get('check')} sec={r.get('sec')} "
                  f"target-in-foreground samples={len(seen)}")
            if background and (r.get("check") is not True or seen):
                failures.append(task)
finally:
    user_app.kill()
assert not failures, f"background tier failed for {failures}"
print("BACKGROUND-OK (target app never in the foreground with the background tier)")
