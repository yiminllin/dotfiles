---
name: pr-human-review-guide
description: Review or refresh a private human-review guide from a local Git branch, commit range, Diffview context, or saved guide. Use when asked for review order, file-by-file guidance, anchored local comments or questions, or a private Markdown/JSON review artifact; do not use for public PR text or GitHub mutations.
---

# PR Human Review Guide

## Purpose and boundary

Produce a private guide that helps a human inspect a local change efficiently and decide what comments, questions, or TODOs to leave. This Pi migration supports local Git evidence only. It does not fetch PR data, use GitHub authentication, post comments, submit reviews, resolve threads, or edit PR bodies.

Default to private Markdown. Emit structured JSON only when the user or a local Diffview/prdv workflow explicitly requests it. Read `references/output-templates.md` when exact artifact structure is needed.

## Inputs

Accept a local branch, commit range, current-worktree diff boundary, Diffview/prdv context, or an existing guide path. If the boundary is ambiguous, ask one short question rather than guessing. A PR number or URL alone is insufficient in this local-only slice; ask for a locally available ref/range or provided metadata. Do not invoke network, authentication, or GitHub CLI as a fallback.

## Workflow

1. If refreshing a guide, read it as prior context, not truth.
2. Resolve the exact local diff boundary with read-only Git commands. Record base/head or the worktree/index boundary inspected.
3. Inspect the diff, changed-file list, relevant surrounding code, tests, and nearby repository guidance. Do not modify source files.
4. Build a private context packet: supplied PR metadata if any, exact diff boundary, intent, touched subsystems, file list, mechanical/generated churn, observed validation, and gaps.
5. Recommend a human inspection order: public API/config first, then wiring, core behavior, error/safety paths, tests, dependencies, and generated files. Use exact diff paths and label depth `read carefully`, `deep`, `skim`, or `optional/generated`.
6. Expand only high-signal files. Review correctness, assumptions, operational risk, edge cases, API/layering fit, maintainability, compatibility, churn, and validation gaps.
7. Anchor every suggested comment to a file and line/range when proven. Mark approximate Markdown anchors `approx`; use `null` in JSON. Never invent line numbers.
8. Apply the final cleanup and review-quality rules in `~/.pi/agent/APPEND_SYSTEM.md` and repository guidance. Keep the artifact concise and evidence-backed.

## Comment labels

- `Blocker`: likely correctness or safety issue requiring resolution.
- `High`: substantial risk or missing validation for important behavior.
- `Medium`: plausible bug, design concern, or maintainability issue.
- `Low`: non-blocking coverage, readability, or follow-up suggestion.
- `Curiosity`: genuine context question, not a demanded change.
- `Nit`: small local issue; omit unless useful.

For the Questions table use `Clarification`, `Curiosity`, `Follow-up`, `Verification gap`, or `Blocker`.

## Output contract

For raw artifact requests, return only the Markdown guide or JSON object: no preface, status wrapper, redirect instructions, or fenced wrapper. Start Markdown with `## TL;DR`, then `## High-level summary`. Include context, recommended inspection order, a compact file map, high-signal file guidance, questions, and validation/coverage notes.

Outside raw artifact mode, report `draft only` and state that no GitHub or repository state was changed. Keep the packet private; do not turn it into public PR prose.

## Guardrails

- Use only local reads and read-only Git inspection. Never fetch, checkout, reset, clean, or mutate the repository.
- Do not invoke `gh`, network access, authentication, or provider/model calls.
- Do not post, approve, request changes, resolve threads, or edit PR bodies.
- Treat uncertain intent as a question, not a defect; separate behavioral risk from style preference.
- Prefer a few actionable, anchored comments over exhaustive commentary.
- If the change is too large for confident review, say so and provide a phased order.
