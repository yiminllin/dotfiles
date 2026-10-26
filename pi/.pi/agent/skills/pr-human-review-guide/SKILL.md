---
name: pr-human-review-guide
description: Review or refresh a private human-review guide from a PR URL/number, local Git branch, commit range, Diffview context, or saved guide. Use for review order, file-by-file guidance, anchored questions, or private Markdown/JSON review artifacts; not for public PR text or GitHub review mutations.
---

# PR Human Review Guide

## Purpose and boundary

Produce a private guide that helps a human inspect a change efficiently. Accept local Git evidence by default. A request to generate or refresh a guide authorizes read-only GitHub queries and fetching the needed PR/base refs for the named review in its repository, using existing authentication, without another approval prompt. For a PR URL or number, read current PR metadata and fetch/query the exact PR refs; do not require the user to fetch them. Online reads do not authorize GitHub writes, checkout, or source changes.

Default to private Markdown. Emit structured JSON only when requested or required by a local Diffview/prdv workflow. Read `references/output-templates.md` when exact artifact structure is needed.

Use the same six-part structure for Markdown and Diffview guides: goal, behavior change, PR flow, core code, top-down review route, and review focus. Load `../code-explainer/SKILL.md` to coordinate core-code and diagram procedures for the same verified scope and revisions. Let code explain behavior and the diagram explain relationships; do not repeat them in prose. Keep full-PR context even when the viewer filters ownership. An explicitly requested one-shot guide does not need a separate layout approval. Follow the persistent-guide rules below when maintaining a Diffview artifact.

## Inputs

Accept a PR number/URL, local branch, commit range, current-worktree diff boundary, Diffview/prdv context, or existing guide. For a bare PR number, establish the repo from the checkout or ask if ambiguous. If the local boundary is ambiguous, ask one short question rather than guessing. When remote access or existing authentication is unavailable, use a known local boundary if one exists; otherwise name the missing evidence and ask for a local ref or user-managed authentication. Do not initiate authentication.

## Workflow

1. If refreshing a guide, read it as prior context, not truth.
2. Resolve the exact boundary. For online PRs, use the scoped permission above to read the live PR body, head/base, and fetch only the needed refs if local objects are missing or stale. If Diffview supplied immutable revisions, preserve that boundary; report remote drift rather than silently switching revisions. Keep the review limited to the named PR; parent PRs provide context, not additional review scope. Do not checkout, reset, clean, or alter the working tree. Record head SHA and the boundary inspected; local refs alone do not prove current remote state.
3. Inspect the diff, changed-file list, relevant surrounding code, tests, and repository guidance. Do not modify source files.
4. Build a private context packet: PR metadata and body claims, exact diff boundary, intent, touched subsystems, file list, mechanical/generated churn, observed validation, and gaps. Check stated PR intent against code.
5. State the PR goal in plain language: the problem it addresses and intended outcome, not a file inventory. Explain the verified before/after behavior and observable consequence. If requested, offer three alternative one-line goal summaries before expanding the chosen framing; do not make this a startup checkpoint.
6. Use `code-explainer` to produce a source-backed PR-flow diagram and the smallest faithful core-code view. Keep actual source identifiers and consequential conditions/error paths. For PR guides, make the central before/after comparison explicit in paired code or diagram views. Compare the same path or mechanism at the same abstraction level: do not compare an old call signature with a detailed new implementation. Choose a diagram comparison for structural changes and code for behavioral changes; use both only when complementary. Label each side and its revision. Label any after-only companion view as such. Verify both revisions independently; when evidence is missing, explain why a paired comparison cannot be shown rather than inventing it.
7. Build the review route from highest-level entry points through API/config and wiring to core behavior, effects/error paths, tests, and supporting/generated details. Follow actual caller-to-callee relationships, not alphabetical or largest-diff order. Group separate flows by purpose and review each top-down. Include unchanged entry points as clearly labeled context references, not changed Diffview files. Give each changed file a stage and a short reason naming the relevant symbol and what to verify; label depth `read carefully`, `deep`, `skim`, or `optional/generated` in that reason. Include every changed file, even under ownership filtering; group mechanical files for skim coverage in Markdown.
8. Review the high-signal code, not just its structure: check correctness, assumptions, operational risk, edge cases, API/layering fit, compatibility, churn, and validation gaps. Include all substantive review questions and verified risks, grouped by route stage/file. A request to test guide generation still requires this source review; do not silently replace it with an orientation-only exercise. State actual review depth and uninspected scope without claiming an exhaustive audit. Remove repetition and generic checklist questions, not evidence-backed items to meet a count limit.
9. Include an explicit suggested-review-comments section. Separate evidence-backed findings from open questions and validation gaps. Give each actionable item proposed comment wording, a label, a proven file and side/line/range, and its impact or reason for asking. Do not present a reading checklist as review comments. If no evidence-backed findings were established, say so; do not invent defects to fill the section. Keep internal follow-up checks in validation notes unless they merit an actionable author-facing comment. Mark approximate Markdown anchors `approx`; use `null` in JSON. Never invent line numbers.
10. Apply final review-quality rules in `~/.pi/agent/APPEND_SYSTEM.md` and repository guidance. Deliver the guide directly; save a file only when requested.

## Persistent Diffview guides

Write one JSON artifact atomically; do not create a separate Markdown guide. Reuse a valid guide unless it is missing, invalid, stale, lacking a diagram, or explicitly requested for refresh. New template fields alone do not require regeneration. When ongoing updates are authorized and discussion changes understanding or order, revise the same artifact; do not rewrite it for every reply. Preserve exact revision stamps and still-relevant suggestion IDs. Neovim owns comment state, reviewed-file progress, and ownership filters—do not edit those. Explain activity and findings in the visible Pi conversation.

## Comment labels

- `Blocker`: likely correctness or safety issue requiring resolution.
- `High`: substantial risk or missing validation for important behavior.
- `Medium`: plausible bug, design concern, or maintainability issue.
- `Low`: non-blocking coverage, readability, or follow-up suggestion.
- `Curiosity`: genuine context question, not a demanded change.
- `Nit`: small local issue; omit unless useful.

For Questions use `Clarification`, `Curiosity`, `Follow-up`, `Verification gap`, or `Blocker`.

## Output contract

For raw artifact requests, return only the Markdown guide or JSON object: no preface, status wrapper, redirect instructions, or fenced wrapper. Follow the six-part structure in `references/output-templates.md`. Start with a very high-level goal, then behavior change, PR flow, core code, review route, and review focus. Include exact revision context and validation/coverage notes without burying the goal. Keep the overview concise through organization, not by capping questions or findings. Require a directly comparable before/after view and explicit proposed review-comment wording; distinguish findings from questions and state review coverage. Follow the template's compatibility notes for fields the Diffview viewer does not yet display.

Outside raw artifact mode, report `draft only` and state that no GitHub review or source/Git state was changed. If authorized guide artifacts were updated, say so. Keep the packet private; do not turn it into public PR prose or reply only with an artifact path.

## Guardrails

- Local reads are the default. Requested guide generation or refresh includes scoped read-only GitHub queries and needed PR/base-ref fetches using existing authentication; do not ask again. Unrelated network access still requires approval. Never initiate login or read credentials.
- Do not post, approve, request changes, resolve threads, or edit PR bodies from this skill; route separately requested GitHub writes to their owning workflow.
- Treat uncertain intent as a question, not a defect. Include every substantive, actionable review item with evidence and uncertainty; do not impose an arbitrary count cap or pad the guide with speculative comments.
- If the change is too large for confident review, say so and provide a phased order.
