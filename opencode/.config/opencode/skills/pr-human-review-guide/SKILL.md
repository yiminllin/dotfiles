---
name: pr-human-review-guide
description: Review a GitHub PR for a human reviewer: recommend file reading order, summarize structure, and draft prioritized review comments, questions, curiosity notes, and validation gaps with file/line anchors. Use when the user provides a PR number or URL and asks for review order, human-review guidance, curiosity comments, or suggested review comments.
---

# PR Human Review Guide

## Overview

Given a PR number or URL, produce a guide that helps a human reviewer read the PR efficiently and decide what comments/questions to leave.

This skill is for **review preparation**, not submitting a GitHub review. Do not post comments, approve, request changes, or resolve threads unless the user explicitly asks for that in a later step.

## Primary output

The default output should include:

1. Overall assessment.
2. High-level PR structure overview.
3. Recommended file reading order.
4. Suggested machine-generated review comments/questions nested under the relevant file.
5. Curiosity/follow-up comments.
6. Validation and coverage notes.

Prefer high-signal comments over exhaustive commentary.

## Workflow

### 1. Resolve PR context

Accept either:

- a PR number, e.g. `52370`
- a PR URL, e.g. `https://github.com/ZiplineTeam/FlightSystems/pull/52370`

Use GitHub CLI for PR context:

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

### 2. Establish the review boundary

Before reviewing details, identify:

- PR title and stated intent.
- Base/head refs.
- Whether the PR appears stacked.
- Main touched subsystems.
- Commit grouping if useful.
- Generated, dependency, lockfile, formatting-only, or mechanical churn.

For stacked PRs, make the diff boundary explicit so the user knows whether the review is against the PR base, `develop`, or another stack branch.

### 3. Build a file reading order

Recommend an order based on how a human should understand the change, not alphabetical order.

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
- `skim`
- `optional/generated`

Explain briefly why each file appears in that position.

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

### 6. Anchor comments

For every suggested comment/question, include:

- file path
- line or line range where possible
- concise suggested wording
- why it matters

Do not invent exact line numbers. If the anchor is approximate, say `approx`.

### 7. Output format

Use this structure:

```markdown
## Overall assessment
- <blocker/non-blocker judgment and main risk>

## PR structure overview
- <brief structure of the change by subsystem/flow>

## Suggested human review order
1. `path/to/file.rs` — <why read first> [read carefully]
   - **Medium** — `path/to/file.rs:10-20`: <suggested review comment/question>
     - Why it matters: <risk/context>
2. `path/to/next_file.rs` — <why next> [skim]
   - No machine comments; skim for <reason>.

## Cross-cutting review questions
- **Curiosity** — `path/a.rs:10`, `path/b.rs:30`: <question>

## Validation / coverage notes
- <tests observed>
- <gaps or follow-up validation>
```

## Guardrails

- Do not post GitHub review comments unless explicitly asked.
- Do not approve, request changes, or submit a review.
- Do not over-comment. Prefer a short list of comments a human might actually leave.
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
