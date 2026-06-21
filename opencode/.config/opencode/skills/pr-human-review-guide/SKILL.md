---
name: pr-human-review-guide
description: Review or refresh a private GitHub PR/Diffview guide for a human reviewer or author: recommend file reading order, summarize structure, and draft prioritized local comments, questions, TODOs, curiosity notes, and validation gaps with file/line anchors. Use when the user provides a PR number/URL, prdv/Diffview input, local branch/diff range, asks for review order or human-review guidance, or provides an existing guide artifact to update.
---

# PR Human Review Guide

## Overview

Given a PR number, PR URL, `prdv`/Diffview prompt, saved guide path, or local branch/diff range, produce a private guide that helps a human reviewer or author inspect the change efficiently and decide what comments/questions/TODOs to leave.

This skill is for **private/local inspection mode**, not a public PR description and not submitting a GitHub review. Do not post comments, approve, request changes, resolve threads, edit PR bodies, or create public-facing review text unless the user explicitly asks for that in a later step. If the user asks for a public GitHub PR body, use `pr-description-chain-writer` instead.

## Shared PR context packet

Build or reuse a compact packet before writing the guide:

- repo, PR number/URL when available, local branch or diff range, base/head, and exact diff boundary
- whether the input came from `prdv`, an already-open Diffview session, a saved guide refresh, or manual local self-review
- PR intent, touched subsystems, file list, generated/mechanical churn, and stack position if relevant
- comments/checks/verification evidence already observed, plus gaps that need local review

Keep this packet private. It may support detailed review order, deep/skim labels, questions, TODOs, suggested local comments, and verification gaps, but it should not be copied into a public PR body as-is.

## Primary output

The default output should be Diffview-centric and include:

1. `## TL;DR`: short private reviewer guidance with the main review path and highest-risk unknowns.
2. `## High-level summary`: conceptual layers of the change before file details.
3. Optional `## Review goal`: include only when a specific reviewer intent or author self-review goal would focus the pass.
4. PR-level context: title/URL/base/head, one-paragraph intent summary, risk summary, and validation focus.
5. `## Recommended inspection order`: Diffview/prdv-friendly file review order, using exact file paths as shown in the PR diff when practical.
6. `## File map`: a compact file or area table. For huge PRs, group by directory/area with representative files or globs instead of listing every file.
7. Per-file sections organized in the recommended order.
8. For each file: what the diff is doing, why it matters, what to inspect in Diffview, and review depth (`read carefully`/`deep`, `skim`, or `optional/generated`).
9. Suggested local review comments/questions/TODOs nested under the relevant file, phrased so they can be copied into local Diffview comments or used for author self-review.
10. `## Questions` table and validation/coverage notes only after the file-by-file guide.

Prefer high-signal comments over exhaustive commentary.

Final reports are `draft only` by default: state that no GitHub review, comment, approval, request-changes action, or thread resolution was updated. If the user later explicitly asks for a GitHub-facing mutation, report each intended artifact as `updated` or `not updated` with exact evidence such as the PR/comment/thread URL, the `gh` command that succeeded, or the blocker/reason no update happened.

For complex or unfamiliar subsystems, or when the user asks for explanation, begin with toddler terminology and a small diagram before the normal review order/comments. Keep simple PRs concise.

## Guide artifact refresh mode

When the prompt provides a target guide path, existing guide path, or asks to update/refresh a saved guide:

- If the existing guide file exists and is readable, read it before reviewing the current PR state.
- Treat the existing guide as prior context, not truth. Preserve still-relevant observations, remove stale ones, and add new findings/questions from the current PR state.
- Keep the refreshed output in the same primary output structure below so it can replace the previous artifact cleanly.
- Mention materially stale or removed prior observations only when that helps the human reviewer; do not include a noisy changelog by default.
- If the guide path is provided, state that the response is intended to be saved there, but do not rely on the shell redirect as proof that it was written.

## Workflow

### 1. Resolve PR context

Accept either:

- a PR number, e.g. `52370`
- a PR URL, e.g. `https://github.com/ZiplineTeam/FlightSystems/pull/52370`
- a `prdv`-generated prompt with PR metadata and a guide artifact path
- a local branch, commit range, or Diffview context for feature self-review before a PR exists

