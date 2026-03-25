---
name: pr-address-comments
description: Triage and address actionable GitHub PR review comments and bot feedback, especially Greptile-like suggestions, while escalating ambiguous, conflicting, or strategic feedback to the human. Use when the user wants focused help handling PR comments rather than full PR babysitting.
---

# PR Address Comments

## Overview

Handle unresolved PR feedback by fetching fresh comment state, separating clear local fixes from comments that need human judgment, implementing only the safe actionable items, and replying in the right thread.

This skill is intentionally narrow: it focuses on PR comments and review threads, not end-to-end PR driving, CI ownership, or merge-queue management.

This skill is standalone. It bundles its own helper scripts for fetching comment state and posting replies, so it does not depend on another PR-management skill.

## Guardrails

- Refresh comment state before acting; do not rely on stale snapshots.
- Ignore resolved inline threads. Treat outdated comments and threads as non-blocking unless they are still clearly relevant.
- Treat Greptile and similar bots as suggestion sources to verify, not instructions to obey.
- Only autonomously act on clear, local, low-ambiguity comments.
- Escalate ambiguous, conflicting, architectural, product, safety, or strategy comments to the human.
- When commenting on behalf of the user, start the comment with `__Comment by Robot__`.
- The bundled reply helper enforces the `__Comment by Robot__` prefix by default.
- Reply in-thread when possible, and only resolve a thread when the concern is actually addressed.
- Follow the repo's normal commit and push discipline if the user explicitly asks you to commit or push. Do not assume this skill owns the whole PR lifecycle.

## Workflow

### 1. Find the PR and verify GitHub access

- Ensure `gh` works:
  - `gh auth status`
- Resolve the PR:
  - Prefer the user-provided PR number or URL.
  - Otherwise use the current branch PR:
    - `gh pr view --json number,url,author,headRefName,baseRefName,isDraft,reviewDecision`

If `gh auth status` fails, stop and ask the user to run `gh auth login`.

### 2. Fetch unresolved comments and review context

Set `SKILL_DIR` to the absolute path of this skill directory (`<path-to-skill>` in the examples below).

Prefer the bundled helper script:

- Current branch PR:
  - `python "$SKILL_DIR/scripts/fetch_comments.py" > /tmp/pr_comments.json`
- Specific PR number or URL:
  - `python "$SKILL_DIR/scripts/fetch_comments.py" --pr "<number-or-url>" > /tmp/pr_comments.json`

Use the output conservatively:

- `review_threads_unresolved`: primary queue for unresolved inline review threads.
- `conversation_comments`: top-level PR comments.
- `reviews_active`: active review submissions.
- Ignore `review_threads_resolved` and `reviews_dismissed`.
- Treat `review_threads_outdated` and `review_comments_outdated` as informational unless the concern still applies.

If you need manual fallbacks for a specific PR:

- `gh pr view <pr> --comments`
- `gh api "repos/<owner>/<repo>/pulls/<pr_number>/reviews"`
- `gh api "repos/<owner>/<repo>/pulls/<pr_number>/comments?per_page=100"`

If you are working against a non-default GitHub host, add `--hostname <host>` to the `gh api` commands.

Important: these REST fallbacks are useful for content lookup, but they do not reliably expose review-thread resolution state. Do not use them alone to decide whether an inline thread is resolved or unresolved. If thread state matters, fetch `reviewThreads` through GraphQL before deciding what still needs action.

Number each unresolved item and capture:

- author/login
- `author_kind` / `author_type` from the fetch output
- file/line anchor if present
- `reply_target_id` for inline review threads
- concise request summary
- whether it looks actionable without human input

### 3. Triage each comment: actionable vs needs human input

Autonomously address a comment only when all of these are true:

- the requested change is specific and easy to restate
- the fix is local to the current diff or a small nearby code path
- the intent is low-ambiguity
- it does not conflict with other feedback
- it does not require product, architecture, safety, or performance-policy judgment
- you can verify the change by reading code and, when practical, running a focused check

