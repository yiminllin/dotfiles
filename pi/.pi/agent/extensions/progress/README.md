# Pi progress panel

A local replacement for `rpiv-todo`. The panel above the input pins a recognizable
session title and genuine high-level outcomes, with the current milestone highlighted.
Keep pins as short as possible for Agent Board scanning, not full plans.
Use plain English. Write a 4–7 word title that names the topic and result.
Use common words and concrete verbs in short outcome labels and blockers.
For example, write “Test new drafts for all 273 PRs,” not “Replay full PR corpus.”
Use only these milestone emoji: 🔍 planning/investigation, 📦 deliverables,
👀 review, 🚀 verification/submission, and 📝 documentation. Not every category
needs a row. No emoji in titles or nested tasks. Keep ○ / ▶ / ✓ for status.
Describe what the user gains, not how we implement it. Keep requested deliverables
identifiable; track procedural requirements in hidden `now` context.
Related replies and detours keep the session goal, not a fixed milestone structure.
Pi asks for confirmation only when the title or goals are unclear.

Top-level items are recognizable user outcomes. Implementation details belong in
hidden `now` context, not visible nested tasks. Pi can rename, merge,
split, or reorder milestones. Preserve explicit requirements, dependencies, and
meaningful completion state, not fixed labels or a row for every past pass.
Distinct deliverables remain identifiable.

Reuse and reopen milestones for repeated planning, implementation, cleanup,
validation, restacking, and submission passes. Add a milestone when the evolving
scope needs a separate outcome. Regroup an overgrown roadmap instead of continually
appending rows. This is model-guided regrouping, not automatic label-based rewriting.

For example, a PR-chain roadmap can keep these outcomes across repeated passes:

```text
Frontend — independent generation and execution
✓ 🔍 Scope agreed
▶ 📦 Independent generation
    ✓ Standalone output
    ▶ Existing workflow support
○ 📦 Independent execution
○ 👀 Review complete
○ 🚀 Verified and submitted
```

Formatting, API wiring, build checks, restacking, and remote-head checks are
implementation details, not visible milestones or nested tasks. Track an
engineering step visibly only when the user explicitly asks to follow it.

Omit `tasks` by default. When nesting is essential to understand progress, show
only one or two short user-relevant sub-outcomes or decisions, without emoji.
When the user asks to track a bookmarked plan, keep up to three short steps in
order under its pending or current milestone. Completed milestones hide tasks.
Keep other procedures in hidden `now` context unless explicitly requested.

Use `blocker` only for an actual obstacle to the current work, such as missing API
issue details. State it briefly. Planning-only scope and unauthorized future
actions are constraints, not blockers, unless the current agreed step needs that
authorization. Keep constraints in conversation or hidden `now` context; they
still apply even when absent from the panel.

Status markers ○ / ▶ / ✓ are bold. The current label is also bold.
Current work uses yellow, done uses green, pending uses muted text,
and blockers use red through the active theme. Agent Board uses bold status rows
with the same colors; dimmed agents keep their dimmed style. There are no separate Now or
Block None rows. The optional `now` field remains available as hidden context.
Each `progress set` supplies a complete snapshot; identical snapshots are ignored.

- **Alt+T** or **`/progress`**: collapse or expand. Blockers stay visible when collapsed.
- **`/progress clear`**: dismiss the panel.
- Completed plans stay visible until replaced or cleared.
- **tmux prefix + a**: Agent Board shows equal-sized session blocks in four columns,
  filled left-to-right, then top-to-bottom. Each block has its own border and a
  shaded, bold supplied agent name above a separator. The progress goal is bold,
  blue, and underlined, so emphasis does not depend on font weight alone.
  Milestones use green for done, amber for current work, gray for pending, and red
  for blockers. The selected block has a cyan border. Dimmed blocks stay gray.
  Short blocks get padding; long text wraps. Scroll with **j/k** or **PgUp/PgDn**.
  Popup height fits the grid content when opened, up to 85% of the
  screen; one grid row opens shorter than two. Widen terminals below 54 columns.
- Agent numbers and positions stay fixed across status changes, dimming, and
  closing another agent. New agents take the first free slot. **1–9** jumps directly;
  **g → slot number → Enter** jumps to any slot (for example, **g → 12 → Enter**).
  **Arrows** select any agent, **Enter** jumps, and **Shift+A** dims the selection.
  The selected number is highlighted; current-window headings stay underlined.
- Agent Board needs Python 3. Pins publish directly from this extension to tmux.
  Existing Pi sessions keep extension code in memory: run **`/reload` once per
  session** to load the progress publisher. Board layout changes only need reopening
  the popup. Missing publication shows “Progress unavailable”; a connected session
  without a pin shows “No pinned progress”.
- The model updates only meaningful outcome, task-status, or blocker changes,
  not every reply or wait. Small follow-ups do not replace the session goals.
- A genuinely different session purpose replaces the roadmap. Abandoned goals
  are removed, not marked done. Pi cannot report live progress during a synchronous call.

State lives in branch-local custom session entries, including updates made through
Codemode. Reload, session resume, and compaction restore the latest snapshot on
the selected branch. A hidden context message reminds the model of the current
plan at the start of each run. Recent transcript bookmarks on the selected branch
inform the existing pin on the next agent turn. Pi uses relevant details without
copying the reply, replacing the pin, or changing status because of a bookmark.
Unmarking removes the extra context. No separate data file or model call is used.

## Activation

Stow the `pi` package so this directory appears as
`~/.pi/agent/extensions/progress`, then restart Pi. The managed settings remove
`rpiv-todo`; its cached package and old configuration are not deleted.

For a one-run trial without stowing, use:

```sh
pi -e ./pi/.pi/agent/extensions/progress/index.ts
```

From the repository root, run the offline checks with the installed Pi SDK:

```sh
JITI_FS_CACHE=0 node --test pi/.pi/agent/extensions/{progress,agent-board}/test.mjs
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest scripts/test_pi_agent_board.py
```

The tests load the actual extension and check rendering and state transitions.
They do not prove that the model chooses useful milestones. Verify that behavior
in a fresh interactive session with a real multi-step task and a scope change.
