# Changelog

## Unreleased

- Head-to-head on the battery's three desktop tasks (`tests/h2h/h2h_battery.py`, replaces the
  single-task calculator script): nitrolane CLI and warm MCP server vs desktop-touch-mcp 2.3.1,
  terminator-mcp-agent and Windows-MCP, same checks, 10 ms foreground sampling. desktop-touch-mcp,
  given element ids and no model, executes 2.5–3× faster than nitrolane's warm replay; terminator
  failed the form 3/3; Windows-MCP took 5–14 s and brought every app to the front; nitrolane's
  form replay still brings the form forward (Tab key, drop-down). Results in the README.

## v0.5.1 — 2026-10-15

- `app.launch` is skipped when a window with the title is already open: re-launching a
  single-instance app (Calculator) re-activated it and stole the user's focus even with the
  background tier (184–197 → 0 foreground samples per cached run).
- Corrected v0.5.0 background numbers measured with the app behind the user's window:
  0.12–0.13 s per click, 7-click replay 3.2 s run / 4.9 s end to end.
- Head-to-head vs terminator-mcp-agent and Windows-MCP, and a jev-1.14.0 vs jev-1.13.0 battery
  A/B (README, `tests/h2h/`, `tests/last_run_v05_jev114.json`).

## v0.5.0 — 2026-10-15

Security (all found by an internal review; none reachable before only because nobody used it):
- `app.launch` no longer runs through a shell and only starts notepad/calc/mspaint or exact
  command lines listed in `NITROLANE_LAUNCH_ALLOW`; the request is validated before launching.
- A request can no longer pick the provider endpoint or key (`base_url`, `api_key`,
  `api_key_env` are rejected): via MCP, any caller could send a stored key to any host.
  Use `NITROLANE_BASE_URL` / `NITROLANE_API_KEY`.
- Own Chrome: random DevTools port per start; attached only when the profile's
  `DevToolsActivePort` matches the listener (a foreign process on 9333 used to be driven).
  Explicit `cdp` endpoints must be loopback.
- `setup.ps1` checks the pinned backend archive's SHA256 and patches in a staging dir, so a
  failed patch can no longer leave an unpatched backend that later runs skip; `install.ps1`
  runs `doctor --deep` and fails when it fails.
- Recorder no longer writes demonstrated values to disk (`--keep-values` to opt in); drop-down
  picks are inputs too. OCR screenshots are unique per call and deleted right after.

Correctness:
- Desktop `check` matches whole words: "Anzeige lautet 15" no longer passes on 156. A check
  that already held before the run is reported (`check_before`) and never cached.
- Fleet: a task over `task_timeout_s` is reported as `TIMEOUT`; the batch keeps all other
  results (it used to print nothing).
- A cua-driver call that hangs ends the run instead of falling back (a late click plus the
  fallback would act twice).
- MCP server reports the real version and negotiates the protocol revision.

Speed (measured on the same machine as before):
- Background clicks: one persistent cua-driver session per process with its animated agent
  cursor off — 0.12–0.13 s per click with the app behind the user's window, 0.06 s when it is
  in front (was 0.3 s CLI per action; 0.6 s with the cursor animation).
- UIA settle polls the revision instead of a fixed 0.15 s pause: 7-click cached calculator
  replay 0.74 s in the foreground; fully in the background (user's window in front, 0 focus
  samples) 3.2 s run, 4.9 s end to end as a CLI call (was 2.6 s run, but stealing focus via
  a redundant `launch` of the already-open app — now skipped when the window exists).
- MCP server and fleet run subtasks in-process: same cached task 1.66 s per warm MCP call vs
  2.9 s as a fresh process; fleet 4 browser tasks 8.6 s wall vs 15.1 s serial.

## v0.4.0 — 2026-10-15

- **True background desktop** via cua-driver (when on PATH; `"background": false`
  opts out): clicks and values on uniquely named elements run in the cua-driver
  daemon, which holds no foreground rights, so UWP/WinUI apps cannot activate
  themselves. Measured with a 10 ms foreground sampler (`tests/test_background.py`):
  Notepad 109 → **0** and Calculator 271 → **0** foreign-foreground samples; cost
  ~0.3 s per action. Keys stay on the foreground path (PostMessage keys into WinUI
  Notepad landed only in some focus states, modifier chords never).
- **Ordered steps** (`"steps"` + required `check`): one decision per step, one
  action each. "7 plus 8": plain goal 0/3, goal with order hints 1/3 and 0/3, as
  steps 3/3.
- **Self-healing replay**: a template step whose element was renamed/translated is
  re-targeted by one decision (gate 0.6) and written back (`cache: healed`); measured
  3.7 s heal run, then 2.6 s zero-model replay. An unhealable step falls back to the
  model and the template is rebuilt (`cache: rebuilt`), including the kept prefix.
