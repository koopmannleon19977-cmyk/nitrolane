# nitrolane plan to 1.0 — research-backed, 2026-10-15

Sources (all read today; vendor claims marked as such in the research notes): browser-use 118k★,
agent-browser 44k★, chrome-devtools-mcp 53.6k★, playwright-mcp 38.2k★, stagehand 25.7k★, Skyvern
23.2k★ (AGPL), browser-harness 18.4k★, midscene 15.3k★, nanobrowser 14.1k★, notte 2k★ (SSPL),
LaVague (stale); OpenHands, open-interpreter, UI-TARS-desktop, trycua/cua, Agent-S, GenericAgent, UFO³,
Windows-MCP, terminator, desktop-touch-mcp, bytebot (stale); argofowl/FowlBrowser + the two @argofowl
posts, fowllabs.com, songkeys/claude-codex-computer-use, pkyanam/OpenSky, TMH13/codex-computer-use-for-
claude-code, browser-use/jev-ultrafast; leaderboards OSWorld-Verified, cuaspeedrun, Steel hub
(WebVoyager / Online-Mind2Web / WebArena), BU Bench v2.1, stagehand evals, WindowsAgentArena.

## 1. Where the field is, and the gap nitrolane can own

- **The metric everyone now posts is task-level:** tasks right · seconds per task · $ per task, on a
  published task file (FowlBrowser 26/26 · 15 min · $8.34 vs Codex 23/26; jev-ultrafast 7.1 s; Sai
  $14.34/task; cuaspeedrun s + $ per task). nitrolane publishes only component numbers (0.3 s/decision,
  replay seconds). **No task-level number = no credibility.**
