"""End-to-end recorder proof: simulate a human demo, then replay the generated request on a fresh form."""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\koopm\.omp\agent\vendor\arc-cua-windows\src")
from pywinauto import Desktop
from arc_cua.backends.windows_uia import send_unicode_text

HERE = Path(__file__).parent
LANE = HERE.parent / "nitrolane.py"
OUT = HERE / "recorded_request.json"


def kill_fixtures():
    subprocess.run(["powershell", "-NoProfile", "-c",
                    "Get-Process powershell -ErrorAction SilentlyContinue | ? MainWindowTitle -eq 'nitrolane fixture' | Stop-Process"],
                   capture_output=True)
    time.sleep(0.8)


def launch_form():
    subprocess.Popen(rf'powershell -NoProfile -ExecutionPolicy Bypass -File "{HERE / "form.ps1"}"',
                     shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        ws = [w for w in Desktop(backend="uia").windows() if w.window_text() == "nitrolane fixture"]
        if ws:
            return ws[0]
        time.sleep(0.2)
    raise RuntimeError("form did not appear")


kill_fixtures()
form = launch_form()
form.set_focus()
recorder = subprocess.Popen([sys.executable, str(HERE.parent / "nitrolane_record.py"),
                             "--title", "nitrolane fixture", "--seconds", "14", "--out", str(OUT),
                             "--goal", "Enter the customer name, choose the country, and submit the form",
                             "--check", "Hallo Jürgen aus Österreich"],
                            stdout=subprocess.PIPE, text=True, encoding="utf-8")
time.sleep(2.5)  # recorder attaches

# --- the "human" demonstration (real mouse + keyboard input) ---
textbox = form.descendants(control_type="Edit")[0]
textbox.click_input()
time.sleep(0.4)
send_unicode_text("Jürgen")
time.sleep(0.4)
combo = form.descendants(control_type="ComboBox")[0]
combo.click_input()
time.sleep(0.7)
item = next(i for w in Desktop(backend="uia").windows() for i in w.descendants(control_type="ListItem")
            if i.window_text() == "Österreich")
item.click_input()
time.sleep(0.4)
form.descendants(control_type="Button", title="Submit")[0].click_input()
rec_out, _ = recorder.communicate(timeout=60)
print(rec_out)
kill_fixtures()

# --- replay the generated request on a fresh form ---
launch_form()
req = json.loads(OUT.read_text(encoding="utf-8"))
saved = req["subtask"]["inputs"]
assert saved and all(v == "" for v in saved.values()), f"demo values leaked into the request file: {saved}"
# The caller supplies the values at replay time (here: the demonstrated ones, so the check holds).
text_key = next(k for k in saved if k.startswith("text"))
choice_key = next(k for k in saved if k.startswith("choice"))
req["subtask"]["inputs"] = {text_key: "Jürgen", choice_key: "Österreich"}
req = json.dumps(req, ensure_ascii=False)
proc = subprocess.run([sys.executable, str(LANE)], input=req, capture_output=True, text=True, encoding="utf-8", timeout=180)
result = json.loads(proc.stdout)
print(result["status"], result.get("cache"), result.get("check"), result.get("steps"))
kill_fixtures()
assert result["status"] == "SUBTASK_COMPLETE" and result.get("cache") == "hit" and result.get("check") is True, result
print("RECORDER-OK")
