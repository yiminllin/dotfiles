---
name: pr-description-chain-writer
description: Generate consistent PR descriptions for chained/stacked GitHub PRs in FlightSystems by reading each PR's commits/files and reusing a style reference PR body. Use when asked to draft PR descriptions for a PR chain, replicate a previous chain's format, or bulk-generate `PR Tree`-aware PR bodies from a list of PR numbers.
---

# Pr Description Chain Writer

## Overview

Generate draft PR bodies for an ordered PR chain. Reuse section structure and tone from a style reference PR, then emit chain-aware `PR Tree` markers and compact, human-readable nested bullets in `Description of Change`.

## Workflow

### 1. Collect inputs

- Collect ordered PR numbers in chain order.
- Default to `ZiplineTeam/FlightSystems` unless user specifies another repo.
- Prefer using a style reference PR with a high-quality body in the same chain.

### 2. Generate draft bodies

Use the generator script:

```bash
python3 .codex/skills/pr-description-chain-writer/scripts/generate_pr_chain_descriptions.py \
  48761 48824 48825 48784 48833 \
  --repo ZiplineTeam/FlightSystems \
  --style-pr 48761 \
  --write-dir /tmp/pr-chain-bodies \
  --stdout
```

Important options:

- `--reason "<text>"`: override shared reason paragraph for the chain.
- `--style-pr <pr>`: force a specific PR as style source.
- `--write-dir <dir>`: write one file per PR as `pr_<number>.md`.
- `--include-snippets`: include short code/pseudocode snippets for illustration.
- `--max-snippets <n>` and `--snippet-lines <n>`: control snippet count and length.
- Default output is compact human-readable bullets.
- `--detailed`: emit full detailed sections.
- `--max-sections <n>` and `--max-sub-bullets <n>`: tune compact output length.

### 3. Review generated content before posting

- Read `references/style-notes.md` and keep template order/shape consistent.
- Tighten `Description of Change` bullets where domain semantics need human wording.
- Keep `PR Tree` ordering exactly aligned to the chain; keep `◀` on current PR.
- Ensure criticality and verification checkboxes reflect reality for each PR.

### 4. Apply generated body to each PR (optional)

```bash
gh pr edit 48825 --repo ZiplineTeam/FlightSystems --body-file /tmp/pr-chain-bodies/pr_48825.md
```

Repeat for each PR in the chain.

## Script Output Contract

For each PR, generate:

- Repository template sections in canonical order.
- Shared reason paragraph + `PR Tree`.
- Human-readable `Description of Change` with nested bullet groups by change area (scenario/config/routing/validation/tests/CI as applicable).
- Optional illustrative snippets when requested.
- Criticality, verification, and release-notes blocks from style PR (or safe defaults if missing).

Write files to:

- `/tmp/pr-chain-bodies/pr_<PR_NUMBER>.md` (or chosen `--write-dir`).

## Resources

- `scripts/generate_pr_chain_descriptions.py`: main generator.
- `references/style-notes.md`: chain style cues to preserve.
