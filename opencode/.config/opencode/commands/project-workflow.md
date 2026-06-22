---
description: Coordinate Jira, GitHub PRs, worktrees, and project lifecycle via project-workflow
agent: orchestrator
---

Load and use the `project-workflow` skill for this request.

Treat `$ARGUMENTS` as natural-language project context/intent, not subcommands:

```text
$ARGUMENTS
```

Route status/sync/planning/pivot/reconsolidation through `project-workflow` first.
Use its read-only packet helper when available, show any pending sync or
reconciliation queue, require explicit confirmation for concrete writes/actions,
then delegate confirmed Jira/PR/stack/review items to the owner skills.
