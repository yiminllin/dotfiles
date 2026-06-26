---
name: pr-description-chain-writer
description: Generate public, reviewer-friendly PR descriptions for chained/stacked GitHub PRs in FlightSystems by reading each PR's commits/files and reusing a style reference PR body. Use when asked to draft PR descriptions for a PR chain, draft local git-spice stack PR bodies before PRs exist, replicate a previous chain's format, or bulk-generate chain-aware PR bodies from PR numbers.
---

# Pr Description Chain Writer

## Overview

Generate each public GitHub PR body for an ordered PR chain or a local git-spice stack whose PRs may not exist yet. The body is authored as the user's reviewer-facing PR description, not a private inspection guide. Reuse section structure and tone from a style reference PR while honoring global `coding_style.pr_descriptions` from `user-profile.yaml`: stacked PRs should keep `Reason for Change` identical across the chain, place PR-specific details in `Description of Change`, use diagrams/tables/before-after comparisons when they improve clarity, keep the shape flexible rather than forced, prefer exact verification commands/links over vague CI claims, and include `PR Tree` by default for multi-PR stacks.

## Mode and Shared PR context packet

This skill is **public description mode**. Before finalizing text, build or reuse a compact PR context packet with:

- repo, PR number or local branch placeholder, URL if available, base/head, and whether the diff is against a stack parent or the repo base
- ordered stack/PR tree, current PR marker, and known Jira/context links
- style reference source and repository template sections
- per-PR change summary, generated/mechanical files, and reviewer-relevant anchors
- verification evidence already run, plus explicit not-run reasons when evidence is unavailable

Do not include private inspection content in public PR bodies. Forbidden in public PR bodies: emoji, private TODOs, deep/skim labels, suggested review comments, unresolved inspection questions, unverifiable claims, invented links, local-only paths as public evidence unless explicitly useful, or long self-review notes. If the user asks for reviewer inspection, local comments, or deep/skim guidance, use `pr-human-review-guide` instead.

## Workflow

### 1. Collect inputs

- Collect ordered PR numbers in chain order.
- For local stacks before PRs exist, collect the current git-spice stack from the repo checkout instead of asking for PR numbers.
- Default to `ZiplineTeam/FlightSystems` unless user specifies another repo.
- Prefer using a style reference PR with a high-quality body in the same chain.

For local git-spice stacks, build the packet/draft context before writing final text:

```bash
python3 "$HOME/.config/opencode/scripts/opencode_pr_stack_packet.py" packet --from-git-spice --format markdown
python3 "$HOME/.config/opencode/scripts/opencode_pr_stack_packet.py" draft --from-git-spice --criticality todo --format markdown
```

The local mode is read-only, does not require `gh`, uses branch placeholders in the PR Tree until PR numbers exist, and warns when drafts are based only on committed branch diffs because the worktree is dirty.

### 2. Lock explicit overrides before drafting, regenerating, or posting

Before running the generator, regenerating text, or posting bodies, capture the user's locked overrides from the request, active plan/artifact, and current conversation. Reuse explicit overrides without asking again; ask only when a required posting decision is missing or conflicts with evidence.

Lock these items when present:

- chain-level `Reason for Change` wording and context links; keep this wording identical across the chain, with PR-specific details only in `Description of Change`
- requested title tags and title conventions, including `[DNL]`, `[FSW-#####]`, `[Phoenix]`, and explicit capitalization
- `Criticality of Change` and `Release Notes` checklist checked states for each PR
- diagram/table preference and any requested description style
- per-PR emphasis, such as which mechanism, files, reviewer concern, or risk each PR should highlight
- verification evidence, including exact commands, Baraza/S3/GHA links, result labels, and explicit not-run reasons

### 3. Generate draft bodies

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

### 4. Review generated content before posting

- Read `references/style-notes.md` and keep template order/shape consistent.
- Do a title preflight before writing or posting:
  - Preserve any capitalization the user explicitly requested.
  - When drafting from commits, preserve commit title capitalization/style unless the user asks for a rewrite.
  - For ticketed Phoenix work, use `[FSW-#####] [Phoenix] ...`.
  - For throwaway/test PRs, add `[DNL]` when the user asks for that marker.
  - Ensure commit-derived PR titles or wording still follow requested `[FSW-#####] [Phoenix] ...` and `[DNL]` conventions.
