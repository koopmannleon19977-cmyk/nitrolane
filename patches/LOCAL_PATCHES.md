# Local patches (nitrolane), on top of GreenKeewi/arc-cua-windows 659696d

`git diff` is authoritative. Each patch came from a failing nitrolane battery run (`tests/` in this repo).

| File | Change | Why (measured on Windows 11, German UI) |
|---|---|---|
| `backends/windows_uia.py` | Observation is one UIA CacheRequest subtree fetch (`_CachedNode`); `live()` gives a pywinauto wrapper for input | Calculator observe 350 ms → 55 ms; 7-click task 18.7 s → 6.8 s |
| `backends/windows_uia.py` | `TYPE_TEXT`: writable ValuePattern `SetValue` first (verified), else one `SendInput` batch of `KEYEVENTF_UNICODE` events | pywinauto typing via layout mapping (AltGr) dropped/repeated characters in Notepad (`"Hallo     arc-lane 22"`) |
| `backends/windows_uia.py` | ComboBox `SET_VALUE`/`TYPE_TEXT` select the item (ExpandCollapse+SelectionItem, else Win32 `CB_SETCURSEL`) | WinForms drop-down lists ignored typed text; pywinauto `select` looks for an English "Open" button |
| `backends/windows_uia.py` | Values normalize `\r`/`\r\n` to `\n`; Alt-tap fallback when `SetForegroundWindow` is refused; `foreground()` returns whether it activated, so `execute` rechecks freshness only after a real activation | Multiline verification; intermittent "did not grant foreground focus"; one observe less per action |
| `runtime.py` | Probe-less settle polls every 50 ms (was 100/120 ms) | Only Windows UIA uses this path; its observation is cheap now |
| `runtime.py` | `RuntimeConfig.min_completion_confidence` | Correct completions scored 0.38–0.43, wrong actions ≤ 0.43: one threshold could not separate them |
| `policies/choice.py`, `safety.py` | Risky controls stay offered; the runtime still refuses them (NEEDS_AGENT naming the risk) | Hidden "Delete account" made JEV click "Save note" instead; hidden "Send me product updates" looped into BLOCKED |
| `tests/…`, `tests/golden/…` | Tests for the above; goldens regenerated (`ARC_UPDATE_GOLDEN=1`) | |

After pulling upstream: re-apply, run `python -m pytest -q`, then the nitrolane battery.
