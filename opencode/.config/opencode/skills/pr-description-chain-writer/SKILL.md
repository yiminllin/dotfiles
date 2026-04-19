---
name: pr-description-chain-writer
description: Generate consistent PR descriptions for chained/stacked GitHub PRs in FlightSystems by reading each PR's commits/files and reusing a style reference PR body. Use when asked to draft PR descriptions for a PR chain, replicate a previous chain's format, or bulk-generate chain-aware PR bodies from a list of PR numbers.
---

# Pr Description Chain Writer

## Overview

Generate draft PR bodies for an ordered PR chain. Reuse section structure and tone from a style reference PR, but default toward concrete `Reason for Change` paragraphs, a dock-in-loop-shaped hybrid `Description of Change` (short prose lead plus nested bullets), baked-in `L3 Nonfunctional` / no-release-notes defaults, a concise checklist-shaped `Verification` block that prefers `Unit Test`, `Manual Test`, or `CI` based on the actual evidence, and `PR Tree` included by default for multi-PR stacks.

## Workflow

### 1. Collect inputs

- Collect ordered PR numbers in chain order.
- Default to `ZiplineTeam/FlightSystems` unless user specifies another repo.
- Prefer using a style reference PR with a high-quality body in the same chain.

### 2. Generate draft bodies

Use the generator script:

```bash
python3 .opencode/skills/pr-description-chain-writer/scripts/generate_pr_chain_descriptions.py \
  48761 48824 48825 48784 48833 \
  --repo ZiplineTeam/FlightSystems \
  --style-pr 48761 \
  --context-link "Context: https://github.com/ZiplineTeam/FlightSystems/issues/123" \
  --write-dir /tmp/pr-chain-bodies \
  --stdout
```

Important options:

- `--reason "<text>"`: override the reason paragraph for the chain; prefer concrete symptom/problem plus mechanism/root-cause wording.
- `--context-link "<markdown-or-url>"`: append an optional context line in `Reason for Change`.
- `--style-pr <pr>`: force a specific PR as style source.
- `--write-dir <dir>`: write one file per PR as `pr_<number>.md`.
- `--omit-pr-tree`: suppress the default `PR Tree` block for a multi-PR chain.
- `--include-pr-tree`: backward-compatible force-include flag; mainly useful for single-PR generation or explicitness.
- `--description-style hybrid|prose|bullets`: choose description rendering style; default is `hybrid`.
- `--tiny`: emit a shorter description for very small PRs or long chains.
- `--include-snippets`: include short code/pseudocode snippets for illustration.
- `--max-snippets <n>` and `--snippet-lines <n>`: control snippet count and length.
- `--detailed`: disable compact mode and keep more of the nested breakdown.
- `--max-sections <n>` and `--max-sub-bullets <n>`: tune compact output length.

### 3. Review generated content before posting

- Read `references/style-notes.md` and keep template order/shape consistent.
- Tighten the generated reason paragraph so it states the concrete reviewer-visible problem and the mechanism/root cause changed in this PR.
- Default to the hybrid `Description of Change` shape: short intro prose, then detailed nested bullets with semantically useful section labels.
- Keep `PR Tree` by default for chains; only omit it when the user asks or it is clearly noise for reviewers.
- If you include `PR Tree`, keep the ordering exactly aligned to the chain and keep `◀` on the current PR.
- Ensure the baked-in `L3 Nonfunctional` / no-release-notes defaults still reflect reality for each PR.
- Keep `Verification` shaped like a small checklist of `Unit Test`, `Manual Test`, and `CI`, analogous to `Criticality of Change`; check the item that best matches the actual proof unless more than one is clearly warranted.
- For `Manual Test`, keep it concise: name the Phoenix scenario or workflow, add environment or mode only when it matters, summarize the result briefly, and include links when useful.
- Use an indented fenced `bash` block only when command details are the real verification evidence.

### 4. Apply generated body to each PR (optional)

```bash
gh pr edit 48825 --repo ZiplineTeam/FlightSystems --body-file /tmp/pr-chain-bodies/pr_48825.md
```

Repeat for each PR in the chain.

## Script Output Contract

For each PR, generate:

- Repository template sections in canonical order.
- Reason paragraph, optional context link, and default-on `PR Tree` for chains.
- Human-readable `Description of Change`, hybrid by default with prose-only and bullets-only modes still available.
- More detailed nested bullets with reviewer-meaningful section labels where the diff supports them.
- Optional illustrative snippets when requested.
- Baked-in `L3 Nonfunctional` and unchecked release-notes defaults, plus a concise verification checklist covering `Unit Test`, `Manual Test`, and `CI`.

Write files to:

- `/tmp/pr-chain-bodies/pr_<PR_NUMBER>.md` (or chosen `--write-dir`).

## Resources

- `scripts/generate_pr_chain_descriptions.py`: main generator.
- `references/style-notes.md`: chain style cues to preserve.
