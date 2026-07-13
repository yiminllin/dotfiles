---
name: project-workflow
description: Coordinate an active Jira, GitHub, branch, worktree, or stacked-PR project in one visible Pi session. Use for starting, resuming, status-checking, syncing, pivoting, or reconsolidating project lifecycle work and routing confirmed leaf actions to installed skills.
---

# Project Workflow

## Purpose

Coordinate project lifecycle diagnosis and sequencing in Pi's single visible
session. Keep routing sticky while the current repo, worktree, branch, Jira key,
PR, or user-named project remains active. Use installed leaf skills for concrete
Jira, PR, review, and stack workflows rather than reproducing them here.

Principle: **observe locally, recommend explicitly, act only after confirmation**.

## Use and routing

Use for project start, resume, status, sync, planning, pivot, or
reconsolidation, and when an ordinary Jira/PR/worktree/review request belongs to
an active project context. Preserve that context across later requests in this
session until the user closes it, switches projects, or evidence makes the
mapping ambiguous.

Route a one-off leaf request directly instead:

- Jira ticket operation: `/skill:jira-ticket`
- stack topology or worktree operation: `/skill:stacked-pr-workflow`
- public PR body draft/update: `/skill:pr-description-chain-writer`
- existing review-comment triage: `/skill:pr-address-comments`
- private local review guide: `/skill:pr-human-review-guide`

## Boundaries

- Coordinate visibly in the current session. Do not claim subagents, parallel
  execution, background work, or enforced tool permissions.
- Local reads are the default. Before network, authentication, provider/model,
  external-directory, repository mutation, state-file write, or external-system
  action, stop and request approval for the exact boundary and action.
- Never initiate or repair authentication. Never install dependencies.
- Do not create, switch, delete, reset, clean, commit, push, merge, submit,
  reparent, restack, resolve, post, or edit external state from this coordinator.
- Treat lifecycle state as memory, not authority. Reconcile it with available
  source evidence before recommending changes.
- Destructive branch actions, PR close/merge, Jira terminal-status moves, and
  broad stack reshaping require their own confirmation after consequences are
  shown, even if related work was previously approved.
- A user confirmation applies only to the numbered queue item(s) named. Silence,
  vague approval, or approval of a read does not authorize a write.

## Lifecycle state

Track the active project in conversation first. When durable state is requested
or an existing state file is supplied, use:

```text
~/.local/state/pi-project-workflow/<repo-key>/<project-id>.json
```

Keep only repo path, project id, Jira keys, branches/worktrees, PR references,
stack order, lifecycle phase, pending queue, and last observed summary. Do not
store credentials, tokens, secret-bearing output, or long logs. Reading outside
the current repo or writing this file crosses a boundary and requires approval.

Lifecycle phases are descriptive, not automatic transitions: planning,
ticketed, branched, PR open, review, merge ready, merged, and closed. Preserve a
user-confirmed phase until source evidence or the user changes it; report drift
instead of silently rewriting it.

## Workflow

1. **Identify anchors.** Capture the repo/worktree, current branch, Jira key,
   PR number/URL, local stack order, active plan, intended outcome, prior state,
   and current lifecycle phase. Ask one compact question only when ambiguity
   changes project identity, boundaries, or the queue.
2. **Check local sources.** With read-only local commands, inspect only what is
   needed: repository guidance and active plan, `git status`, branch/remotes,
   `git worktree list --porcelain`, relevant diffs/logs, and
   `git-spice log long` when installed and stack topology matters. Do not fetch.
   Missing `git-spice` limits stack evidence; it does not justify installation
   or a mutating plain-Git fallback.
3. **Compare intended and observed state.** Name source limits and drift such as
   branch without known PR, PR without Jira mapping, stale lifecycle phase,
   review-driven scope change, dirty-worktree risk, or stack-order mismatch.
   Do not infer live Jira/GitHub state from local hints.
4. **Map boundaries.** Separate the next steps into local read, local draft,
   repository mutation, network/auth read, and external write. Keep gated steps
   pending until explicitly approved.
5. **Build the pending queue.** Queue only concrete actions. Missing context is
   an observation or next read, not a write proposal. Show the queue before any
   handoff and ask for item numbers, `all`, `none`, `edit`, `defer`, or
   `not needed`.
6. **Hand off visibly.** For each confirmed item, tell the user the exact
   `/skill:<name>` invocation and compact context packet to use next. Do not
   perform or restate the leaf workflow. If later work depends on changed state,
   return here and refresh local evidence before preparing another handoff.
7. **Report status.** Mark each item `updated`, `not updated`, `draft only`,
   `deferred`, or `not needed` only from evidence returned in this session.
   Propose any durable state update as a separately confirmed queue item.

## Pivot and reconsolidation

For ticket split/merge, PR split/reorder/replacement, branch/worktree change,
review or validation scope change, or stale mappings:

1. State that writes and mutation handoffs are frozen.
2. Snapshot the active anchors, prior lifecycle state, local source evidence,
   user intent, and evidence limits.
3. Classify the pivot and ask one question only if competing mappings produce
   different queues.
4. Rebuild the queue. Include local-state correction as a confirmed item when
   durable state is in use.
5. Resume explicit handoffs only for confirmed items, then refresh evidence.

## Pending queue

Use this schema:

| id | target | kind | reason | proposed action | boundary | handoff | confirm | status |
|---|---|---|---|---|---|---|---|---|
| 1 | `<target>` | `<action kind>` | `<evidence>` | `<exact action>` | `<local draft / repo mutation / network-auth read / external write>` | `/skill:<owner>` | yes | proposed |

Allowed action kinds are Jira status/comment/description/link work, PR body
draft/update, stack/worktree topology work, review reply/resolution, private
review guide, and durable lifecycle-state update. If there are none, say
`Pending sync queue: empty` and give one next read-only or planning step.

## Handoff map

- Jira status, comment, description, or link: `/skill:jira-ticket`
- Stack/worktree inspection or mutation planning: `/skill:stacked-pr-workflow`
- Public PR body or Jira-link drafting: `/skill:pr-description-chain-writer`
- Existing PR feedback: `/skill:pr-address-comments`
- Private local review order/guide: `/skill:pr-human-review-guide`

Each handoff packet contains only the confirmed queue id, target, requested
outcome, known local evidence, evidence limits, exact approved boundary (if
any), and required return status. The leaf skill owns its own checks and must
request any approval its workflow requires.

## Compact output

1. **Current state** — active project, lifecycle phase, local source evidence,
   and limits.
2. **Recommended next action** — one primary step and explicit skill handoff.
3. **Pending sync/reconciliation queue** — proposed items or `empty`.
4. **Need from you** — only the decision, approval, or missing anchor needed now.

For a pivot, prepend `Writes frozen` and include the old-to-new boundary mapping.
