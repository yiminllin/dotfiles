---
name: pr-human-review-guide
description: Review or refresh a private GitHub PR/Diffview guide for a human reviewer or author: recommend file reading order, summarize structure, and draft prioritized local comments, questions, TODOs, curiosity notes, and validation gaps with file/line anchors. Use when the user provides a PR number/URL, prdv/Diffview input, local branch/diff range, asks for review order or human-review guidance, or provides an existing guide artifact to update.
---

# PR Human Review Guide

## Purpose and boundary

Given a PR number, PR URL, `prdv`/Diffview prompt, saved guide path, or local branch/diff range, produce a private guide that helps a human reviewer or author inspect the change efficiently and decide what comments/questions/TODOs to leave.

This skill is for **private/local inspection mode**. It is not a public PR description workflow and not a GitHub review-submission workflow.

Do not post comments, approve, request changes, resolve threads, edit PR bodies, or create public-facing review text unless the user explicitly asks for that in a later step through the proper workflow. If the user asks for a public GitHub PR body, use `pr-description-chain-writer` instead.

## When to use

Use for:

- PR review order or Diffview/prdv reading guidance.
- Local comments, questions, TODOs, curiosity notes, and validation gaps for a human reviewer or author.
- Refreshing an existing private review-guide artifact.
- Structured JSON review-guide artifacts when `prdv` or the user explicitly requests JSON.
- Local branch/range self-review before a PR exists.

Do not use for:

- Public PR descriptions or stacked PR body generation.
- Posting GitHub comments/reviews or resolving public review threads.
- General code review when the user wants only final findings and no human-review guide structure.

## Reference files

Bulky templates live in `references/output-templates.md`.

Read that file when:

- The user asks for exact raw Markdown or JSON artifact output.
- `prdv` requests structured JSON.
- Refreshing or replacing a saved guide artifact.
- You need the full section skeleton, JSON shape, or tone examples.

Keep this `SKILL.md` as the routing, safety, workflow, and output contract source of truth. Use the reference only for expanded templates and examples.

## Shared PR context packet

Build or reuse a compact private packet before writing the guide:

- repo, PR number/URL when available, local branch or diff range, base/head, and exact diff boundary
- whether input came from `prdv`, an already-open Diffview session, a saved guide refresh, or manual local self-review
- PR intent, touched subsystems, file list, generated/mechanical churn, and stack position if relevant
- comments/checks/verification evidence already observed, plus gaps that need local review

Keep this packet private. It may support detailed review order, deep/skim labels, questions, TODOs, suggested local comments, and verification gaps, but it should not be copied into a public PR body as-is.

## Output contract

### Default Markdown guide

The default output is raw guide Markdown only:

- no preface
- no meta-wrapper/status prose such as `No existing guide found`
- no wrapping fenced Markdown block
- first visible content should be the guide itself, preferably starting with `## TL;DR` followed by `## High-level summary`

The guide should be Diffview-centric and include:

1. `## TL;DR`: short private reviewer guidance with the main review path and highest-risk unknowns.
2. `## High-level summary`: conceptual layers of the change before file details.
3. Optional `## Review goal`: include only when a specific reviewer intent or author self-review goal would focus the pass.
4. PR-level context: title/URL/base/head, intent summary, risk summary, and validation focus.
5. `## Recommended inspection order`: Diffview/prdv-friendly file order using exact diff paths when practical.
6. `## File map`: compact file/area table; for huge PRs, group by directory/area with representative files or globs.
7. `## File-by-file Diffview guide`: expand only high-signal files.
8. Per-file notes: what the diff does, why it matters, what to inspect in Diffview, and review depth (`read carefully`/`deep`, `skim`, or `optional/generated`).
9. Suggested local review comments/questions/TODOs nested under relevant files.
10. `## Questions` table and `## Validation / coverage notes` after the file-by-file guide.

Prefer high-signal comments over exhaustive commentary. Use the full Markdown skeleton in `references/output-templates.md` when exact section wording/order matters.

Outside raw guide-artifact mode, final reports are `draft only` by default: state that no GitHub review, comment, approval, request-changes action, or thread resolution was updated. If the user later explicitly asks for a GitHub-facing mutation, report each intended artifact as `updated` or `not updated` with exact evidence such as the PR/comment/thread URL, the `gh` command that succeeded, or the blocker/reason no update happened.

For complex or unfamiliar subsystems, or when the user asks for explanation, begin with toddler terminology and a small diagram before the normal review order/comments. Keep simple PRs concise.

### Structured JSON artifact mode

When `prdv` or the user explicitly requests a JSON guide artifact, return raw JSON only:

- no preface
- no Markdown
- no save-status prose
- no fenced code block

