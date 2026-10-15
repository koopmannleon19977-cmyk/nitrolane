# nitrolane ⚡

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Platform: Windows 11](https://img.shields.io/badge/platform-Windows%2011-informational)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
[![Release](https://img.shields.io/github/v/release/koopmannleon19977-cmyk/nitrolane)](https://github.com/koopmannleon19977-cmyk/nitrolane/releases)

**The fast lane for browser and desktop automation.** One JSON request in, one
*verified* JSON result out. Instead of paying a frontier LLM for every click,
nitrolane lets a decision model (TypeSafe JEV) choose each action from the elements
the UI actually offers — ~0.3 s per decision, no screenshots, no invented text.
Anything it has done once and verified, it replays later with **zero model calls**.

```text
planner (you / any LLM)                nitrolane                     UI
───────────────────────   subtask     ──────────────   action       ───
goal + inputs + check  ─────────────►  JEV decisions ─────────────►  Chrome / Windows app
                       ◄─────────────  ~0.3 s each   ◄─────────────  DOM / UIA tree
        verified JSON                    + replay cache
```

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

Browser median over the battery: 1.4 s per subtask · desktop median: 5.0 s.
Reproduce them yourself: `tests/battery.py` (see [Tests](#tests)).

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

Desktop works the same way: `"target":"desktop","app":{"title":"Rechner","launch":"calc.exe"}`.

## What nitrolane adds

Everything in this repo is nitrolane's own engineering on top of two MIT backends
(credits below) — the backends are downloaded at install time, never vendored:

- **The lane itself** (`nitrolane.py`): request/result contract, warm-Chrome
  management (own profile, never the user's), UWP window resolution, minimized-window
  restore, independent `check`/`extract` verification in the same call.
- **Record-and-replay cache**: verified trajectories are stored and re-executed by
  element name + geometry with semantic guards and probe-based settling — repeat
  work costs zero model calls; a failed post-replay check deletes the entry.
- **A faster Windows backend** (`patches/`): UIA observation as a single CacheRequest
  subtree fetch (350 ms → 55 ms), exact layout-independent typing
  (ValuePattern first, Unicode `SendInput` fallback), native drop-down selection,
  one observe saved per action.
- **A safer decision loop**: risky controls are refused *by name* instead of hidden
  (hiding made the model substitute-click the wrong button), separate confidence
  gates for actions (0.45) and completions (0.30) — thresholds derived from battery
  data, where correct actions scored ≥ 0.5 and wrong targets ≤ 0.43.
- **The verification methodology**: a 27-task battery where success is only counted
  when an independent check against the real UI agrees (`tests/`).

Details and per-change measurements: [`patches/README.md`](patches/README.md).

## Install (Windows 11)

Prerequisites: Python 3.12+, Chrome, git, and a
[TypeSafe](https://typesafe.com) API key in your user environment (`TYPESAFE_API_KEY`).

```powershell
git clone https://github.com/koopmannleon19977-cmyk/nitrolane.git
cd nitrolane
.\setup.ps1   # pinned backend + nitrolane patches + venv, then smoke test and backend test suite
```

## The contract

- **Bounded subtasks.** You supply `goal`, literal `inputs`, `verification` criteria
  and `constraints`. The model only chooses among offered elements/operations; it can
  never invent text. Missing value → `NEEDS_INPUT` naming the field.
- **Independent check.** `check` (JS expression in the browser, expected text on the
  desktop) verifies the real UI state after the run — success is never taken on faith.
- **Safety gates.** Delete/send/purchase/close controls are refused by name unless
  opted in via `allowed_risks`. Low-confidence decisions hand back (`NEEDS_AGENT`)
  instead of guessing. Secrets stay hidden from the model via `secret_inputs`.
- **Browser:** one warm headless Chrome, CDP, 1280×2400 viewport so most content
  needs no scrolling decisions. **Desktop:** foreground Windows UIA.

Full contract and hard-won authoring rules (from the battery):
[`omp/skills/nitrolane/SKILL.md`](omp/skills/nitrolane/SKILL.md). The `omp/` folder
also ships ready-made [Oh My Pi](https://omp.sh) agents and a delegation rule that
route bounded subtasks to nitrolane first.

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
- Public benchmark runs (OSWorld/WebArena-style scoring)

## Credits & License

nitrolane is MIT-licensed (see [`LICENSE`](LICENSE)). It executes through
[arc-cua](https://github.com/shhivv/arc-cua) by Shiv Shanmugam (MIT) and its Windows
fork [arc-cua-windows](https://github.com/GreenKeewi/arc-cua-windows) (MIT), downloaded
pinned at install time. Full attribution: [`NOTICE`](NOTICE).
