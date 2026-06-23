---
name: project-workflow
description: /project-workflow Jira GitHub project workflow coordinator. Use when invoking /project-workflow, starting/resuming project workflows, coordinating Jira+GitHub+worktree+PR lifecycle, planning projects with Jira tickets and stacked PRs, or handling status/sync/pivot/reconsolidation requests.
---

# Project Workflow

Coordinate Jira/GitHub/project lifecycle work across OpenCode, branches,
worktrees, PRs, and git-spice stacks. Own diagnosis and sequencing; delegate
concrete Jira/PR/stack/review actions to existing owner skills.

For nested/stacked branches, prefer `git-spice` (`gs`) as the stack topology
interface. Observe stack position/order when it affects lifecycle state, then
queue confirmed track/reparent/restack/submit work for `stacked-pr-workflow`.

Principle: **observe automatically, recommend explicitly, write only after
confirmation**. Source truth is `opencode/.config/opencode/`; runtime config is
usually `~/.config/opencode/` and needs stow/reload plus OpenCode restart.

`/project-workflow $ARGUMENTS` is natural language. Infer start, resume, status,
sync, planning, pivot, or reconsolidation intent; do not require subcommands.

## Routing

Use when the user:

- invokes `/project-workflow`
- asks to start, resume, status-check, sync, pivot, or reconsolidate a Jira/GitHub project
- wants project planning tied to Jira tickets, branches/worktrees, stacked PRs,
  PR descriptions, reviews, or lifecycle state
- asks a Jira/PR/worktree/review question and an active project workflow appears
  relevant for the current repo, worktree, branch, PR, or Jira key

Do not use for:

- one-off Jira edits with no project lifecycle context: use `jira-ticket`
- PR body drafting only: use `pr-description-chain-writer`
- PR review-comment triage only: use `pr-address-comments`
- stack topology only: use `stacked-pr-workflow`
- private human review guides only: use `pr-human-review-guide`
- implementation/debugging tasks unrelated to Jira/GitHub project coordination

## Guardrails

- Run the packet helper read-only first; Phase 3/4 sync and reconciliation items
  are queue proposals, not execution.
- No hidden Jira/GitHub writes: do not run auth flows, mutate branches/worktrees,
  commit, push, merge, submit, resolve threads, upload externally, or change
  plugin/MCP config unless the user confirms that exact action.
- Destructive branch deletion, PR close/merge, Jira Done/Blocked/closed moves, and
  broad stack reparenting need separate confirmation after target/consequence.
- `git-spice` stack mutations such as track, reparent, restack, or submit are
  branch topology actions: recommend explicitly and delegate only after confirmation.
- Delegate confirmed writes/actions; do not duplicate owner-skill workflows.
- Treat local project state as memory, not authority. Reconcile against git,
  GitHub, and Jira before recommending writes.
- Do not store credentials, tokens, secret-bearing output, or long logs.

## State Model

Local state should live outside stowed source:

```text
~/.local/state/opencode-project-workflow/<repo-key>/<project-id>.json
```

For `dotfiles`, `<repo-key>` is `dotfiles`. A `<project-id>` may be a Jira key,
PR number, branch/stack slug, or user-confirmed project name. Keep state small:
repo path, Jira keys, branch/worktree names, PR URLs, lifecycle phase, pending
write proposals, and last observed summary.

## Workflow

1. Identify anchors: repo/worktree, branch, Jira key, PR number/URL,
   `git-spice` stack position/order, active plan, and desired outcome.
2. Build a read-only packet when available:
   `python3 opencode/.config/opencode/scripts/opencode_project_workflow_packet.py packet --repo . --format markdown`.
   Add `--pivot` for pivot/reconsolidation. If a read would cross auth/network,
   external-directory, or credential boundaries, stop and ask.
3. Compare observed vs intended lifecycle; name drift such as branch without PR,
   PR without Jira link, stale Jira status, review-driven scope change, or stack
   order mismatch.
4. Convert concrete `proposed` sync items into the queue schema below. Missing
   context stays an observation or next read-only step, not a write.