Prefer building PR context once with the deterministic helper when it is available, especially for a PR number or URL:

```sh
python3 "$HOME/.config/opencode/scripts/github_pr_context.py" <pr> --include-comments
```

For the current branch PR, omit `<pr>`. Use `--format markdown` only when a compact human-readable packet is more useful than JSON. For `prdv` prompts, trust the provided metadata as the starting packet and refresh only the missing details needed for the guide. If the helper is unavailable, fall back to direct GitHub CLI commands:

```sh
gh pr view <pr> --json number,url,title,body,author,baseRefName,headRefName,isDraft,mergeStateStatus,reviewDecision,commits,files,additions,deletions
gh pr diff <pr>
```

If useful, inspect comments/checks with:

```sh
gh pr view <pr> --comments
gh pr checks <pr>
```

If `gh` auth fails, stop and ask the user to refresh GitHub auth. Do not attempt interactive auth unless explicitly asked.

For local feature self-review without a PR, use local git diff context only and say which base/ref was inspected. Do not infer GitHub-only metadata or mutate files.

### 2. Establish the review boundary

Before reviewing details, identify:

- PR title and stated intent.
- Base/head refs.
- Whether the PR appears stacked.
- Main touched subsystems.
- Commit grouping if useful.
- Generated, dependency, lockfile, formatting-only, or mechanical churn.

For stacked PRs, make the diff boundary explicit so the user knows whether the review is against the PR base, `develop`, or another stack branch.

If the subsystem is unfamiliar, the change spans several layers, or the user asks for explanation/easy terminology/examples, first explain the moving pieces in toddler terminology plus a small diagram. Then continue with the normal review boundary, file order, suggested comments, and validation notes. Include small examples only when they help the reviewer understand why the suggested reading order makes sense.

### 3. Build a recommended inspection order

Recommend an order based on how a human should review the PR in Diffview or from a `prdv` packet, not alphabetical order. Use exact file paths from the PR diff so the guide can be followed while stepping through Diffview files when practical.

Default order:

1. Public API, config, schema, CLI, or user-facing surface.
2. Architecture or wiring seams.
3. Core behavior / business logic.
4. Error handling, safety checks, compatibility paths.
5. Tests and validation.
6. Build/dependency files.
7. Generated or lockfile-only files.

For each file, label the review depth:

- `read carefully`
- `deep` when the user asks for deep/skim labels
- `skim`
- `optional/generated`

For each non-generated file section, include:

- `What this diff does`: a concise explanation of the change in that file.
- `Inspect in Diffview`: concrete things to verify while looking at that file's diff.
- `Suggested local comments/questions/TODOs`: only high-signal items that could become local Diffview comments or author self-review follow-ups.

Explain briefly why each file appears in that position, especially when one file should be understood before another.

Build a compact `## File map` as a separate orientation aid. For small or medium PRs, a table may list files directly. For huge PRs, do not list every file; group by directory/area and include representative files or directory globs.

### 4. Review the code

Review for:

- correctness
- hidden assumptions
- safety or operational risk
- edge cases
- API/layering fit
- maintainability
- test and validation gaps
- compatibility / migration concerns
- excessive churn or reviewability problems
- global coding-style concerns from `user-profile.yaml`: low-signal tests, speculative guardrails, unnecessary indirection, poor reading order, missing diagrams/docs for complex flow, weak verification, or stale PR descriptions

When working in FlightSystems, be conservative around safety-critical behavior. Separate true behavioral risk from style or preference comments.

### 5. Classify suggested comments

Use these labels:

- `Blocker`: likely correctness/safety issue; reviewer should not approve without resolution.
- `High`: substantial risk or missing validation for important behavior.
- `Medium`: plausible bug, design concern, or maintainability issue worth discussion.
- `Low`: coverage/readability/follow-up suggestion; non-blocking by default.
- `Curiosity`: genuine design/context question, not framed as a requested change.
- `Nit`: small local style/readability issue; omit unless useful.

Keep severity calibrated. Most curiosity/design-shape questions are `Low` or `Curiosity`, not blockers.