- Tighten the generated reason paragraph so it states the concrete reviewer-visible problem and the mechanism/root cause changed in this PR.
- Keep `Description of Change` concise, plain-language, and layered around the feature being added: feature/mechanism first, file inventory second. Under `In particular:`, prefer conceptual area bullets with semantic labels and nested file details when that improves skimmability, for example `**Config source of truth**`, `**Physics plumbing**`, `**Gen2 tether-guide geometry**`, and `**Contact behavior**`. Use the hybrid shape as a useful default, reduce local jargon, and use diagrams/tables only when they make the review easier. Include short code or pseudocode snippets only when they clarify an API, struct, or flow. Summarize generated, mechanical, or bulk churn as one clear bullet/table row instead of listing repetitive file edits.
- For chains, keep the chain-level reason paragraph/context identical across PRs and keep `PR Tree` by default; only omit it when the user asks or it is clearly noise for reviewers.
- If you include `PR Tree`, keep the ordering exactly aligned to the chain, use PR numbers only such as `- #123`, do not include PR titles or markdown links, and keep `◀` on the current PR.
- When a Jira ticket is known, add `Jira Ticket: [FSW-XXXXX](https://flyzipline.atlassian.net/browse/FSW-XXXXX)` directly below the `PR Tree` block; use the ticket most relevant to each PR, even when multiple PRs share a ticket.
- For non-trivial PRs, optionally add `### Map for Reviewers` under `Description of Change`. Skip it for tiny PRs. Use this public shape instead of dense reviewer-guide tables:
  - `**Suggested route**`: numbered 1-3 semantic areas to inspect.
  - `**Key checkpoints**`: concise bullets for the main correctness, config, API, or frame points.
  - `**Context anchors**`: concise bullets for parent/child PRs, Jira/design/Slack context, key evidence, or validator follow-up.
- Optionally add `### Watchouts` only for real risk or follow-up. Skip it when there is no meaningful risk. Keep compact bullets shaped as `**Risk**: ...`, `**Mitigation**: ...`, and `**Follow-up**: ...`.
- Both sections are optional; skip `Map for Reviewers` for tiny PRs and skip `Watchouts` when there is no real risk or follow-up. Keep them factual and public-safe. Do not include emoji, deep/skim labels, suggested comments, private TODOs, or unresolved inspection questions in public PR bodies.
- Preserve the repository template checkbox blocks for `Criticality of Change` and `Release Notes`; do not collapse them to prose such as `L3 Nonfunctional`. Use the existing repo checklist blocks when known, or copy/preserve the exact checklist shape from the current PR template or style reference. Before finalizing, verify the checked criticality and release-notes state reflect reality for each PR.
- Finalize `Verification` as non-empty checked evidence bullets, not raw generated text: use `- [x] Manual Test [Baraza](...) [S3](...)` or another short result label; multiple tests get multiple `- [x]` bullets. If verification was intentionally not run, include a short explicit not-run reason instead of leaving the section blank. Use fenced `bash` only for real commands that were run or are the evidence. Never leave TODOs, empty query results, or template placeholders.
- Treat Baraza/S3/GHA links as evidence, not decoration: prefer Baraza and `[S3](...)` links over Aspect links or local paths when available, but never invent links. Upload or link logs only when the user requested/authorized it; otherwise omit unavailable links or state local-only evidence.
- For `Manual Test`, keep it concise: name the Phoenix scenario or workflow, add environment or mode only when it matters, summarize the result briefly, and include links when useful.
- A verification bullet may be followed by a fenced `bash` command block when the exact command is useful; include command details only when they are real verification evidence.

### 5. Apply generated body to each PR (optional)

```bash
gh pr edit 48825 --repo ZiplineTeam/FlightSystems --body-file /tmp/pr-chain-bodies/pr_48825.md
```

Repeat for each PR in the chain.

When reporting results:

- Draft/local mode: say `draft only` and name the local files or stdout output; no GitHub artifact was updated.
- Edit/posting mode: for each PR, say `updated` or `not updated` with exact evidence: PR URL, the `gh pr edit ...` command that succeeded, or the blocker/reason no update happened.

## Script Output Contract

For each PR, generate:

- Repository template sections in canonical order.
- Shared reason paragraph, optional context link, and default-on `PR Tree` for chains.
- Human-readable `Description of Change`, flexible in final shape even though the script renders hybrid, prose-only, or bullets-only drafts.
- More detailed nested bullets with reviewer-meaningful section labels where the diff supports them.
- Optional `### Map for Reviewers` and `### Watchouts` sections only when they add reviewer value.
- Optional illustrative snippets when requested.
- Preserved repository-template checkbox blocks for `Criticality of Change` and `Release Notes`, with checked states verified during final review, plus concise exact verification evidence after manual review.

Write files to:

- `/tmp/pr-chain-bodies/pr_<PR_NUMBER>.md` (or chosen `--write-dir`).

## Resources

- `scripts/generate_pr_chain_descriptions.py`: main generator.
- `references/style-notes.md`: chain style cues to preserve.