5. Show the numbered Pending sync/reconciliation queue before any write/action.
   Ask for item number(s), all, none, edit, defer, or not needed.
6. Delegate only confirmed items. Refresh the packet when later groups depend on
   current git/GitHub/Jira state. Report `updated`, `not updated`, or `draft only`
   with evidence.

## Pivot / Reconsolidation Flow

Use for pivot/reconsolidate, split/merge tickets, PR split/reorder/reparent,
abandon/replace PR, scope/plan/review/validation changes, branch rename,
Jira/GitHub drift, or stale local state.

1. **Freeze writes.** Say Jira/GitHub/branch/worktree writes are paused until
   specific reconciliation items are confirmed.
2. **Snapshot.** Run/read the packet helper read-only, preferably with `--pivot`,
   plus user hints.
3. **Classify.** Name likely pivot type(s): Jira split/merge, PR split/reorder,
   branch/worktree change, abandon/replace PR, review/validation scope change,
   stale local state, or status/link drift.
4. **Confirm ambiguity.** Ask one compact question only when the mapping changes
   the queue.
5. **Reconcile.** Build Phase 3 action records; every item requires explicit
   confirmation, including local-state corrections and drafts.
6. **Delegate and refresh.** Send confirmed groups to owner skills, refresh when
   needed, and report evidence-backed status.

Compact pivot snapshot shape:

```md
## Pivot snapshot
- freeze_writes: true
- user intent: <one sentence>
- observed state: <repo/branch/Jira/PR/worktree/local-state summary>
- pivot hints: <detected drift or user-provided change>
- classification: <pivot type(s) or needs decision>
- confidence/evidence limit: <what was and was not inspected>
```

## Pending Sync Queue

Use shadow mode first. Queue only concrete write/action proposals in these kinds:

- Jira status move, comment, description update, or link update
- PR body refresh
- `git-spice` track/reparent/restack/submit or worktree action
- review reply or resolution

All queued items require explicit confirmation. Queue/reconciliation schema:

- `id`: stable queue number such as `1`
- `target`: Jira key, PR, branch/worktree, review thread, or stack target
- `kind`: one of the allowed action kinds above
- `reason`: packet observation or user request that justifies the action
- `proposed_action`: exact action to delegate after confirmation
- `delegate_skill`: owner skill that will perform or draft the action
- `requires_confirmation`: always `yes`
- `status`: `proposed`, then `updated`, `not updated`, `draft only`, `deferred`,
  or `not needed`

Show the queue compactly:

```md
## Pending sync queue
| id | target | kind | reason | proposed_action | delegate_skill | requires_confirmation | status |
|---|---|---|---|---|---|---|---|
| 1 | Jira `FSW-123` | Jira status move | PR is open | Move to `In Review` | `jira-ticket` | yes | `proposed` |
| 2 | PR `#456` | PR body refresh | Jira link missing | Add Jira link to body | `pr-description-chain-writer` | yes | `proposed` |
```

If there are no writes, say `Pending sync queue: empty` or `Reconciliation queue:
empty` and give the next read-only/planning step. Never treat silence or vague
approval as permission to write.

## Delegation Map

- Jira status move/comment/description/link update: `jira-ticket`
- Stack/worktree branch topology, `git-spice` tracking, reparenting, restack,
  submit: `stacked-pr-workflow`
- Public PR body/Jira-link drafting: `pr-description-chain-writer`
- Existing PR review comments or bot feedback: `pr-address-comments`
- Private human review order, local comments, or Diffview guide: `pr-human-review-guide`
- Implementation/debug/review leaf work: route through the normal agent guide
  after project-workflow has clarified lifecycle context and boundaries.

## Output Contract

Default response:

1. **Current state** — concise repo/Jira/PR/branch/worktree/stack summary and evidence limits.
2. **Recommended next action** — one primary next step and owner skill.
3. **Pending sync/reconciliation queue** — proposed writes or `empty`.
4. **Need from you** — only decisions or confirmations required now.

For status requests, emphasize current state and pending queue. For planning
requests, include a short phased plan and which Jira/PR artifacts each phase
should own.
