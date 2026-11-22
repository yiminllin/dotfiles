---
name: pr-description-chain-writer
description: Draft, explain, shorten, or update changes for a reviewer-facing pull request description, PR body, or PR template. Use for "draft a PR for this branch", "create a PR and write the description", "explain this change for the PR description", and edits to Verification or other PR sections. Works for single PRs, local branches, and stacks. Not for chat-only explanations, private review guides, or review comments.
---

# PR Description Chain Writer

## Choose the first-draft presentation

**Draft without a presentation menu by default.** Honor explicit choices. For unresolved choices, use the simplest structure that explains the verified change: Brief for a small change, One main view for one mechanism, or Numbered overview + details for several distinct changes. **When a PR changes a workflow handoff, render an ASCII flow diagram in `Description of Change` by default.** This applies when a stage starts accepting a new input, produces a new output, or work moves between stages. Use the `code-diagram` renderer via `code-explainer`; show the producer, payload, receiving stage, and downstream result. A table can supplement the diagram, but cannot replace it unless the user explicitly chooses another overview view. Make this decision from the verified change, not the number of files or the existing PR layout. Use mixed detail unless exact names or plain labels better serve the draft. Ask only if the review boundary cannot be resolved or the user opts into choosing the presentation.

**When a new or changed input joins an existing path at a shared stage, default to Numbered overview + details with box flow.** In the overview, draw both paths from their verified entry points, label the payloads, and show where they join and who consumes the result. Keep unchanged context visible but distinct from the change. If a producer belongs to a later PR, label it as out of scope; do not make it the only entry point. Number the transformations and shared stage that need explanation, then render a focused diagram for each section.

If the user opts in, ask unresolved choices in one `ask_user_question` menu:

| Question | Choice pool |
|---|---|
| **Structure** | Brief · One main view · Numbered overview + details |
| **View** | Prose · Box flow · Before/after boxes · Tree · Core code · Formula · Table |
| **Detail** | Plain labels · Exact names and types · Mixed |
| **Scope** (if unclear) | One change · This PR · Full stack |

In the opt-in menu, keep Structure, View and Detail separate, with 2–4 short relevant options each and the recommendation first. Name the diagram types. If a non-diagram View is chosen for a numbered draft, it applies to the details; still render the overview. If the picker is unavailable, ask in chat and wait. If cancelled, stop.

For section-only edits, keep the existing presentation unless asked to change it. Pass the resolved presentation to the explainer without a nested menu.

## Overview

Write reviewer-facing GitHub PR text for one change or a stack. Load this skill before drafting the body even when another workflow owns PR creation or stack submission. For a chat-only explanation, use `code-explainer`; for a private review guide, use `pr-human-review-guide`.

Draft locally by default. Use existing authentication for requested read-only GitHub inspection. Obtain explicit approval before posting bodies. Never log in, submit a stack, or push branches from this skill.

Use past PRs for structure, tone, and level of detail only. Never copy their claims or evidence into a new PR. Keep private examples and audit artifacts outside public checkouts; use fictional examples in tracked skill files.

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

- Accept one PR number/URL, a local branch, or ordered PR numbers in chain order.
- For local stacks before PRs exist, collect the current git-spice stack from the repo checkout instead of asking for PR numbers.
- Resolve the repository from the PR URL, explicit input, or current checkout. Ask if it remains ambiguous.
- Prefer using a style reference PR with a high-quality body in the same chain.

For local git-spice stacks, inspect the stack with read-only `git`,
`git-spice log long`, and boundary diffs before writing final text. Do not rely
on an agent-specific shared packet helper.

The local mode is read-only, does not require `gh`, uses branch placeholders in the PR Tree until PR numbers exist, and warns when drafts are based only on committed branch diffs because the worktree is dirty.

### 2. Lock explicit overrides before drafting, regenerating, or posting

Before running the generator, regenerating text, or posting bodies, capture the user's locked overrides from the request, active plan/artifact, and current conversation. Reuse explicit overrides without asking again; ask only when a required posting decision is missing or conflicts with evidence.