Read `references/output-templates.md` for the full JSON schema/example before emitting JSON. Preserve the same private/read-only behavior and order `files` as the recommended human/Diffview review order, not alphabetically unless alphabetical is genuinely best.

Use exact Diffview file paths. `change_map` is optional; include it only when a concise ASCII/plain-text relationship figure, dataflow, or ownership map helps orient the reviewer. Do not invent exact line numbers; use `null` for approximate anchors. Prefer a short high-signal set of file notes and suggestions over exhaustive coverage.

### Guide artifact refresh mode

When the prompt provides a target guide path, existing guide path, or asks to update/refresh a saved guide:

- If the existing guide file exists and is readable, read it before reviewing the current PR state.
- Treat the existing guide as prior context, not truth.
- Preserve still-relevant observations, remove stale ones, and add new findings/questions from the current PR state.
- Keep refreshed output in the same raw Markdown or raw JSON artifact structure so it can replace the prior artifact cleanly.
- Mention materially stale or removed prior observations only when that helps the human reviewer; do not include a noisy changelog by default.
- If a guide path is provided, return only raw artifact content that can replace that file; do not add save-status prose or rely on shell redirect as proof that it was written.

## Workflow

### 1. Resolve PR context

Accept either:

- a PR number, e.g. `52370`
- a PR URL, e.g. `https://github.com/ZiplineTeam/FlightSystems/pull/52370`
- a `prdv`-generated prompt with PR metadata and a guide artifact path
- a local branch, commit range, or Diffview context for feature self-review before a PR exists

Prefer building PR context once with the deterministic helper when available, especially for a PR number or URL:

```sh
python3 "$HOME/.config/opencode/scripts/github_pr_context.py" <pr> --include-comments
```

For the current branch PR, omit `<pr>`. Use `--format markdown` only when a compact human-readable packet is more useful than JSON. For `prdv` prompts, trust provided metadata as the starting packet and refresh only missing details needed for the guide.

If the helper is unavailable, fall back to direct GitHub CLI commands:

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

Identify PR title and stated intent, base/head refs, stacked position, touched subsystems, useful commit groups, generated/dependency/lockfile/formatting-only churn, and the exact diff boundary. For stacked PRs, make clear whether the review is against the PR base, `develop`, or another stack branch.

If the subsystem is unfamiliar, spans several layers, or the user asks for easy terminology/examples, first explain the moving pieces in toddler terminology plus a small diagram. Then continue with the normal review boundary, file order, suggested comments, and validation notes.

### 3. Build a recommended inspection order

Recommend an order based on how a human should review the PR in Diffview or from a `prdv` packet, not alphabetically by default. Use exact file paths from the PR diff when practical.

Default order:

1. Public API, config, schema, CLI, or user-facing surface.
2. Architecture or wiring seams.
3. Core behavior / business logic.
4. Error handling, safety checks, compatibility paths.
5. Tests and validation.
6. Build/dependency files.
7. Generated or lockfile-only files.

Label review depth as `read carefully`, `deep` when requested, `skim`, or `optional/generated`.

Do not create detailed sections for every changed file by default. Use `## File map` and `## Recommended inspection order` for broad coverage, then expand only high-signal files: core behavior, public API/config/schema, safety or compatibility paths, files with suggested local comments/questions/TODOs, representative mechanical/generated areas, and central tests.

Explain briefly why each file appears in the inspection order, especially when one file should be understood before another.

### 4. Review the code

Review for correctness, hidden assumptions, safety or operational risk, edge cases, API/layering fit, maintainability, test and validation gaps, compatibility/migration concerns, excessive churn, and global coding-style concerns from `user-profile.yaml`.

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

For every suggested comment/question, include file path, line or line range when possible, concise suggested wording, and why it matters.

Do not invent exact line numbers. If the anchor is approximate, say `approx`; in JSON mode, use `null` for approximate line anchors.

## Guardrails and tone

- Do not post GitHub review comments unless explicitly asked.
- Do not approve, request changes, submit a review, resolve threads, or edit PR bodies.
- Do not turn this guide into a public PR description.
- Do not over-comment; prefer a short list of comments a human might actually leave.
- Treat coding-style comments as reviewability concerns; keep them low-severity unless they hide correctness or maintenance risk.
- Do not phrase curiosity as a demand.
- Do not review generated or lockfile churn deeply unless it changes behavior, build semantics, or dependencies.
- If the PR is too large to review confidently in one pass, say so and provide a phased review order.
- If a finding depends on uncertain intent, mark it as a question rather than a defect.

Be concise, evidence-backed, and reviewer-friendly. Avoid vague comments without anchors, broad redesign requests without evidence, pretending machine review is authoritative, distracting style nits, and generic PR-review prose that is not actionable while stepping through Diffview files.
