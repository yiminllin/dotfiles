---
name: pr-address-comments
description: Triage and address existing GitHub PR review comments or bot feedback supplied inline, in a saved file, or retrieved from GitHub on explicit request. Use for focused handling of existing feedback, not discovering new review issues, creating private review guides or notes, or full PR management.
---

# PR Address Comments

## Purpose

Handle existing PR feedback in one of two modes:

1. **Local snapshot mode (default):** triage comments supplied in the prompt or a local saved file. Do not access GitHub, a provider API, the network, or authentication.
2. **Live GitHub mode (explicit only):** retrieve current GitHub comment state only when the user explicitly requests it and approves the required network/auth access.

This skill handles feedback already raised by reviewers or bots. It does not discover new review issues, create private review guides or new review notes (`pr-human-review-guide`), or manage the full PR lifecycle.

Triage first. Do not edit code, post replies, resolve threads, commit, or push unless the user separately asks or approves the specific action.

## Guardrails

- Default to local snapshot mode. Supplied snapshots may be incomplete or stale; label that limitation rather than refreshing them.
- In local mode, read only the supplied prompt content or named local file. Do not invoke `gh`, provider tools/APIs, network access, or auth checks.
- Enter live mode only after an explicit request and approval for GitHub access. If permission is absent or unclear, stop and ask; never start or repair authentication.
- Require a PR number, URL, or current-branch lookup only in live mode. Local snapshots need no PR identifier.
- Require fresh state only in live mode. Never reject a local snapshot merely because it is not current.
- Treat bot feedback as a hypothesis. Verify claims against local code before recommending or making changes.
- Escalate ambiguous, conflicting, architectural, product, safety, performance-policy, or strategic feedback.
- GitHub writes require separate explicit approval of the exact replies and resolutions. Prefix posted comments with `__Comment by Robot__`.
- Never commit or push unless separately requested.

## Workflow

### 1. Select the mode

Use **local snapshot mode** when comments are included in the prompt or the user names a saved file. State that no provider state will be refreshed.

Use **live GitHub mode** only when the user explicitly asks to fetch or refresh comments from GitHub. Before any provider action:

- obtain network/auth approval
- obtain a PR number or URL, or approval to resolve the PR from the current branch
- stop at any permission boundary rather than attempting access

### 2. Acquire existing feedback

#### Local snapshot mode

- Parse only the supplied inline content or saved file.
- Preserve available author, thread, path/line, status, and identifier fields.
- Do not infer unresolved/resolved or current/outdated state when the snapshot does not establish it.

#### Live GitHub mode

After approval, use the bundled helper:

```text
python "$SKILL_DIR/scripts/fetch_comments.py" --pr "<number-or-url>" > /tmp/pr_comments.json
```

For an approved current-branch lookup, omit `--pr`. If `gh` or authentication is unavailable, ask the user to install or authenticate it; do not run login or auth-refresh commands.

Use unresolved review threads as the primary queue. Ignore resolved threads, and treat outdated feedback as informational unless it still applies.

### 3. Triage before editing

Number each item and report:

- author and file/line when available
- concise request
- classification: `actionable`, `needs human input`, or `insufficient snapshot context`
- evidence and proposed next action

Classify feedback as actionable only when its intent is specific, local, non-conflicting, and verifiable without product, architecture, safety, or strategy judgment. Read the referenced implementation and nearby tests before accepting reviewer or bot claims.

Return the triage without edits unless the user already asked for implementation. If implementation was not requested, ask which actionable items to address.

### 4. Implement approved fixes

- Work one approved item at a time.
- Search and read touched definitions and usages before editing.
- Make the smallest coherent fix within the PR boundary.
- Add tests only for a real regression, tricky behavior, or public contract.
- Run the narrowest practical verification and stop if a local fix expands into a design decision.

### 5. Draft or post replies

Drafting replies is local and does not authorize posting. Keep drafts short and evidence-based.

Only after showing the exact writes and receiving explicit GitHub-write approval, post with the bundled helper:

```text
python "$SKILL_DIR/scripts/reply_comments.py" --replies /tmp/replies.json --pr "<number-or-url>" --json
```

Reply in-thread when possible. Resolve a thread only when its full concern is addressed; otherwise leave it unresolved.

## Output

Report concisely:

- mode used and input source
- triage classifications and human decisions needed
- approved fixes made and verification run
- replies/resolutions as `draft only`, `updated`, or `not updated`
- provider evidence or blockers only when live access or writes were attempted

## Resources

- `<path-to-skill>/scripts/fetch_comments.py`
- `<path-to-skill>/scripts/reply_comments.py`
