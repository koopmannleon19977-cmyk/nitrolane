# arc-lane

A fast lane for bounded browser and Windows-desktop subtasks: one JSON request in,
one verified JSON result out. A small decision model (TypeSafe JEV) picks each click
from the elements the UI actually offers — no frontier model in the per-click loop,
no screenshots, no invented text.

Built on [arc-cua](https://github.com/shhivv/arc-cua) (MIT, Shiv Shanmugam) and its
Windows fork [arc-cua-windows](https://github.com/GreenKeewi/arc-cua-windows) (MIT),
plus local patches and measurements developed for the [Oh My Pi](https://omp.sh) agent
on Windows 11. See `THIRD_PARTY_NOTICES.md` and `patches/LOCAL_PATCHES.md`.

## Measured (Windows 11, 2026-10-15, 27-task battery, independently checked per run)

| Verdict | Count |
|---|---:|
| Verified success | 20 |
| Correct handback (missing input / forbidden risk refused) | 6 |
| Missed a feasible task | 1 |
| False success | 0 |
| Constraint violation | 0 |

Runtime: browser median 1.4 s per subtask, desktop median 5.0 s. With the
record-and-replay cache, repeat runs skip the model entirely
(e.g. form 4.7 s → 2.95 s, Notepad 3.98 s → 0.53 s).

## Why it is fast

- JEV chooses from a finite action space (~0.3 s/decision); literal text only ever
  comes from `inputs`.
- Browser: one warm headless Chrome (own profile, CDP port 9333, 1280×2400 viewport);
  DOM observation only.
- Desktop: one UIA CacheRequest per observation (~55 ms instead of ~350 ms),
  ValuePattern-first typing with a Unicode fallback (layout-independent),
  native drop-down selection.
- Safety: risky controls (delete/send/purchase/close) are refused by name unless the
  subtask opts in via `allowed_risks`; confidence gates hand back instead of guessing.
- Cache: `"cache": true` records verified trajectories and replays them with zero
  model calls; a failed post-replay check deletes the entry.

## Install (Windows 11)

Prerequisites: Python 3.12+, Chrome, a TypeSafe API key in the user environment
(`TYPESAFE_API_KEY`), git.

```powershell
git clone <this repo> arc-lane
cd arc-lane
.\setup.ps1   # clones the pinned fork, applies patches/, builds the venv, runs smoke + tests
```

## Use

```bash
ARC="vendor/arc-cua-windows/.venv/Scripts/python.exe"
"$ARC" arc_lane.py <<'EOF'
{"target":"browser","url":"https://httpbin.org/forms/post",
 "subtask":{"goal":"Fill the pizza order form and submit it",
  "inputs":{"name":"Max Muster","phone":"0123456","email":"max@example.com"},
  "verification":["The order was submitted and the response page is shown"],
  "constraints":["Choose size Medium","Select topping Bacon only"],"max_actions":15},
 "check":"document.body.innerText.includes('\"size\": \"medium\"')",
 "cache":true}
EOF
```

Desktop: `"target":"desktop","app":{"title":"Rechner","launch":"calc.exe"}` —
foreground only (real mouse/focus move). Full contract and authoring rules:
`omp/skills/arc-lane/SKILL.md`.

## Tests

`tests/battery.py` runs 27 browser/desktop tasks, each with an independent check
(fixture server: `python -m http.server 8765 --bind 127.0.0.1` in `tests/pages`).

## Limitations

Preview-quality: one Windows 11 machine measured (German UI/keyboard). No logins/2FA,
uploads, drag & drop, canvas/graphics, cross-origin iframes; no minimized/locked/
elevated windows; desktop is foreground-only. JEV is a hosted service (own key required).

## License

MIT for the arc-lane wrapper, tests and integration files. Upstream licenses and
attribution: `THIRD_PARTY_NOTICES.md`.
