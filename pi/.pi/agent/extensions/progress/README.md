# Pi progress panel

A local replacement for `rpiv-todo`. The panel above the input shows the current
user goal, up to five outcome milestones, the current action, and a blocker.
Each `progress` tool update replaces the whole plan; it does not append tasks.

- **Alt+T** or **`/progress`**: collapse or expand. Blockers stay visible when collapsed.
- **`/progress clear`**: dismiss the panel.
- Completed plans stay visible until replaced or cleared.
- The model updates the panel at meaningful phase boundaries. It cannot report
  live progress while blocked in a synchronous call.

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
