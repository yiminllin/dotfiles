---
name: pr-description-chain-writer
description: Generate consistent PR descriptions for chained/stacked GitHub PRs in FlightSystems by reading each PR's commits/files and reusing a style reference PR body. Use when asked to draft PR descriptions for a PR chain, replicate a previous chain's format, or bulk-generate chain-aware PR bodies from a list of PR numbers.
---

# Pr Description Chain Writer

## Overview

Generate draft PR bodies for an ordered PR chain. Reuse section structure and tone from a style reference PR while honoring global `coding_style.pr_descriptions` from `user-profile.yaml`: stacked PRs should keep `Reason for Change` identical across the chain, place PR-specific details in `Description of Change`, use diagrams/tables/before-after comparisons when they improve clarity, keep the shape flexible rather than forced, prefer exact verification commands/links over vague CI claims, and include `PR Tree` by default for multi-PR stacks.

## Workflow

### 1. Collect inputs

- Collect ordered PR numbers in chain order.
- Default to `ZiplineTeam/FlightSystems` unless user specifies another repo.
- Prefer using a style reference PR with a high-quality body in the same chain.

### 2. Generate draft bodies

Use the generator script from the loaded skill directory. Set `SKILL_DIR` to that directory when needed; for the stowed global skill this is usually `$HOME/.config/opencode/skills/pr-description-chain-writer`.

```bash
SKILL_DIR="${SKILL_DIR:-$HOME/.config/opencode/skills/pr-description-chain-writer}"
python3 "$SKILL_DIR/scripts/generate_pr_chain_descriptions.py" \
  48761 48824 48825 48784 48833 \
  --repo ZiplineTeam/FlightSystems \
  --style-pr 48761 \
  --context-link "Context: https://github.com/ZiplineTeam/FlightSystems/issues/123" \
  --write-dir /tmp/pr-chain-bodies \
  --stdout
```

Important options:

- `--reason "<text>"`: override the shared reason paragraph for the whole chain; for stacked PRs, keep this text identical across PRs and put per-PR specifics in `Description of Change`.
- `--context-link "<markdown-or-url>"`: append an optional context line in `Reason for Change`.
- `--style-pr <pr>`: force a specific PR as style source.
- `--write-dir <dir>`: write one file per PR as `pr_<number>.md`.
- `--omit-pr-tree`: suppress the default `PR Tree` block for a multi-PR chain.
- `--include-pr-tree`: backward-compatible force-include flag; mainly useful for single-PR generation or explicitness.
- `--description-style hybrid|prose|bullets`: choose the script-rendered description style; default is `hybrid`. Manually rewrite to a diagram or table when that better explains the change.
- `--tiny`: emit a shorter description for very small PRs or long chains.
- `--include-snippets`: include short code/pseudocode snippets for illustration.
- `--max-snippets <n>` and `--snippet-lines <n>`: control snippet count and length.
- `--detailed`: disable compact mode and keep more of the nested breakdown.
- `--max-sections <n>` and `--max-sub-bullets <n>`: tune compact output length.

### 3. Review generated content before posting

- Read `references/style-notes.md` and keep template order/shape consistent.
- Tighten the generated reason paragraph so it states the concrete reviewer-visible problem and the mechanism/root cause changed in this PR.
- Use the hybrid `Description of Change` shape as a useful default, not a hard requirement; adapt to the change and favor clarity.
- For chains, keep the chain-level reason paragraph/context identical across PRs and keep `PR Tree` by default; only omit it when the user asks or it is clearly noise for reviewers.
- If you include `PR Tree`, keep the ordering exactly aligned to the chain and keep `◀` on the current PR.
- Ensure the baked-in `L3 Nonfunctional` / no-release-notes defaults still reflect reality for each PR.
- Keep `Verification` concise and evidence-based; prefer exact commands, Baraza/GHA links, run tables, or concrete manual results over vague `CI` claims. Never return raw generated verification placeholders as final PR text.
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
- Shared reason paragraph, optional context link, and default-on `PR Tree` for chains.
- Human-readable `Description of Change`, flexible in final shape even though the script renders hybrid, prose-only, or bullets-only drafts.
- More detailed nested bullets with reviewer-meaningful section labels where the diff supports them.
- Optional illustrative snippets when requested.
- Baked-in `L3 Nonfunctional` and unchecked release-notes defaults where appropriate, plus concise exact verification evidence after manual review.

Write files to:

- `/tmp/pr-chain-bodies/pr_<PR_NUMBER>.md` (or chosen `--write-dir`).

## Resources

- `scripts/generate_pr_chain_descriptions.py`: main generator.
- `references/style-notes.md`: chain style cues to preserve.
