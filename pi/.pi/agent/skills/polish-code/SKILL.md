---
name: polish-code
description: Make a feature, PR, or PR chain easier for humans to understand. Use for "polish this code", "make the change minimal", "simplify the diff", "remove unnecessary unit tests", or readability passes on names, comments, docstrings, inlining, and code order. Inspect the whole requested scope from source; offer selectable naming and cleanup choices before editing unless automatic cleanup is explicitly requested. Not for feature development or UI design.
license: MIT
---

# Polish code

**Optimize for human understanding, not line count.** Use concise, explicit language without jargon; retain accurate established terms. Preserve behavior and essential coverage.

## 1. Choose mode and scope

| Mode | Behavior |
|---|---|
| Interactive (default) | Inspect, summarize, then use `ask_user_question`. Wait for choices before editing. |
| Automatic (explicit request) | Apply clear cleanup; leave subjective names and uncertain test removals unchanged and report them. |
| Review only | Recommend without editing or requesting approval to edit. |

Use `/skill:polish-code` with an optional mode and scope. During development, use this checklist only when polishing is requested. Reuse known context and approvals; do not spawn another agent merely to run it.

- Read repository guidance, Git status, staged/unstaged diffs, and relevant untracked source. Exclude secrets/generated output; preserve unrelated work.
- Prefer named scope, otherwise current-task changes or one coherent uncommitted change. Ask one focused question if the boundary is unclear.
- Identify committed base/head from local refs and PR/stack metadata; do not assume main or the remote tracking tip. Inventory each requested PR's parent/head and inspect each diff plus the combined result—not just the checked-out branch. Include only related local edits.
- Infer intent from source, callers, tests, and configuration, without requiring a chat recap. Consult history only for missing decisions.

## 2. Inspect the full scope

**Coverage gate:** Before editing, record inspected and remaining PRs/files. Read changed hunks and surrounding definitions, not just obvious cleanup candidates. When resuming, check prior inspection against the current skill and source; an old shortlist does not establish coverage. Complete inspection before the final proposal or label the work partial.

Inspect all eight passes using local conventions:

| Pass | Goal |
|---|---|
| Names | Review every added or materially changed variable, field, struct, type, and function. Clarify meaning, actions, booleans versus quantities, and units. |
| Comments and docstrings | Separately review changed definitions for missing purpose, constraints, defaults, seed effects, or surprising behavior. Simplify unclear wording; do not add documentation to every obvious function. |
| Tests | Remove redundant new cases, distracting setup, and assertions of internal structure; keep clear evidence of behavior. |
| Inlining | Remove needless jumps through trivial wrappers, one-use helpers, or temporary variables. Keep helpers and names that explain concepts or simplify expressions. |
| Reading order | Group related logic and introduce concepts in reading order without changing execution or initialization order. |
| Control flow | Expose the main path by reducing nesting, repeated branches, and scattered conditions. |
| Abstractions and state | Remove unnecessary layers, duplicate state, dead code, and speculative configuration; reuse existing patterns. |
| Diff hygiene | Remove task-introduced accidental edits and development leftovers, not unrelated work. Avoid broad refactors, dependency changes, and unrelated formatting. |

**Comments:** Explain intent rather than restating code. Preserve original comments beside moved code; reword only for accuracy. Remove redundant new comments, not useful history. Use concise Setup / Test / Verify comments only for hard-to-follow tests.

**Tests:** Review new tests, not the whole suite. Preserve existing tests and essential new behavior, regression, boundary, and failure coverage. Before removal, identify retained verification of the same behavior; keep uncertain cases. Size, private-code access, or passing today does not justify deletion. Never hide failures or target deletion counts. Consolidate for clarity; reuse existing coverage for equivalent refactors.

## 3. Prompt through the findings

Briefly state coverage, unfinished areas, and findings: **confusion → change → clarity benefit**. Group routine edits without dropping findings or imposing a suggestion quota.

**Approval gate:** In interactive mode, obtain explicit selections through `ask_user_question` before editing; a text list alone is insufficient. A repeated "polish this PR" request is not approval of an earlier proposal or its recommended names. Reuse explicit approvals only for the same changes; otherwise prompt. If the tool is unavailable, wait for explicit text selections.

- Batch up to four questions per call, with two to four options each. After answers, continue remaining decisions; the prompt limit is not a finding limit.
- For meaningful naming changes, offer two or three alternatives plus keep-current. Put the recommendation first with `(Recommended)`. Do not invent alternatives for clear names or rename established public/domain concepts merely for style.
- Use short labels and explanations, `preview` for useful single-select code comparisons, and `multiSelect` for independent edits. The tool supplies custom answers.
- Wait before editing. Cancellation is not approval; do not repeat answered or already authorized choices. Use text-only choices only if the tool is unavailable, with stable labels such as `N1` and `T1`.

Skip prompts in automatic/review-only modes. If no useful cleanup exists, say so; do not manufacture edits.

## 4. Apply, verify, and stop

- Apply approved or clear automatic cleanup; update renamed references. Preserve results, errors, ordering, ownership, concurrency, and public interfaces. Leave uncertain behavior equivalence unchanged; report discovered bugs separately.
- Keep the smallest coherent change; do not add cleanup frameworks or abstractions that need more explanation than they remove.
- Run focused tests and required repository checks. Remote jobs, simulations, network writes, and expensive unrelated suites need approval.
- Check the final diff for behavior changes, lost comments/coverage, unnecessary renames, and unresolved findings. Stop after scoped inspection, agreed changes, and required fixes.
- Preserve the index. Stage, commit, amend, restack, push, or publish only when asked. Mention new unstaged edits to staged files; reassess scope after concurrent file/ref changes.
- Report **inspection status** (complete or partial, with remaining scope) separately from **cleanup status** (approved changes applied or pending). Passing checks or applying a shortlist does not establish full inspection. Briefly summarize clarity improvements, test decisions, checks, and uncertainty—not an edit log; distinguish verified results from assumptions.
