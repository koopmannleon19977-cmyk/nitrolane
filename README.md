# nitrolane ⚡

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Platform: Windows 11](https://img.shields.io/badge/platform-Windows%2011-informational)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)

**The fast lane for browser and desktop automation.** One JSON request in, one
*verified* JSON result out. A small decision model (TypeSafe JEV) picks each click
from the elements the UI actually offers — no frontier LLM in the per-click loop,
no screenshots, no invented text. Repeat runs replay with **zero model calls**.

```text
planner (you / any LLM)                nitrolane                     UI
───────────────────────   subtask     ──────────────   action       ───
goal + inputs + check  ─────────────►  JEV decisions ─────────────►  Chrome / Windows app
                       ◄─────────────  ~0.3 s each   ◄─────────────  DOM / UIA tree
        verified JSON                    + replay cache
```

Built on [arc-cua](https://github.com/shhivv/arc-cua) (MIT, Shiv Shanmugam) and its
Windows fork [arc-cua-windows](https://github.com/GreenKeewi/arc-cua-windows) (MIT),
plus measured local patches — developed for the [Oh My Pi](https://omp.sh) agent on
Windows 11. Attribution: `THIRD_PARTY_NOTICES.md`; patches: `patches/LOCAL_PATCHES.md`.

## Measured, not promised

27-task battery (browser + desktop, every run independently checked against the real
UI state, Windows 11, 2026-10-15):

| Verdict | Count |
|---|---:|
| Verified success | 20 |
| Correct handback (missing input asked, forbidden action refused) | 6 |
| Missed a feasible task | 1 |
| False success | **0** |
| Constraint violation | **0** |

| Task | Model loop | Replay (0 model calls) |
|---|---:|---:|
| 6-field web form + submit | 4.7 s | **1.4 s** |
| Notepad: set document text | 4.0 s | **0.46 s** |
| Calculator: 7 button clicks | 6.4 s | **3.8 s** |

Browser median over the battery: 1.4 s per subtask; desktop median 5.0 s.
Why so fast? LLM-in-the-loop agents pay a full model round-trip per click;
nitrolane pays ~0.3 s for a finite-choice decision — and nothing on replays.

## Demo

```bash
"$ARC" nitrolane.py <<'EOF'
{"target":"browser","url":"https://httpbin.org/forms/post",
 "subtask":{"goal":"Fill the pizza order form and submit it",
  "inputs":{"name":"Max Muster","phone":"0123456","email":"max@example.com"},
  "verification":["The order was submitted and the response page is shown"],
  "constraints":["Choose size Medium","Select topping Bacon only"],"max_actions":15},
 "check":"document.body.innerText.includes('\"size\": \"medium\"')",
 "cache":true}
EOF
```

```json
{
 "status": "SUBTASK_COMPLETE",
 "actions": 6,
 "steps": [
  "TYPE_TEXT 'Customer name:' (replay)",
  "CLICK 'Submit order' (replay)"
 ],
 "cache": "hit",
 "check": true,
 "sec": { "setup": 0.72, "run": 1.31 }
}
```

## Install (Windows 11)

Prerequisites: Python 3.12+, Chrome, git, and a
[TypeSafe](https://typesafe.com) API key in your user environment (`TYPESAFE_API_KEY`).

```powershell
git clone https://github.com/koopmannleon19977-cmyk/nitrolane.git
cd nitrolane
.\setup.ps1   # pinned upstream + patches + venv, then smoke test and full upstream test suite
```

## How it works

- **Bounded subtasks.** You supply `goal`, literal `inputs`, `verification` criteria
  and `constraints`. JEV only chooses among offered elements/operations; it can never
  invent text. Missing value → `NEEDS_INPUT` naming the field.
- **Independent check.** `check` (JS expression in the browser, expected text on the
  desktop) verifies the real UI state after the run — success is never taken on faith.
- **Safety gates.** Risky controls (delete/send/purchase/close) are refused by name
  unless opted in via `allowed_risks`. Low-confidence decisions hand back
  (`NEEDS_AGENT`) instead of guessing. Secrets can be redacted via `secret_inputs`.
- **Browser:** one warm headless Chrome with its own profile (never yours), CDP,
  1280×2400 viewport so most content needs no scrolling decisions.
- **Desktop:** foreground Windows UIA. One CacheRequest per observation (~55 ms),
  exact typing via ValuePattern/Unicode input (keyboard-layout independent),
  native drop-down selection.
- **Cache:** `"cache": true` (requires `check`) records verified trajectories and
  replays them model-free; a failed post-replay check deletes the entry.

Full contract and hard-won authoring rules (from the battery):
`omp/skills/nitrolane/SKILL.md`.

## Limitations

Preview quality, measured on one Windows 11 machine (German UI). Not for logins/2FA,
payments, uploads, drag & drop, canvas/graphics or cross-origin iframes. Desktop is
foreground-only (your mouse/focus move); for background control pair it with
[cua-driver](https://github.com/trycua/cua). JEV is a hosted service — bring your own key.

## Tests

```powershell
# fixture server, in tests/pages:  python -m http.server 8765 --bind 127.0.0.1
vendor\arc-cua-windows\.venv\Scripts\python.exe tests\battery.py
```

## Roadmap

- Background desktop input pairing (cua-driver)
- OCR fallback for canvas/custom-drawn UIs
- Trajectory cache sharing across machines

## License

MIT for the nitrolane wrapper, tests and integration files. Upstream licenses and
attribution: `THIRD_PARTY_NOTICES.md`.
