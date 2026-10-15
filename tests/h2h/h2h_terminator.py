"""Calculator 12 x 12 = by element name through terminator-mcp-agent (no model), 3 rounds.
Records per-call latency, total, correctness (display) and target-in-foreground samples."""
import ctypes, json, subprocess, sys, threading, time
HERE = __import__('pathlib').Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mcpclient import Client
from pywinauto import Desktop

u = ctypes.windll.user32; u.GetForegroundWindow.restype = ctypes.c_void_p
def fgtitle():
    b = ctypes.create_unicode_buffer(200); u.GetWindowTextW(ctypes.c_void_p(int(u.GetForegroundWindow() or 0)), b, 200); return b.value
def display():
    calc = next(w for w in Desktop(backend="uia").windows() if w.window_text() == "Rechner")
    return next(t.window_text() for t in calc.descendants(control_type="Text") if "Anzeige" in t.window_text())

SEQ = ["clearButton", "num1Button", "num2Button", "multiplyButton", "num1Button", "num2Button", "equalButton"]
c = Client("npx.cmd -y terminator-mcp-agent@latest")
proc = sys.argv[1] if len(sys.argv) > 1 else "CalculatorApp"
user = subprocess.Popen([sys.executable, "-c", "import tkinter as t; r=t.Tk(); r.title('h2h user window'); r.geometry('300x80+40+40'); r.mainloop()"])
time.sleep(1.5)
rounds = []
for rnd in range(int(sys.argv[2]) if len(sys.argv) > 2 else 2):
    subprocess.run([sys.executable, str(HERE.parent / "reset.py"), "calc"])
    next(w for w in Desktop(backend="uia").windows() if w.window_text() == "h2h user window").set_focus()
    time.sleep(0.4)
    seen, stop = [], threading.Event()
    def sample():
        while not stop.is_set():
            if fgtitle() == "Rechner":
                seen.append(1)
            time.sleep(0.01)
    th = threading.Thread(target=sample); th.start()
    t0 = time.perf_counter(); per = []; err = None
    for name in SEQ:
        dt, r = c.tool("invoke_element", {"process": proc, "selector": f"nativeid:{name}",
                                          "verify_element_exists": "", "verify_element_not_exists": "",
                                          "highlight_before_action": False, "ui_diff_before_after": False,
                                          "include_monitor_screenshots": False, "include_window_screenshot": False}, timeout=60)
        per.append(dt)
        if "error" in r or (r.get("result") or {}).get("isError"):
            err = json.dumps(r, ensure_ascii=False)[:400]; break
    total = round(time.perf_counter() - t0, 2)
    time.sleep(0.3); stop.set(); th.join()
    rounds.append({"total_s": total, "per_call_s": per, "display": display(), "target_fg_samples": len(seen), "error": err})
    print(rounds[-1], flush=True)
c.close(); user.kill()
json.dump(rounds, open(HERE / "terminator_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
