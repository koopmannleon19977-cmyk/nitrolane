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
- **Record-and-replay cache**: verified trajectories are stored as *parameterized
  templates* (input values become variables) and re-executed by element name +
  geometry with semantic guards and probe-based settling — the same workflow with
  new data still costs zero model calls. A replay that breaks mid-way hands the
  reached state to the model (delta fallback); a failed post-replay check deletes
  the entry.
- **Provider freedom**: TypeSafe JEV by default, OpenAI Decisions, or any
  OpenAI-compatible chat endpoint (OpenAI, OpenRouter, Ollama, LM Studio) behind
  one finite-choice transport — plus an MCP server (`nitrolane_mcp.py`) and a
  `doctor` mode for instant setup diagnostics.
- **Pattern-first desktop**: clicks/values go through UIA patterns
  (Invoke/Toggle/SelectionItem/ValuePattern) before any pointer or foreground
  activation, and your original foreground window is restored when the run ends.
- **Transition verification**: optional per-step expectations stop a run whose
  intermediate state is wrong — even if the final screen would have looked right.
- **Parallel fleet** (`nitrolane_fleet.py`): many subtasks in one call — browser tabs
  run in parallel, desktop tasks stay sequential (one foreground). Measured: 4 wiki
  tasks in **10.2 s wall instead of 17.0 s serial**.
- **Demo recorder** (`nitrolane_record.py`): demonstrate a workflow once; nitrolane
  records clicks (resolved to element names), typed values and drop-down picks as a
  *parameterized* template and later replays it with new data — verified end to end
  (4 recorded steps → replay with zero model calls).
- **OCR last resort** (`ocr_capture.ps1`): for pixels-only UIs (canvas, custom-drawn
  controls) Windows.Media.Ocr finds the text and clicks it; UIA always wins when it
  can. Verified clicking a Tk canvas label (2.7 s).
- **Bring your own browser** (`"cdp": "http://127.0.0.1:9222"`): attach to any Chrome
  started with `--remote-debugging-port` (e.g. one you are logged into) instead of
  nitrolane's own profile. Opt-in only — the subtask then acts as that session.
- **A faster Windows backend** (`patches/`): UIA observation as a single CacheRequest
  subtree fetch (350 ms → 55 ms), exact layout-independent typing
  (ValuePattern first, Unicode `SendInput` fallback), native drop-down selection,
  pattern-first execution, one observe saved per action.
- **A safer decision loop**: risky controls are refused *by name* instead of hidden
  (hiding made the model substitute-click the wrong button), separate confidence
  gates for actions (0.35) and completions (0.30) — derived from battery data:
  multi-field tasks split confidence across equally valid first steps, so the gate
  sits below correct-but-ambiguous actions and above the observed wrong targets.
- **The verification methodology**: a 27-task battery where success is only counted
  when an independent check against the real UI agrees (`tests/`).

Details and per-change measurements: [`patches/README.md`](patches/README.md).

## Install (Windows 11)

Prerequisites: Python 3.12+, Chrome, git, and a decision provider —
a [TypeSafe](https://typesafe.com) key (`TYPESAFE_API_KEY`, default), an OpenAI
Decisions key, or any OpenAI-compatible chat endpoint (set
`NITROLANE_PROVIDER=chat`, `NITROLANE_MODEL`, `NITROLANE_BASE_URL`).

One command (PowerShell):

```powershell
irm https://raw.githubusercontent.com/koopmannleon19977-cmyk/nitrolane/main/install.ps1 | iex
```

Or manually:

```powershell
git clone https://github.com/koopmannleon19977-cmyk/nitrolane.git
cd nitrolane
.\setup.ps1   # pinned backend + nitrolane patches + venv, then smoke test and backend test suite
vendor\arc-cua-windows\.venv\Scripts\python.exe nitrolane.py doctor
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
  needs no scrolling decisions. **Desktop:** Windows UIA, pattern-first — clicks and
  values go through accessibility patterns without moving your pointer; keys and
  focus-clicks briefly come to the front, and your original window gets focus back.

Full contract and hard-won authoring rules (from the battery):
[`omp/skills/nitrolane/SKILL.md`](omp/skills/nitrolane/SKILL.md). The `omp/` folder
also ships ready-made [Oh My Pi](https://omp.sh) agents and a delegation rule that
route bounded subtasks to nitrolane first.

## Limitations

Preview quality, measured on one Windows 11 machine (German UI). Not for logins/2FA,
payments, uploads, drag & drop, canvas/graphics or cross-origin iframes. Desktop
input is pattern-first and your foreground window is restored afterwards, but keys
and focus clicks still come to the front briefly, and UWP apps self-activate on
Invoke; for true background control pair it with
[cua-driver](https://github.com/trycua/cua). The default JEV provider is a hosted
service — or bring your own model (see Install).

## Tests & benchmark

```powershell
# fixture server, in tests/pages:  python -m http.server 8765 --bind 127.0.0.1
vendor\arc-cua-windows\.venv\Scripts\python.exe tests\battery.py   # 27-task regression battery
vendor\arc-cua-windows\.venv\Scripts\python.exe tests\bench.py     # public micro-benchmark -> tests/bench_result.json
```

## Use it from your agent (MCP)

`nitrolane_mcp.py` exposes `nitrolane_run` and `nitrolane_doctor` over stdio MCP —
point Claude Code, Cursor, Codex or omp at
`vendor\arc-cua-windows\.venv\Scripts\python.exe nitrolane_mcp.py` and the agent
gets the whole lane as one tool call.

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