- **"Background, never steals focus" is now table stakes** (cua/Hermes, Claude Cowork, Codex engine,
  FowlBrowser, terminator, desktop-touch). What differentiates is *proof* (FowlBrowser: 188/188 cursor on
  target, 0 focus steals, 12 agents at once) and *enforcement* (user's-turn detector, CDP allowlist).
- **The strongest browser design today is FowlBrowser — and it is macOS-only.** Real signed-in browser,
  background tabs via an MV3 extension + native-messaging host (no debugging port), tab ownership /
  park / handoff, turn-scoped release, document-scoped refs, changes-only snapshots, pointer pre-flight
  with a named reason, stuck-page liveness, cookie/password redaction, upload path policy. **Nobody ships
  this on Windows.** That is nitrolane's opening: *FowlBrowser-class browser lane on Windows, plus the
  finite-choice decision model, zero-model replay, verified results and the UIA desktop lane in one.*
- **Speed recipe that wins:** fewer model calls per task, not faster calls — jev-ultrafast (1,092 → 101
  browser calls), stagehand observe→replay, Skyvern on-demand context (2.3× faster, prompt cache 27→80 %),
  UFO² speculative batches, Sai "explore once, compile to self-healing code". nitrolane already has the
  replay half; it lacks multi-step decisions per call and a content-addressed cache.
- **Precision recipe that wins:** stale-handle refusal instead of retry (OpenSky, FowlBrowser, notte,
  chrome-devtools uid), pre-action guards/leases (desktop-touch), refuse-with-reason instead of "done".
- **Benchmarks runnable on Windows:** WebVoyager (Apache-2.0, local Selenium/Chrome, one site ≈ 43 tasks),
  stagehand evals (`-e local`, nitrolane as a tool surface), WindowsAgentArena (Docker/WSL2, 154 tasks;
  needs your OK). OSWorld, cuaspeedrun, BU Bench, WebArena are Linux/Modal/macOS-bound.

## 2. Phases

Each phase ends with: fixtures + battery green, jevify with the frozen rubric (0 false successes, no
regression vs previous release), head-to-head rerun, README numbers updated, release.

### P0 — Task-level measurement first (everything later is judged by it)
1. **Public task file** `bench/tasks/*.jsonl`: 30 browser + 20 desktop tasks, each with an executable
   grader (JS / UIA check), no hand judging. Includes logged-in-free real sites + local fixtures.
2. **Planner shim** `nitrolane_agent.py`: one LLM call turns an instruction into nitrolane subtasks
   (goal, inputs, verification, check); re-plans only on handback. Reports `cost_usd`, seconds, calls.
3. **Runner** `bench/run.py`: per tool → tasks right, s/task, $/task, model calls, focus samples (10 ms
   sampler, already built), records every run as JSON for jevify. Same planner model for every tool.
4. **Competitors on the same file** (all driven by the same planner via MCP): browser-use, agent-browser,
   playwright-mcp, chrome-devtools-mcp, jev-ultrafast (browser); desktop-touch-mcp, Windows-MCP,
   terminator, cua-driver (desktop). Publish every row, including losses.
5. **WebVoyager one-site subset (≈43 tasks)** locally, then 3 sites. Report next to the Steel board rows
   with "self-run, subset" stated.

### P1 — Real-browser lane for Windows (the headline feature)
1. **MV3 extension + native-messaging host** (HKCU registry, no admin), `chrome.debugger` + `chrome.tabs`,
   named pipe `\\.\pipe\nitrolane-<browser>` with a per-install token instead of a debugging port.
   Chrome, Edge, Brave. Opt-in per browser; own headless Chrome stays the default.
2. **Background tabs:** `active:false`, muted, own tab group, `autoDiscardable:false`,
   `Emulation.setFocusEmulationEnabled`, `Page.setWebLifecycleState active`; never `bringToFront`;
   popups adopted in the background; last-window guard.
3. **Ownership + handoff:** owned/unowned tabs, `park` (takeover/handoff) for logins, 2FA, CAPTCHA,
   payments → nitrolane returns `NEEDS_USER` with the tab, resumes on claim. **User's-turn detector**
   (agent input windows + tab focused) so the lane never types where the human just clicked.
4. **Turn/session scoping:** session id on every call, release tabs at turn end (Claude Code / omp Stop
   hook), idle release + transparent re-attach.
5. **Safety:** CDP method allowlist (refuses future domains), navigation only http/https/about/data,
   cookie values hidden, password fields masked before any snapshot, upload path policy (no hidden/system
   paths, no paths another account can swap), approval policy enum (`untrusted` / `all`).

### P2 — Observation and precision
1. **Document-scoped refs**: refs renumbered per document; a ref from an older document or vanished
   element is refused immediately with a reason (no blind retry). Frames `f<seq>eN`, closed shadow roots
   via `DOM.getDocument` pierce.
2. **Changes-only snapshots** after actions (diff vs last full snapshot, full above ~60 % change);
   snapshot cap by characters.
3. **Pointer pre-flight**: hit-test before click; covered/disabled/hidden → fail in ≤1 s naming the
   cover. **Stuck-page liveness** probe (`Runtime.evaluate 1`, 15 s) + `terminateExecution`.
4. **Settle by cause**: wait for the navigation/request chain the action started (cap 3 s), not a timer.
5. **Uploads** (`DOM.setFileInputFiles`) behind the path policy; **downloads** into an approved dir.
6. **Desktop parity**: lease + pre-action guard (desktop-touch), cua-driver `background_unavailable`
   ladder surfaced in results, queryable owner state (Windows-MCP ControlStatus style), lock-screen →
   queue, never inject.

### P3 — Fewer decisions per task (speed)
1. **observe → plan N**: one decision call returns an ordered list of actions for the visible form
   (JEV multi-question request), validated step by step against live state (UFO² speculative batch).
   Target: 6-field form from 6 decisions to 1–2.
2. **Content-addressed cache**: key = goal template + page fingerprint (URL pattern + candidate
   signature), model excluded; `stability` threshold before a template is trusted.
3. **A/B the candidate encoding** (HTML vs current), candidate prefilter beyond the 240 cap, prompt-cache
   friendly ordering. Keep only what wins on the task file.
4. **Persistent worker** for CLI callers (named pipe), so every entry point gets the warm-MCP numbers.

### P4 — Breadth and public scores
1. Desktop breadth battery: Word/Excel (no save), VS Code, Explorer (temp dir), Settings page, Clock,
   Paint — reversible tasks only; Chromium a11y enablement for Electron apps; Java Access Bridge note.
2. Vision fallback (small model, opt-in) only for canvas / cross-origin iframes / icon-only controls.
3. WindowsAgentArena 10-task smoke → 154 (needs WSL2 + Docker + ISO terms — your decision).
4. stagehand evals with nitrolane as tool surface; Online-Mind2Web subset with the recorder's trajectory.

### P5 — Launch
`--skill` and `--check` commands (OpenSky/TMH13 pattern), install that auto-reads cua-driver/browser
paths, demo GIF of the real-browser lane, then omp Discord → Show HN → r/AI_Agents with the task-level
table. Social preview and key rotation first.

## 3. Test plan

| Layer | What | Gate |
|---|---|---|
| Unit (CI, windows-latest) | security refusals, check regex, cache key, ref staleness, path policy, CDP allowlist | all pass on every push |
| Fixtures (local pages/apps) | iframes (same/cross origin), closed shadow DOM, popups, slow loads, cookie banner, covered button, upload, download, dialog, infinite script, form with blur validation, Win32/WinUI/WinForms/Electron apps | per feature: listed fixtures pass 3/3 |
| Battery (28 → 50 tasks) | existing + new P1/P2 cases, handbacks included | jevify: 0 false success, 0 violations, ≥ previous correct |
| Focus | 10 ms foreground sampler on every browser and desktop task | 0 samples with background tier |
| Concurrency soak | 12 agents × forms in parallel tabs (FowlBrowser method) | 100 % fields right, no cross-agent mixing, no leftover tabs |
| Task file h2h | nitrolane vs listed tools, same planner | published table; regressions block release |
| Public subsets | WebVoyager site subset, WAA smoke (if approved) | published with "self-run, subset" |
| Security | token/pipe auth, allowlist bypass attempts, path-swap race, prompt-injected page asking for secrets | all refused |

## 4. Targets (measured on the task file, same machine)

- Correct ≥ best open-source competitor on the same planner; 0 false successes.
- Browser task median ≤ 0.5× browser-use with the same planner; replay ≤ 1 s per form.
- 0 focus steals across all background runs; 12 parallel agents without mixing.
- Model cost per task on the file ≤ ¼ of the next tool (zero-model replays counted honestly).

## 5. Decisions needed from the user

1. Real-browser lane uses an unpacked extension + native host in the user's Chrome/Edge (opt-in): yes/no.
2. Planner model and budget for the task file (same model for all tools).
3. WindowsAgentArena (WSL2, Docker, Microsoft evaluation ISO terms).
4. Order: P0 first is recommended — without it no later claim is measurable.
