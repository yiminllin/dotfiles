# Stacked PR command recipes

Lazy-load this reference from `SKILL.md` when exact `git-spice` syntax, local shorthand notes, rare branch surgery, or longer examples are needed. Keep routing, safety, and output decisions anchored in the main skill file.

## Local shorthand notes

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

Use canonical commands in responses unless the user explicitly prefers shorthands.

## Inspect stack

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

`git-spice log long` is the primary stack-aware inspection view. Use `--all` for broader tracked topology and `--json` when machine-readable stack metadata is helpful.

## Track branches

Create and track a new branch:

```bash
git switch -c <branch>
git-spice branch track <branch> --base <base-branch>
```

Use `git checkout -b <branch>` instead of `git switch -c <branch>` when that better matches the local Git version or repo habit.

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

After tracking:

```bash
git-spice log long
```

## Verify boundaries

```bash
git diff <base>...<pr1>
git diff <pr1>...<pr2>
git log --oneline --decorate <base>..<branch>
git-spice log long
```

Use plain `git diff` as the source of truth for reviewer-visible branch boundaries.

## Reparent stack

Move one branch onto a different base, leaving its upstack alone:

```bash
git-spice branch onto <new-base> --branch <branch>
```

Move a branch and everything above it onto a different base:

```bash
git-spice upstack onto <new-base> --branch <branch>
```

Edit stack order directly:

```bash
git-spice stack edit --branch <branch>
```

`git-spice stack edit` opens an editor, so treat it as a manual fallback rather than an autonomous default. Prefer `branch onto` or `upstack onto` when the intended change is simple and clear.

## Restack stack

Restack the whole current stack:

```bash
git-spice stack restack
```

Useful variant:

```bash
git-spice stack restack --branch <branch>
```

Restack only a branch and its upstack:

```bash
git-spice upstack restack
```

Useful variants:

```bash
git-spice upstack restack --branch <branch>
git-spice upstack restack --branch <branch> --skip-start
```

If a rebase stops on conflicts:

```bash
git-spice rebase continue
git-spice rebase abort
```

## Squash stack

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

`git-spice branch squash` squashes all commits in the branch into one commit and restacks upstack branches automatically. Squash one branch at a time, usually lowest to highest when preparing a clean stacked submission.

## Submit stack

Submit or update one branch only:

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

Submit or update a branch and everything above it:

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

Prefer `branch submit` for one PR and `upstack submit` for the current branch plus higher branches.

## Sync stack

```bash
git-spice repo sync
```

Useful variant:

```bash
git-spice repo sync --restack
```

`repo sync` pulls the latest remote changes. Merged branches may be deleted after syncing. Use `--restack` only when the user explicitly wants the current stack refreshed against the latest remote state in one step.

## Navigation helpers

These are convenience commands, not primary workflow steps:

```bash
git-spice up
git-spice down
git-spice trunk
```

Use them to move around the stack quickly during inspection or after mutations.
