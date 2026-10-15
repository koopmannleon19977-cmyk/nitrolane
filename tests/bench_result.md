# nitrolane micro-benchmark

Measured 2026-10-15 on this machine (Windows 11) with `tests/bench.py`.
Success counts only when the independent `check` passes. `run` excludes process start and page setup.

| Task | Success | Median run (s) |
|---|---:|---:|
| browser_form_jev | 2/2 | 4.8 |
| browser_form_cached | 2/2 | 0.29 |
| browser_form_param_b | 2/2 | 0.36 |
| browser_wiki_search | 2/2 | 2.85 |
| desktop_notepad_text | 2/2 | 2.72 |
| desktop_calc_7clicks | 2/2 | 7.64 |
| desktop_calc_cached | 2/2 | 2.53 |
| fleet_4_browser_tasks | 4/4 | wall 8.61 (serial sum 16.31) |
