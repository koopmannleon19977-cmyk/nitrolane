"""Put fixture apps into a known state between battery runs: notepad -> empty, calc -> 0."""
import sys
from pywinauto import Desktop

for w in Desktop(backend="uia").windows():
    title = w.window_text()
    if sys.argv[1] == "notepad" and "Notepad" in title:
        w.descendants(control_type="Document")[0].iface_value.SetValue("")
    if sys.argv[1] == "calc" and title == "Rechner":
        w.descendants(control_type="Button", title="Löschen")[0].iface_invoke.Invoke()