Escalate to the human when any of these are true:

- reviewer intent is ambiguous or under-specified
- multiple reviewers appear to disagree
- the comment asks for a broader refactor or design change
- the comment changes product behavior or system boundaries
- the right answer depends on non-local context or team preference
- a bot claim looks questionable and the evidence is mixed

### 4. Treat Greptile and similar bots as hypotheses

- Verify the referenced code path before changing anything.
- Read the surrounding implementation and any nearby tests.
- Prefer small, evidence-backed fixes over broad speculative cleanup.
- If the bot is correct, fix the concrete issue.
- If the bot is partially right, address only the substantiated part.
- If the bot is wrong or not worth taking, reply with a short evidence-backed explanation instead of blindly changing code.

Examples that are usually safe to handle autonomously:

- missing or incorrect targeted test coverage
- obvious typo, naming, or doc fix
- small local simplification with clear reviewer intent
- narrow bug fix or edge-case handling that is directly supported by the comment and code context

Examples that usually need human input:

- “should this be a different abstraction?”
- “can we redesign this API instead?”
- “this seems risky, performance-sensitive, or product-sensitive” without a clearly mechanical fix
- conflicting bot and human feedback

### 5. Implement only the clear local fixes

- Work one actionable thread at a time.
- Search and read all touched definitions and usages before editing.
- Prefer the smallest coherent change that fully addresses the comment.
- Add or adjust targeted tests when the comment points to a bug, regression, or behavior edge.
- Run the narrowest relevant verification you can.
- If a supposedly simple comment expands into a design question, stop and escalate instead of guessing.

### 6. Reply in-thread and resolve when appropriate

Use the bundled reply helper:

- `python "$SKILL_DIR/scripts/reply_comments.py" --replies /tmp/replies.json --pr "<number-or-url>" --json`
- Add `--dry-run` first if you want to validate the payload.

For inline review threads, prefer the thread's `reply_target_id` from `fetch_comments.py` as `in_reply_to`.

Use `review_comment` replies for inline review threads. Use `issue_comment` only for top-level PR comments, since GitHub issue comments do not have true inline thread replies.

Example replies payload:

```json
{
  "replies": [
    {
      "kind": "review_comment",
      "in_reply_to": "PRRC_kw...",
      "resolve_thread_id": "PRRT_kw...",
      "body": "__Comment by Robot__\nAddressed by tightening the local validation path and adding targeted coverage for the failing edge case."
    },
    {
      "kind": "issue_comment",
      "body": "__Comment by Robot__\nAddressed the top-level feedback around test coverage in the latest local changes."
    }
  ]
}
```

Reply guidance:

- Start user-facing PR replies with `__Comment by Robot__`.
- Keep replies short, concrete, and tied to the actual fix or rationale.
- If you chose not to take a bot suggestion, explain why with code evidence.
- Resolve a review thread only when the concern is fully answered by the code change or explanation.
- If a comment has multiple asks and only some are done, reply but leave the thread unresolved.

### 7. Escalate non-mechanical feedback back to the human

When you hit ambiguous or strategic feedback, stop and give the user a compact decision prompt instead of guessing.

Use this format:

```text
Need human input on 2 PR comments:

1. [@reviewer, path:line] <one-line summary>
   Why I stopped: <ambiguity/conflict/strategy reason>
   Options: <A> | <B>
   Lean: <preferred option, if any>

2. [@reviewer or bot, path:line] <one-line summary>
   Why I stopped: <reason>
```

Keep the escalation focused on the decision that only the human can make.

### 8. Report completion and remaining blockers

At the end, summarize:

- which comments were addressed
- which threads or comments were replied to or resolved
- what verification you ran
- which comments still need human input

If the user wants more than comment handling after that, switch to a broader PR-management workflow.

## Resources

Bundled scripts available in this skill:

- `<path-to-skill>/scripts/fetch_comments.py`
- `<path-to-skill>/scripts/reply_comments.py`
