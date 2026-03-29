---
name: stacked-pr-workflow
description: Inspect, track, reparent, restack, squash, and submit stacked PR branches conservatively, especially with git-spice. Use when the user wants help keeping PR boundaries clean, restacking in order, or resubmitting a stack.
---

# Stacked PR Workflow

## Overview

Manage a stacked PR chain conservatively:

- inspect the current tracked stack
- track manually created branches when needed
- verify each PR boundary with local diffs and logs
- reparent branches when the stack shape is wrong
- restack the stack cleanly
- optionally squash branches to one commit each
- submit or update one PR or a full upstack

This skill is about stack structure and submission discipline. It is not the primary skill for PR-body writing or review-comment triage.

## Related skills

- If the user wants PR descriptions, use `pr-description-chain-writer`.
- If the user wants actionable review comments handled, use `pr-address-comments`.

## Guardrails

- Ensure `git-spice` is available before proceeding. If it is not installed, stop and ask whether the user wants a plain-git fallback.
- Do not mutate a stack until the local worktree is understood.
- Stop if unrelated local changes are mixed in; ask whether to stash, split, or commit them first.
- Treat tracking, reparenting, restack, squash, and submit operations as stateful history-shaping actions.
- Prefer canonical `git-spice` commands in instructions; local aliases like `gs`, `gsl`, `gsur`, and `gsus` are conveniences, not the canonical interface.
- Do not rely on GitHub UI alone; verify PR boundaries locally with `git diff`, `git log`, and `git-spice log long`.
- When addressing stacked review feedback, fix the lowest affected PR first.
- After each mutation, re-check branch order, diff boundaries, and PR mapping before continuing.
- Keep each PR reviewer-friendly; avoid unrelated cleanup that blurs boundaries.
- Avoid interactive git-spice prompts and editors in autonomous runs. Supply explicit flags when possible; otherwise stop and ask instead of hanging on a prompt.
- Do not use force push or `--no-verify` unless the user explicitly asks for it.
- Prefer the least invasive git-spice command that matches the intended change.

## Useful local shorthand notes

If the local fish config is in effect, these abbreviations may exist:

- `gs` = `git-spice`
- `gsl` = `git-spice log long`
- `gsu` = `git-spice up`
- `gsd` = `git-spice down`
- `gsm` = `git-spice trunk`
- `gsur` = `git-spice upstack restack`
- `gsus` = `git-spice upstack submit`
- `gsrc` = `git-spice rebase continue`
- `gsra` = `git-spice rebase abort`
- `gsrs` = `git-spice repo sync`

Use canonical commands in responses unless the user explicitly prefers the shorthands.

## Modes

1. `inspect-stack`
2. `track-branches`
3. `verify-boundaries`
4. `reparent-stack`
5. `restack-stack`
6. `squash-stack`
7. `submit-stack`
8. `sync-stack`

If a request spans multiple modes, start with the safest read-only mode first.

## 1) inspect-stack

Start by inspecting local and remote state:

```bash
git status
git branch --show-current
git-spice log long
gh pr view --json number,url,title,headRefName,baseRefName,isDraft,reviewDecision
```

Useful variants:

```bash
git-spice log long --all
git-spice log long --json
```

Notes:
- `git-spice log long` is the primary stack-aware inspection view.
- It shows branches and commits for the current stack by default.
- Use `--all` when the current branch is not enough to understand the broader tracked topology.
- Use `--json` when you want machine-readable stack metadata.

Summarize:
- stack order
- whether branches are tracked
- which branches already have PRs
- whether the worktree is safe to mutate
- the likely next operation

## 2) track-branches

Use this when branches already exist but are not yet tracked by git-spice.

Track one branch:

```bash
git-spice branch track <branch>
```

If base inference is wrong or ambiguous:

```bash
git-spice branch track <branch> --base <base-branch>
```

If the user manually created a whole stack and you are near the top, prefer:

```bash
git-spice downstack track <branch>
```

Notes:
- `branch track` is best for one branch.
- `downstack track` is better for an already-created untracked stack below the current or specified branch.

After tracking, re-run:

```bash
git-spice log long
```

and confirm the stack shape looks right before any restack or submit step.

## 3) verify-boundaries

For each adjacent pair in the stack:

```bash
git diff <base>...<pr1>
git diff <pr1>...<pr2>
git log --oneline --decorate <base>..<branch>
git-spice log long
```

Check that:
- each PR contains only its intended scope
- no higher-PR changes leaked into a lower PR
- there is no hidden dependency on uncommitted local changes
- if one-commit PRs are desired, whether each branch is already squashed

Use plain `git diff` as the source of truth for reviewer-visible branch boundaries.

## 4) reparent-stack

Use this when the stack shape is wrong, not merely stale.

### Move one branch onto a different base, leaving its upstack alone

```bash
git-spice branch onto <new-base> --branch <branch>
```