- `doctor --deep`: sends one real choice decision (measured: CLICK at 0.99 in 2.3 s),
  so a broken key/endpoint/model surfaces during setup rather than on the first task.
- Fork hook (`patches/`): `adapter.background(backend, snapshot, action)` runs before
  the pattern path.
- Docs: demo GIF (`docs/demo.gif`) and social preview (`docs/social-preview.png`).
- Verification: 28 battery tasks + 11 feature runs judged → 32 verified, 6 correct
  handbacks, 1 known miss, 0 false successes, 0 constraint violations.

## v0.3.0 — 2026-10-15

- **Parallel fleet** (`nitrolane_fleet.py`): batch subtasks; browser in parallel tabs,
  desktop sequential. Measured 4 wiki tasks: 10.2 s wall vs 17.0 s serial sum.
- **Demo recorder** (`nitrolane_record.py`): low-level mouse/keyboard hooks record a
  human demonstration into a *parameterized* template (typed values become inputs,
  drop-down picks become SET_VALUE, combo-open clicks dropped). Proof: 4 recorded
  steps replayed model-free on a fresh window (`cache: hit`).
- **OCR last resort** (`ocr_capture.ps1` + `"ocr"` in a desktop request):
  Windows.Media.Ocr locates text pixels and clicks it, with optional OCR post-check.
  Verified on a UIA-blind Tk canvas (2.7 s).
- **Bring your own browser**: `"cdp": "<endpoint>"` attaches to any
  `--remote-debugging-port` Chrome (logged-in sessions, opt-in); proof test included.
- **Engine A/B** (`tests/engine_ab.py`): Chrome 3/3, Moli 3/3 on the same tasks;
  Chrome faster on all three → Chrome stays the default.
- **Benchmark v2** (`tests/bench.py`): adds parameter-replay, cached desktop and fleet
  rows, writes `bench_result.md`. Medians (2 runs): form 4.92 s model / 1.28 s replay,
  parameter replay 1.33 s, wiki 3.16 s, Notepad 1.96 s, Calculator 3.19 s / 1.60 s
  cached, fleet 4/4 in 10.19 s.
- Fork fix in `patches/`: transient-UIA-read retry — a dropdown/dialog transition
  could raise COMError and abort a run.
- Verification: 41 records judged (battery + P1 features) → 33 verified successes,
  7 correct handbacks, 1 known miss (natural-order calculator task), 0 false
  successes, 0 constraint violations.

## v0.2.0 — 2026-10-15

- **Provider freedom**: decision provider is pluggable — TypeSafe JEV (default),
  OpenAI Decisions, or any OpenAI-compatible chat endpoint (OpenAI, OpenRouter,
  Ollama, LM Studio) via a finite-choice transport. Wire format covered by a stub
  test; live auth/request verified (an instruction-following model is required).
- **Replay 2.0**: cache entries are parameterized templates — the same workflow with
  different input values replays with zero model calls (verified: foreign form data,
  1.27 s). A replay that breaks mid-way hands the reached state to the model (delta).
- **Pattern-first desktop**: UIA Invoke/Toggle/SelectionItem/ValuePattern before any
  foreground activation; the user's foreground window is restored after desktop runs.
  Fixed a freshness bug where the follow-up key after typing erased the executed
  TYPE_TEXT from history (and from recorded trajectories).
- **Transition verification**: optional expected state after specific steps; a wrong
  transition stops the run even if the final screen would look right.
- **MCP server** (`nitrolane_mcp.py`), **`doctor`** mode, one-command `install.ps1`.
- **Public benchmark** (`tests/bench.py`): form 4.64 s model / 1.27 s replay,
  wiki search 3.09 s, Notepad 1.85 s, Calculator 2.9–5.3 s (medians of 2).
- Action confidence gate 0.45 → 0.35 (battery-derived: correct multi-field first
  steps score 0.33–0.43); full battery re-verified at the new gate.

## v0.1.0 — 2026-10-15

First public release.

- `nitrolane.py`: one-JSON-in / verified-JSON-out subtask lane for Chrome (warm
  headless instance, CDP 9333, 1280×2400) and Windows desktop (foreground UIA).
- Record-and-replay cache (`"cache": true`, requires `check`): verified trajectories
  replay with zero model calls; probe-based settling. Measured: web form 4.7→1.4 s,
  Notepad 4.0→0.46 s, Calculator 6.4→3.8 s.
- Confidence gates: 0.45 for actions, 0.30 for completions (battery-derived).
- Local patches on arc-cua-windows 659696d (`patches/`): single UIA CacheRequest
  observation (350→55 ms), exact layout-independent typing, native ComboBox
  selection, risky controls refused by name instead of hidden, separate completion
  confidence gate, 50 ms probe-less settle polling.
- 27-task regression battery with independent per-run checks: 26/27 correct,
  0 false successes, 0 constraint violations.
- Oh My Pi integration (`omp/`): skill, browser/computer agents, delegation rule.
