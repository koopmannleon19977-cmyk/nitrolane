"""Same 12 x 12 = calculator task through nitrolane (CLI process per run, as an agent would call it)."""
import ctypes, json, subprocess, sys, threading, time
HERE = __import__('pathlib').Path(__file__).resolve().parent
from pywinauto import Desktop
T = str(HERE.parents[1])
u = ctypes.windll.user32; u.GetForegroundWindow.restype = ctypes.c_void_p
def fgtitle():
    b = ctypes.create_unicode_buffer(200); u.GetWindowTextW(ctypes.c_void_p(int(u.GetForegroundWindow() or 0)), b, 200); return b.value
req = json.load(open(T + r"\tests\cache_req_calc.json", encoding="utf-8"))
user = subprocess.Popen([sys.executable, "-c", "import tkinter as t; r=t.Tk(); r.title('h2h user window'); r.geometry('300x80+40+40'); r.mainloop()"])
time.sleep(1.5)
rows = []
for label, extra in [("model loop", {"cache": False}), ("cached replay", {}), ("cached replay", {}), ("cached replay", {})]:
    subprocess.run([sys.executable, T + r"\tests\reset.py", "calc"])
    next(w for w in Desktop(backend="uia").windows() if w.window_text() == "h2h user window").set_focus(); time.sleep(0.4)
    seen, stop = [], threading.Event()
    def sample():
        while not stop.is_set():
            if fgtitle() == "Rechner": seen.append(1)
            time.sleep(0.01)
    th = threading.Thread(target=sample); th.start()
    t0 = time.perf_counter()
    out = json.loads(subprocess.run([sys.executable, T + r"\nitrolane.py"], input=json.dumps({**req, **extra}),
                                    capture_output=True, text=True, encoding="utf-8").stdout)
    total = round(time.perf_counter() - t0, 2)
    time.sleep(0.3); stop.set(); th.join()
    rows.append({"mode": label, "total_s": total, "status": out["status"], "check": out.get("check"), "cache": out.get("cache"),
                 "actions": out.get("actions"), "target_fg_samples": len(seen)})
    print(rows[-1], flush=True)
user.kill()
json.dump(rows, open(HERE / "nitrolane_result.json", "w", encoding="utf-8"), indent=1)
