---
name: polish-code
description: Make a feature, PR, or PR chain easier for humans to understand. Use for "polish this code", "make the change minimal", "simplify the diff", "remove unnecessary unit tests", or readability passes on names, comments, docstrings, inlining, and code order. Inspect the whole requested scope, then apply clear local cleanup by default. Honor review-only and interactive requests. Not for feature development or UI design.
license: MIT
---

# Polish code

**The diff must be as small as possible while preserving required behavior, human readability, and essential coverage.** Delete or revert unnecessary changes instead of rewriting them.

## 1. Choose mode and scope

| Mode | Behavior |
|---|---|
| Automatic (default for a request to polish) | Finish the scoped cleanup in one run without routine approvals. Apply clear edits; keep uncertain or behavior-changing edits out and record why. |
| Interactive (on request) | Inspect, summarize, then use `ask_user_question`. Wait for choices before editing. |
| Review only (suggestions, assessment, or plan) | Recommend without editing or requesting approval to edit. |

Use `/skill:polish-code` with an optional mode and scope. During development, use this checklist only when polishing is requested. Reuse known context and approvals; do not spawn another agent merely to run it.

- Read repository guidance, Git status, staged/unstaged diffs, and relevant untracked source. Exclude secrets/generated output; preserve unrelated work.
- Prefer named scope, otherwise current-task changes or one coherent uncommitted change. Ask one focused question if the boundary is unclear.
- Identify committed base/head from local refs and PR/stack metadata; do not assume main or the remote tracking tip. Inventory each requested PR's parent/head and inspect each diff plus the combined result—not just the checked-out branch. Include only related local edits.
- Infer intent from source, callers, tests, and configuration, without requiring a chat recap. Consult history only for missing decisions.

## 2. Inspect the full scope

**Coverage gate (all modes):** Keep a review note outside the working tree. Reconcile its file checklist with each PR diff and the combined diff. Include build, deployment, and config files; record exclusions and why. Read changed hunks and surrounding definitions. In each file, record what can go, what must stay, and what needs verification. Record each new or changed identifier's keep/rename decision and each addition's doc update or existing explanation. Record test decisions. Group related entries; do not substitute a file summary for decisions. Mark unfinished items explicitly. On resume, recheck coverage against the current source. Do not give a final proposal while coverage is incomplete; label any interim findings partial.

Finish the deletion and test-reduction decisions across the full scope before polishing names and wording. Start from the base: justify every changed hunk against the task. If deleting it or reverting it to the base preserves required behavior, readability, and essential coverage, remove it (or recommend removal in review-only mode). Check callers, build references, and serialized contracts before deciding. Then inspect all eight passes using local conventions:

| Pass | Goal |
|---|---|
| Names | Decide keep or rename for every added or materially changed identifier, including locals, parameters, fields, functions, and types. Ask whether a reader can infer its role, action, state, or unit without tracing the implementation. If not, choose the clearest explicit name. Keep clear names; do not churn unrelated code. |
| Comments and docstrings | Account for every addition. Document new modules, types, functions, and configuration at their definitions. Explain fields, locals, and logic in nearby docs when names alone do not convey intent. Cover purpose, contracts, defaults, and constraints. |
| Tests | Try removing every PR-added unit test. Keep only the smallest set needed to verify essential behavior. |
| Inlining | Remove needless jumps through trivial wrappers, one-use helpers, or temporary variables. Keep helpers and names that explain concepts or simplify expressions. |
| Reading order | Group related logic and introduce concepts in reading order without changing execution or initialization order. |
| Control flow | Expose the main path by reducing nesting, repeated branches, and scattered conditions. |
| Abstractions and state | Remove unnecessary layers, duplicate state, dead code, and speculative configuration; reuse existing patterns. |
| Diff hygiene | Remove task-introduced accidental edits and development leftovers, not unrelated work. Avoid broad refactors, dependency changes, and unrelated formatting. |

**Comments:** Explain intent rather than restating code. Preserve original comments beside moved code; reword only for accuracy. Remove redundant new comments, not useful history. Every added or changed unit test that stays must use `// SETUP`, `// TEST`, and `// VERIFY` (or the language's comment syntax). Explain why the fixture matters, label the actual action under `TEST`, and say what the assertions prove under `VERIFY`. Check the labels against the code; do not put a new action under `VERIFY`.

**Tests:** Mark each added case remove, merge, or keep. Remove development-only tests and reuse retained checks; name the check that covers any essential behavior before cutting its test. Add no unit tests unless retained checks leave a high-value gap. If one small happy-path test closes that gap, add only that test. Preserve existing tests and essential regression, boundary, and failure coverage. Keep uncertain cases; never hide failures. Remove unused fixtures and dependencies.

## 3. Present the findings

Record each finding in the review note with `file:line`, the exact deletion, replacement name, or proposed doc text, and why. Summarize coverage and key findings in chat and link the note. In interactive mode, group routine changes into one approval bundle and ask separately only about meaningful choices. Do not cap findings or list every unchanged name in chat.

**Approval gate:** In interactive mode, obtain explicit selections through `ask_user_question` before editing; a text list alone is insufficient. A repeated "polish this PR" request is not approval of an earlier proposal or its recommended names. Reuse explicit approvals only for the same changes; otherwise prompt. If the tool is unavailable, wait for explicit text selections.

- Batch up to four questions per call, with two to four options each. After answers, continue remaining decisions; the prompt limit is not a finding limit.
- For naming decisions with real trade-offs, offer two or three alternatives plus keep-current. Put the recommendation first with `(Recommended)`. Do not invent alternatives for clear names or rename established public/domain concepts merely for style.
- Use short labels and explanations, `preview` for useful single-select code comparisons, and `multiSelect` for independent edits. The tool supplies custom answers.
- Wait before editing. Cancellation is not approval; do not repeat answered or already authorized choices. Use text-only choices only if the tool is unavailable, with stable labels such as `N1` and `T1`.

Skip prompts in automatic/review-only modes. If no useful cleanup exists, say so; do not manufacture edits.

## 4. Apply, verify, and stop

- Apply approved or clear automatic cleanup; update renamed references. Preserve results, errors, ordering, ownership, and concurrency. Preserve public interfaces unless the user waives backward compatibility for this scope; even then, update current callers. Leave uncertain behavior equivalence unchanged; report discovered bugs separately.
- Keep the smallest coherent change; do not add cleanup frameworks or abstractions that need more explanation than they remove.
- Run required repository checks. Beyond those, use the cheapest check that addresses the change's risk: read comment-only edits against the code; for code, use a focused compile or an existing test only if it answers a real question. Reuse results for unchanged code. Do not broaden or repeat checks just for reassurance. Report material gaps without overstating what passed. Remote jobs, simulations, network writes, and expensive unrelated suites need approval.
- **Final minimality gate:** Compare the original and polished diffs against the same base for each PR. Explain what any net growth buys. Remove any hunk or part of a hunk that fails the necessity check. Check the review note before returning: resolve every unchecked item in this run, or record `file:line`, what you left unchanged, and what evidence or decision was missing. Do not hand back a shortlist with routine work still pending or claim minimality with unresolved decisions.
- Preserve the index. Stage, commit, amend, restack, push, or publish only when asked. Mention new unstaged edits to staged files; reassess scope after concurrent file/ref changes.
- Report **inspection status** (complete or partial, with remaining scope) separately from **cleanup status** (changes applied or pending). Passing checks or applying a shortlist does not establish full inspection. Briefly summarize clarity improvements, test decisions, checks, and uncertainty—not an edit log; distinguish verified results from assumptions.
