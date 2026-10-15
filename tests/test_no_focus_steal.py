"""Prove the user's foreground window is back after a desktop run (pattern-first + restore).

Note: UWP/WinUI apps activate themselves on Invoke, and key submissions need the
foreground briefly — measured OS behavior; nitrolane restores the original window.
"""
import ctypes
import json
import subprocess
import sys
import time

from pywinauto import Desktop

user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = ctypes.c_void_p


def fg_title():
    hwnd = int(user32.GetForegroundWindow() or 0)
    for w in Desktop(backend="uia").windows():
        if int(w.handle) == hwnd:
            return w.window_text()
    return f"hwnd {hwnd}"

subprocess.Popen(r'powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\koopm\.omp\agent\tools\nitrolane\tests\form.ps1"',
                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(50):
    if any(w.window_text() == "nitrolane fixture" for w in Desktop(backend="uia").windows()):
        break
    time.sleep(0.2)
note = next(w for w in Desktop(backend="uia").windows() if "Notepad" in w.window_text())
note.set_focus()
time.sleep(0.4)
before = fg_title()
req = json.loads(open(sys.argv[2], encoding="utf-8").read())
proc = subprocess.run([sys.executable, sys.argv[1]], input=json.dumps(req), capture_output=True, text=True, encoding="utf-8", timeout=120)
result = json.loads(proc.stdout)
after = fg_title()
print(result["status"], result.get("check"), result["sec"])
print("foreground before:", before)
print("foreground after: ", after)
assert result["status"] == "SUBTASK_COMPLETE" and result["check"] is True
assert "Notepad" in after, "foreground was stolen"
print("PATTERN-FIRST-OK (no focus steal)")
