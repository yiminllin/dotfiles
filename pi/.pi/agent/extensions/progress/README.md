# Pi progress panel

A local replacement for `rpiv-todo`. The panel above the input pins a recognizable
session title and genuine high-level outcomes, with the current milestone highlighted.
Explicitly requested steps stay separate; there is no fixed top-level milestone limit.
Related replies and detours keep the same roadmap. Pi asks for confirmation only when the title or goals are unclear.

Small refinements belong under an existing milestone when one fits. As related
small items accumulate, Pi folds them into tasks under one new outcome-based
milestone, such as `Polish review output`, preserving their status and meaningful
detail. This is model-guided regrouping, not automatic label-based rewriting.
Distinct deliverables are not merged just to shorten the panel.

Each milestone can contain up to five optional `tasks`. Only the current milestone's
tasks appear. Current work uses yellow, done uses green, pending uses muted text,
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
