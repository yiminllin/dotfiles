---
name: pr-human-review-guide
description: Review or refresh a private human-review guide from a PR URL/number, local Git branch, commit range, Diffview context, or saved guide. Use for review order, file-by-file guidance, anchored questions, or private Markdown/JSON review artifacts; not for public PR text or GitHub review mutations.
---

# PR Human Review Guide

## Purpose and boundary

Produce a private guide that helps a human inspect a change efficiently. Accept local Git evidence by default. For a PR URL or number, read current PR metadata and fetch/query the exact PR refs after explicit network/auth approval; do not require the user to fetch them. Online reads do not authorize GitHub writes, checkout, or source changes.

Default to private Markdown. Emit structured JSON only when requested or required by a local Diffview/prdv workflow. Read `references/output-templates.md` when exact artifact structure is needed.

## Inputs

Accept a PR number/URL, local branch, commit range, current-worktree diff boundary, Diffview/prdv context, or existing guide. For a bare PR number, establish the repo from the checkout or ask if ambiguous. If the local boundary is ambiguous, ask one short question rather than guessing. When remote access is unavailable or not approved, use a known local boundary if one exists; otherwise name the missing evidence and ask for network approval or a local ref. Do not initiate authentication.

## Workflow

1. If refreshing a guide, read it as prior context, not truth.
2. Resolve the exact boundary. For online PRs, first obtain network/auth approval; read the live PR body, head/base, and fetch only the needed refs if local objects are missing or stale. Keep the review limited to the named PR; parent PRs provide context, not additional review scope. Do not checkout, reset, clean, or alter the working tree. Record head SHA and the boundary inspected; local refs alone do not prove current remote state.
3. Inspect the diff, changed-file list, relevant surrounding code, tests, and repository guidance. Do not modify source files.
4. Build a private context packet: PR metadata and body claims, exact diff boundary, intent, touched subsystems, file list, mechanical/generated churn, observed validation, and gaps. Check stated PR intent against code.
5. Recommend an inspection order: public API/config, wiring, core behavior, error/safety paths, tests, dependencies, generated files. Label depth `read carefully`, `deep`, `skim`, or `optional/generated`.
6. Expand only high-signal files. Review correctness, assumptions, operational risk, edge cases, API/layering fit, compatibility, churn, and validation gaps.
7. Anchor each suggested comment to a proven file and line/range. Mark approximate Markdown anchors `approx`; use `null` in JSON. Never invent line numbers.
8. Apply final review-quality rules in `~/.pi/agent/APPEND_SYSTEM.md` and repository guidance. Deliver the guide directly; save a file only when requested.

## Comment labels

- `Blocker`: likely correctness or safety issue requiring resolution.
- `High`: substantial risk or missing validation for important behavior.
- `Medium`: plausible bug, design concern, or maintainability issue.
- `Low`: non-blocking coverage, readability, or follow-up suggestion.
- `Curiosity`: genuine context question, not a demanded change.
- `Nit`: small local issue; omit unless useful.

For Questions use `Clarification`, `Curiosity`, `Follow-up`, `Verification gap`, or `Blocker`.

## Output contract

For raw artifact requests, return only the Markdown guide or JSON object: no preface, status wrapper, redirect instructions, or fenced wrapper. Start Markdown with `## TL;DR`, then `## High-level summary`. Include context, inspection order, compact file map, high-signal file guidance, questions, and validation notes.

Outside raw artifact mode, report `draft only` and state that no GitHub review or repository state was changed. Keep the packet private; do not turn it into public PR prose or reply only with an artifact path.

## Guardrails

- Local reads are the default. Online PR reads or Git fetch require network/auth approval for the exact scope. Never initiate login or read credentials.
- Do not post, approve, request changes, resolve threads, or edit PR bodies from this skill; route separately requested GitHub writes to their owning workflow.
- Treat uncertain intent as a question, not a defect. Prefer a few actionable, anchored comments over exhaustive commentary.
- If the change is too large for confident review, say so and provide a phased order.
