# nitrolane micro-benchmark

Measured 2026-10-15 on this machine (Windows 11) with `tests/bench.py`.
Success counts only when the independent `check` passes. `run` excludes process start and page setup.

| Task | Success | Median run (s) |
|---|---:|---:|
| browser_form_jev | 2/2 | 4.92 |
| browser_form_cached | 2/2 | 1.28 |
| browser_form_param_b | 2/2 | 1.33 |
| browser_wiki_search | 2/2 | 3.16 |
| desktop_notepad_text | 2/2 | 1.96 |
| desktop_calc_7clicks | 2/2 | 3.19 |
| desktop_calc_cached | 2/2 | 1.6 |
| fleet_4_browser_tasks | 4/4 | wall 10.19 (serial sum 19.86) |