For the `## Questions` table, use categories rather than severity: `Clarification`, `Curiosity`, `Follow-up`, `Verification gap`, and `Blocker` when applicable. Columns must be `Category`, `Anchor`, `Question`, and `Why it matters`.

### 6. Anchor comments

For every suggested comment/question, include:

- file path
- line or line range where possible
- concise suggested wording
- why it matters

Do not invent exact line numbers. If the anchor is approximate, say `approx`.

### 7. Output format

Use this Diffview/prdv-friendly structure. `read carefully` may be replaced with `deep` when the user requested deep/skim labels:

```markdown
## TL;DR
- <main review route and highest-risk unknowns>
- <most important validation or follow-up focus>

## High-level summary
<plain-language summary of the conceptual layers changed, such as public API/config, routing/wiring, core behavior, validation, and generated/mechanical churn.>

## Review goal
<optional; include only when a specific reviewer or author self-review goal helps focus the pass>

## PR context
- PR: #<number> — <title>
- URL: <url>
- Base/head: `<base>` ← `<head>`
- Intent: <one-paragraph summary>
- Main risk: <blocker/non-blocker judgment and primary risk>
- Validation focus: <short list>

## Recommended inspection order
1. `path/to/file.rs` — <why read first> [read carefully]
2. `path/to/next_file.rs` — <why next> [skim]

## File map
| Area | Files / globs | Review focus |
| ---- | ------------- | ------------ |
| <area> | `path/to/file.rs` or `path/to/**/*.rs` | <what this area owns> |

## File-by-file Diffview guide

### 1. `path/to/file.rs` [read carefully]
**What this diff does**
- <plain-language explanation of the file's diff>

**Inspect in Diffview**
- <specific behavior, edge case, or API/layering point to verify while viewing this file>

**Suggested local comments/questions**
- **Medium** — `path/to/file.rs:10-20`: <suggested local Diffview comment/question>
  - Why it matters: <risk/context>
  - TODO: <optional local follow-up before posting/submitting review>

### 2. `path/to/next_file.rs` [skim]
**What this diff does**
- <explanation>

**Inspect in Diffview**
- <what to skim for>

**Suggested local comments/questions**
- None.

## Questions
| Category | Anchor | Question | Why it matters |
| -------- | ------ | -------- | -------------- |
| Clarification | `path/a.rs` | <question> | <impact on review/intent> |
| Curiosity | `path/a.rs`, `path/b.rs` | <question> | <design context> |
| Follow-up | `path/c.rs` | <question> | <non-blocking next step> |
| Verification gap | `path/test.rs` | <question> | <coverage confidence> |
| Blocker | `path/d.rs:10` | <question> | <correctness/safety concern> |

## Validation / coverage notes
- <tests observed>
- <gaps or follow-up validation>

## Public PR body suggestions
<optional/private; include only when useful. Suggestions may identify public-body improvements, but do not edit the PR body or present this private inspection guide as public text.>
```

## Guardrails

- Do not post GitHub review comments unless explicitly asked.
- Do not approve, request changes, or submit a review.
- Do not edit PR bodies or turn this guide into a public PR description.
- Do not over-comment. Prefer a short list of comments a human might actually leave.
- Treat coding-style comments as reviewability concerns; keep them low-severity unless they hide correctness or maintenance risk.
- Do not phrase curiosity as a demand.
- Do not review generated or lockfile churn deeply unless it changes behavior, build semantics, or dependencies.
- If the PR is too large to review confidently in one pass, say so and provide a phased review order.
- If a finding depends on uncertain intent, mark it as a question rather than a defect.

## Good default tone

Be concise, evidence-backed, and reviewer-friendly.

Example phrasing:

- `Low — path:line-line: Is this intentionally scenario-global rather than per-domain?`
- `Medium — path:line-line: I would expect coverage for <case> because this is the main new behavior.`
- `Curiosity — path:line-line: Longer term, do you expect this to move into <layer>, or is this meant to stay local?`

Avoid:

- vague comments without anchors
- broad redesign requests without evidence
- pretending machine review is authoritative
- style nits that distract from correctness or review order
- generic PR-review prose that is not actionable while stepping through Diffview files