Lock these items when present:

- chain-level `Reason for Change` wording and context links; preserve an existing PR's reason unless the user asks to align it across the chain
- requested title tags and title conventions, including explicit capitalization
- `Criticality of Change` and `Release Notes` checklist checked states for each PR
- diagram/table preference and any requested description style
- per-PR emphasis, such as which mechanism, files, reviewer concern, or risk each PR should highlight
- verification evidence, including exact commands, run or report links, result labels, and explicit not-run reasons

### 3. Choose a structure and draft

Use the resolved first-draft presentation. See [Explanation choices](../code-explainer/choices.md) for shared handoff rules.

Keep prose short and let the diagrams carry the detail. Cut prose that repeats a figure, not meaningful stages, arrows, or payload labels. Keep material verification results or gaps. Expand optional prose only on request.

| Structure | Description of Change |
|---|---|
| Brief | A sentence or a few bullets. No diagram required. |
| One main view | Use the selected view. Add another only if it answers a different question. |
| Numbered overview + details | Follow [the shared numbered layout](../code-explainer/SKILL.md#numbered-overview--details). Include its rendered overview in `Description of Change`; a selected detail view never replaces it. For a boxed workflow, require one rendered box diagram under every numbered group unless the user selects a different detail view. Zoom in on that group’s inputs, transformations, decisions, and outputs as relevant. Do not redraw the entire overview. Add a short group-to-commit table where useful. |

For an existing PR body or one-section update, first read the live body, then draft the smallest requested diff against it. Do not run the whole-body generator for a section-only update. For new PR bodies or an explicitly requested rewrite, use the generator script from the loaded skill directory. Set `SKILL_DIR` to that directory when needed; for the stowed global skill this is usually `$HOME/.pi/agent/skills/pr-description-chain-writer`. The generator uses read-only `gh` queries; run it only for the requested repository and PRs with existing authentication.

```bash
SKILL_DIR="${SKILL_DIR:-$HOME/.pi/agent/skills/pr-description-chain-writer}"
python3 "$SKILL_DIR/scripts/generate_pr_chain_descriptions.py" \
  101 102 103 \
  --repo OWNER/REPO \
  --style-pr 101 \
  --context-link "Context: https://github.com/OWNER/REPO/issues/100" \
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

- Use `../code-explainer/SKILL.md` for the selected views. Reuse verified explanations from a matching private guide without copying review routes, questions, or comments. Disclose missing source instead of inventing details.
- Read `references/style-notes.md` and keep template order/shape consistent.
- For section-update requests, update only the requested body/template section, preserving all other live wording, checklist state, and style. Show the minimal proposed diff before posting.
- Do a title preflight before writing or posting:
  - Preserve any capitalization the user explicitly requested.
  - When drafting from commits, preserve commit title capitalization/style unless the user asks for a rewrite.
  - Preserve repository or user-supplied ticket prefixes, component tags, and test-only markers.
- State the concrete problem in `Reason for Change`. Start `Description of Change` with what this PR changes and the effect on behavior. Treat generator prose as a draft; verify claims against the actual diff and evidence.
- Use short, active sentences. Name the function, field, type, or flag in backticks when it makes the actor, input, or output clear. Use the same term throughout. Replace vague phrases such as “plumb the config” with who reads what and where it goes.
- Describe actual actions in prose, captions, and diagram labels. Omit what does not happen or stays the same unless it prevents a concrete misunderstanding about scope, compatibility, or risk. Cut headings, subtext, and file lists that repeat the lead or a selected view.
- For chains, keep the shared motivation and context identical across PRs. Use a neutral chain-wide before/after overview there only when it explains the motivation. Compare the current PR against its own base in `Description of Change`. Keep `PR Tree` by default; only omit it when the user asks or it is clearly noise for reviewers.
- When a published stack is known, use a `PR Tree` heading and one bare `- #123` per line in verified stack order. Add `◀` only to the current PR if it is a member. Do not use inline arrows, nesting, titles, or explicit Markdown links. Use local branch placeholders only when PR numbers do not exist.
- When a tracking ticket is known and the repository uses a ticket line, put its verified link below the `PR Tree` block; use the ticket most relevant to each PR, even when multiple PRs share a ticket.
- For non-trivial PRs, optionally add `### Map for Reviewers` under `Description of Change`. Skip it for tiny PRs. Use this public shape instead of dense reviewer-guide tables:
  - `**Suggested route**`: numbered 1-3 semantic areas to inspect.
  - `**Key checkpoints**`: concise bullets for the main correctness, config, API, or frame points.
  - `**Context anchors**`: concise bullets for parent/child PRs, issue/design/discussion context, key evidence, or validator follow-up.
- Optionally add `### Watchouts` only for real risk or follow-up. Skip it when there is no meaningful risk. Keep compact bullets shaped as `**Risk**: ...`, `**Mitigation**: ...`, and `**Follow-up**: ...`.
- Omit either section when it repeats the description or verification. Keep both factual and safe for the PR's audience.
- Preserve the repository template checkbox blocks for `Criticality of Change` and `Release Notes`; do not collapse them to prose such as `L3 Nonfunctional`. Use the existing repo checklist blocks when known, or copy/preserve the exact checklist shape from the current PR template or style reference. Before finalizing, verify the checked criticality and release-notes state reflect reality for each PR.

#### Verification: checklist first

1. Default to one Markdown checklist line. Add another only for a distinct material failure, pending check, or coverage gap. Mark confirmed passes as `- [x] <check>: passed` and failed, pending, or unrun checks as `- [ ] <check>: <status>`. Link directly to a run or report when available. If nothing ran, write `- [ ] Not run: <reason>.` If evidence is missing, write `- [ ] Verification not confirmed.`
2. Include a fenced `bash` block below the checklist when a reproducible command is available. Prefer the actual command and preserve required targets, flags, and seeds. Label any source-checked equivalent without implying it ran. Omit the block if no command can be verified.
3. If measured differences matter, add a small before/after table with units and the comparison baseline. Keep material failures, pending checks, and older-head or stack-tip limits even if they need another line. Omit logs, bare `CI`, and test inventories. Never claim another PR's result as this PR's.

Before showing or posting a draft, read the rendered body once. Verify template and checkboxes, source names, current-PR scope, and evidence. When the workflow-handoff rule applies, confirm a rendered flow diagram is present in the final body; a table-only draft is incomplete. For converging inputs, trace each path in the rendered overview to the shared stage and trace its output to the consumer. A path mentioned only in prose does not count. For a numbered box-flow draft with no detail override, count one successfully rendered overview plus one successfully rendered box diagram inside each numbered group. Check every ASCII diagram matches its own successful renderer output unchanged. Fix rejected layouts instead of hand-drawing; if source evidence is missing, state the gap. Check the PR Tree is a flat list in verified order. Delete text that adds no fact, decision, or evidence. Check only the edited sections for a section-only update.

### 5. Apply generated body to each PR (optional, separately approved)

```bash
gh pr edit 102 --repo OWNER/REPO --body-file /tmp/pr-chain-bodies/pr_102.md
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
- Optional `### Map for Reviewers` and `### Watchouts` sections only when they add reviewer value.
- The selected structure, with source-backed views and comparison only where useful. Keep public wording concise; do not copy private review content.
- Existing PRs' own `Criticality of Change` and `Release Notes` checkboxes (no inferred checked defaults); review them for each new PR, plus concise per-PR verification evidence.

Write files to:

- `/tmp/pr-chain-bodies/pr_<PR_NUMBER>.md` (or chosen `--write-dir`).

## Resources

- `scripts/generate_pr_chain_descriptions.py`: main generator.
- `references/style-notes.md`: chain style cues to preserve.