Use this when only one branch should move and the branches above it should stay attached to the original structure.

### Move a branch and everything above it onto a different base

```bash
git-spice upstack onto <new-base> --branch <branch>
```

Use this when the branch and its upstack all belong on a different parent.

### Edit stack order directly

```bash
git-spice stack edit --branch <branch>
```

Use this when the branch ordering itself is wrong and needs explicit manual reshaping.

Notes:
- `git-spice stack edit` opens an editor, so treat it as a manual fallback rather than an autonomous default.
- Prefer `branch onto` or `upstack onto` when the intended change is simple and clear.
- Prefer `stack edit` when multiple branch relationships are wrong and a one-shot reorder is clearer.
- After any reparenting, re-run `git-spice log long` and verify boundaries again.

## 5) restack-stack

Use restack when branch relationships are correct but history needs to be rebased cleanly onto their tracked bases.

### Restack the whole current stack

```bash
git-spice stack restack
```

Useful variant:

```bash
git-spice stack restack --branch <branch>
```

### Restack only a branch and its upstack

```bash
git-spice upstack restack
```

Useful variants:

```bash
git-spice upstack restack --branch <branch>
git-spice upstack restack --branch <branch> --skip-start
```

Guidance:
- Prefer `stack restack` for “clean up this whole stack”.
- Prefer `upstack restack` for “start here and restack this branch plus higher branches”.
- Use `--skip-start` only when the starting branch is already correct and only higher branches need movement.

After each restack:
- re-check `git status`
- re-run `git-spice log long`
- re-run boundary diffs
- confirm the next branch still bases on the intended parent

If a rebase stops on conflicts, use the normal git-spice continuation flow:

```bash
git-spice rebase continue
# or
git-spice rebase abort
```

## 6) squash-stack

Only do this if the user explicitly asked to squash or wants one-commit PRs.

Use git-spice's branch squash flow:

```bash
git-spice branch squash --branch <branch> -m "<commit message>"
```

Or, from the branch itself:

```bash
git-spice branch squash -m "<commit message>"
```

Useful variant:

```bash
git-spice branch squash --branch <branch> --no-edit
```

Notes:
- `git-spice branch squash` squashes all commits in the branch into one commit.
- It already restacks upstack branches automatically.
- Squash one branch at a time, usually in stack order from lowest to highest when preparing a clean stacked submission.
- In autonomous use, prefer `-m` or `--no-edit` to avoid launching an editor.

After each squash:
- re-check `git status`
- re-run `git-spice log long`
- re-check `git log --oneline`
- re-run boundary diffs to confirm each PR still has the intended scope

Do not use `--no-verify` unless the user explicitly asks for it.

## 7) submit-stack

Choose the narrowest submit command that matches the task.

### Submit or update one branch only

```bash
git-spice branch submit --branch <branch>
```

Useful safe first pass:

```bash
git-spice branch submit --branch <branch> --dry-run
```

Useful non-interactive variants:

```bash
git-spice branch submit --branch <branch> --fill --draft
git-spice branch submit --branch <branch> --title "<title>" --body "<body>" --draft
```

### Submit or update a branch and everything above it

```bash
git-spice upstack submit
```

Useful safe first pass:

```bash
git-spice upstack submit --dry-run
```

Useful variants:

```bash
git-spice upstack submit --branch <branch>
git-spice upstack submit --branch <branch> --fill --draft
```

Guidance:
- Prefer `branch submit` when only one PR should be created or updated.
- Prefer `upstack submit` when the user wants the current branch and all higher branches updated together.
- Use `--dry-run` first when the stack was recently restacked, squashed, or reparented.
- In autonomous use, prefer `--fill` or explicit `--title` / `--body` to avoid metadata prompts.
- Avoid `--force` and `--no-verify` unless the user explicitly requests them.

Before submitting:
- confirm branch order
- confirm draft vs non-draft intent
- confirm PR body/title updates are ready
- confirm the correct starting branch

After submitting:
- collect PR URLs
- verify head/base refs on each PR
- confirm GitHub shows the intended stack order

## 8) sync-stack

Use this when the user wants to refresh from remote trunk before continuing stack work.

```bash
git-spice repo sync
```

Useful variant:

```bash
git-spice repo sync --restack
```

Notes:
- This pulls the latest changes from the remote.
- Merged branches may be deleted after syncing.
- `--restack` is useful when the user explicitly wants the current stack refreshed against the latest remote state in one step.

Use this conservatively when there are local in-progress changes.

## Navigation helpers

These are convenience commands, not primary workflow steps:

```bash
git-spice up
git-spice down
git-spice trunk
```

Use them to move around the stack quickly during inspection or after mutations.

## Response pattern

When using this skill, reply with:
- chosen mode
- detected stack order
- whether branches are tracked
- cleanliness / mutation safety
- exact next check or mutation
- any confirmation needed before track, reparent, restack, squash, submit, or sync
