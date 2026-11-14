# Pi progress panel

A local replacement for `rpiv-todo`. The panel above the input pins a recognizable
session title and genuine high-level outcomes, with the current milestone highlighted.
Aim for 3–5 broad outcomes, not a chronological activity log. This is not a quota or
hard limit. Use short labels, usually 3–7 words, without repeating the session title.
Explicitly requested steps remain represented as milestones or tasks.
Related replies and detours keep the session goal, not a fixed milestone structure.
Pi asks for confirmation only when the title or goals are unclear.

Top-level items are milestones with recognizable outcomes. Execution steps belong
in `milestone.tasks`. As the conversation clarifies the work, Pi can rename, merge,
split, or reorder milestones. Preserve explicit requirements, dependencies, and
meaningful completion state, not fixed labels or a row for every past pass.
Distinct deliverables remain identifiable.

Reuse and reopen milestones for repeated planning, implementation, cleanup,
validation, restacking, and submission passes. Add a milestone when the evolving
scope needs a separate outcome. Regroup an overgrown roadmap instead of continually
appending rows. This is model-guided regrouping, not automatic label-based rewriting.

For example, a PR-chain roadmap can keep these outcomes across repeated passes:

- Implement the frontend and scenarios.
- Validate behavior and simplify the API.
- Organize buildable review commits and restack the chain.
- Submit the chain and verify remote heads.

Cleanup, boundary checks, and resubmission belong under these outcomes, not in
new top-level rows each time.

Each milestone can contain up to five optional `tasks`, but usually show only 1–3
useful immediate steps. Five is a schema limit, not a target. Only the current
milestone's tasks appear. Keep labels short, usually 3–7 words. Omit tasks that
repeat the milestone or list routine formatting, review, and speculative future
procedures. Group related checks as focused validation. Keep detailed procedures
in conversation or hidden `now` context.

Use `blocker` only for an actual obstacle to the current work, such as missing API
issue details. State it briefly. Planning-only scope and unauthorized future
actions are constraints, not blockers, unless the current agreed step needs that
authorization. Keep constraints in conversation or hidden `now` context; they
still apply even when absent from the panel.

Current work uses yellow, done uses green, pending uses muted text,
and blockers use red through the active theme. There are no separate Now or
Block None rows. The optional `now` field remains available as hidden context.
Each `progress set` supplies a complete snapshot; identical snapshots are ignored.

- **Alt+T** or **`/progress`**: collapse or expand. Blockers stay visible when collapsed.
- **`/progress clear`**: dismiss the panel.
- Completed plans stay visible until replaced or cleared.
- The model updates only meaningful outcome, task-status, or blocker changes,
  not every reply or wait. Small follow-ups do not replace the session goals.
- A genuinely different session purpose replaces the roadmap. Abandoned goals
  are removed, not marked done. Pi cannot report live progress during a synchronous call.

State lives in branch-local custom session entries, including updates made through
Codemode. Reload, session resume, and compaction restore the latest snapshot on
the selected branch. A hidden context message reminds the model of the current
plan at the start of each run. No separate data file or model call is used.

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
JITI_FS_CACHE=0 node --test pi/.pi/agent/extensions/progress/test.mjs
```

The tests load the actual extension and check rendering and state transitions.
They do not prove that the model chooses useful milestones. Verify that behavior
in a fresh interactive session with a real multi-step task and a scope change.
