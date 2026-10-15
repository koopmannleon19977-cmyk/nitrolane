# Changelog

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
