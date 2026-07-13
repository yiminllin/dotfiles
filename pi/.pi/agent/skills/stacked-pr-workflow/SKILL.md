---
name: stacked-pr-workflow
description: Inspect, track, reparent, restack, squash, and submit stacked PR branches conservatively, especially with git-spice. Use when the user wants help keeping PR boundaries clean, restacking in order, or resubmitting a stack.
---

# Stacked PR Workflow

## Purpose

Manage a stacked PR chain conservatively with `git-spice` as the stack topology source of truth and plain `git` as the local diff/log source of truth. Focus on stack structure, PR boundaries, restacking, and submission discipline.

Read-only local inspection is the default. Obtain explicit approval before
tracking, reparenting, restacking, squashing, syncing, submitting, switching
branches, or otherwise changing Git/stack state. Network/auth access and PR
writes require separate approval. Never start auth, force push, bypass hooks,
or invent a plain-Git mutation fallback.

Lazy-load `references/command-recipes.md` only when exact command syntax, local alias notes, rare branch surgery, or longer examples are needed.

## Use / do not use

Use this skill when the user wants to:

- inspect a tracked stack, branch order, PR mapping, or dirty-worktree safety
- track manually created branches in `git-spice`
- verify PR boundaries before or after mutation
- reparent, restack, squash, sync, submit, or resubmit stacked branches
- keep PR boundaries clean while addressing stack feedback

Do not use this as the primary workflow for:

- public PR-body writing; use `pr-description-chain-writer`
- actionable review-comment triage; use `pr-address-comments`
- private human review guides; use `pr-human-review-guide`
- broad Jira/project lifecycle coordination; use `project-workflow` first

## Guardrails and boundaries

- Prefer `git-spice` for stack tracking, topology, navigation, reparenting, restacking, squashing, syncing, and submitting. Use plain `git status`, `git diff`, and `git log` for local source-of-truth inspection.
- Ensure `git-spice` is available before stack work. If missing, stop; use plain Git only for read-only inspection unless the user separately requests and approves a mutation approach.
- Do not mutate a stack until the worktree is understood. Stop if unrelated local changes are mixed in; ask whether to stash, split, commit, or leave them untouched.
- Treat tracking, reparenting, restacking, squashing, syncing, and submitting as stateful history-shaping actions. Use the least invasive command that matches the requested change.
- Avoid interactive prompts and editors in autonomous runs. Supply explicit flags when possible; otherwise stop and ask.
- Do not force push, pass `--force`, or pass `--no-verify` unless the user explicitly requests it.
- Use GitHub/`gh` only for requested PR inspection or submission verification when authenticated. Do not run auth/login flows; if auth is missing, report the blocker.
- Submit/update PRs only when the user asked for submission or resubmission. Prefer a dry run after recent reparent/restack/squash work.
- When addressing stacked review feedback, fix the lowest affected PR first and re-check all upstack boundaries.
- When updating stacked PR descriptions, keep the chain-level reason/context identical, update only the PR Tree arrow, and put per-PR details in Description of Change.

## Core workflow

Start with the safest read-only mode that answers the request, then move to mutations only after the stack and worktree are safe.

1. Inspect stack state.
2. Verify PR boundaries before mutation.
3. Perform one narrow mutation mode if requested or clearly required.
4. Verify branch order, diff boundaries, PR mapping, and worktree state after each mutation.
5. Stop and report blockers before crossing auth, destructive, force, or interactive boundaries.

## Modes

### inspect-stack

Use first for most stack requests. Collect:

- `git status`
- current branch
- `git-spice log long` stack order and tracking state
- existing PR number/url/title/head/base/draft/review state when `gh` is available and relevant

Summarize stack order, tracked/untracked branches, PR mapping, dirty-worktree safety, and the likely next operation.

### track-branches

Use when branches already exist but are not tracked by `git-spice`, or after creating a new branch with plain `git`. Prefer `git-spice branch track` for one branch and `git-spice downstack track` for an already-created untracked stack. Include an explicit base when inference is ambiguous or boundary-critical.

After tracking, re-run `git-spice log long` and confirm the stack shape before restack or submit.

### verify-boundaries

For each adjacent stack pair, use local diffs and logs to confirm reviewer-visible scope:

- `git diff <base>...<branch>` for each PR boundary
- `git log --oneline --decorate <base>..<branch>` for commit scope
- `git-spice log long` for tracked branch order

Check that each PR contains only intended changes, higher-PR work has not leaked downward, no boundary depends on uncommitted changes, and one-commit expectations are met when requested.

### reparent-stack

Use when the stack shape is wrong, not merely stale. Prefer direct `branch onto` or `upstack onto` operations when the intended parent change is simple. Treat `stack edit` as a manual fallback for complex reorderings because it opens an editor.

After reparenting, re-run stack inspection and boundary verification before continuing.

### restack-stack

Use when branch relationships are correct but history needs to be rebased cleanly onto tracked bases. Prefer whole-stack restack for “clean up this stack” and upstack restack for “start here and restack this branch plus higher branches”. Use skip-start only when the starting branch is already correct.

If a rebase stops on conflicts, report the conflict state and use the normal git-spice continue/abort flow only after the conflict resolution path is clear.

### squash-stack

Only squash when the user explicitly asks or clearly wants one-commit PRs. Squash one branch at a time, usually lowest to highest, and avoid editors by using an explicit commit message or `--no-edit` when appropriate.

After each squash, inspect status, stack order, commit log, and boundary diffs. Remember that branch squash can restack upstack branches.

### submit-stack

Submit only the narrowest requested scope: one branch or a branch plus its upstack. Before submitting, confirm branch order, starting branch, draft/non-draft intent, title/body readiness, and clean boundary diffs.

Use dry run first when the stack was recently restacked, squashed, or reparented. Prefer non-interactive metadata flags (`--fill` or explicit title/body) rather than allowing prompts. After submission, collect PR URLs and verify head/base refs and intended stack order.

### sync-stack

Use only when the user wants to refresh from remote trunk before continuing stack work. Treat remote sync as network/state mutation; be conservative when local changes are in progress. Re-verify stack order and boundaries afterward, especially if merged branches were deleted or a restack occurred.

## Pre/post verification expectations

Before any mutation:

- know the current branch, stack order, PR mapping, and dirty-worktree state
- identify the exact branch range affected
- verify relevant diff/log boundaries locally
- confirm user intent for stateful, network, or history-shaping operations

After any mutation:

- re-check `git status`
- re-run `git-spice log long`
- re-run affected boundary diffs/logs
- verify PR head/base refs when PRs exist or were updated
- stop if branch order, scope, or worktree cleanliness no longer matches expectations

## Response contract

When using this skill, reply with:

- chosen mode and why
- detected stack order and PR mapping
- tracked/untracked branch status
- cleanliness and mutation safety
- actions taken or exact next check/mutation
- blockers or confirmations needed before track, reparent, restack, squash, sync, submit, auth, force, or destructive operations
- validation performed and what it proves or does not prove
