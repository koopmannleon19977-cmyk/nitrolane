# Changelog

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
