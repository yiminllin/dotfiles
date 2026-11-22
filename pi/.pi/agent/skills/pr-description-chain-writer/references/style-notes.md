# PR Chain Style Notes

Use this as a flexible reviewer-friendly starting point for PR bodies in a stack, not a rigid shape:

1. Do a short finalization pass before posting:
   - Preserve title capitalization the user explicitly requested.
   - When drafting from commits, preserve commit title capitalization/style unless the user asks for a rewrite.
   - Preserve repository or user-supplied ticket prefixes, component tags and test-only markers.
   - Do not invent evidence links. Upload or link logs only when authorized.
2. Keep the repository template section order exactly:
   - `## Reason for Change`
   - `## Description of Change`
   - `## Criticality of Change`
   - `## Verification`
   - `## Release Notes`
3. Under `Reason for Change`, include:
   - The genuinely shared chain-level motivation. Preserve distinct existing reasons and explain per-PR effects in Description of Change.
   - Optional context link.
   - Default-on `PR Tree` list for stacks, with PR numbers only such as `- #123`, no PR titles or markdown links, and `◀` on the current PR as the only per-PR change in this section.
   - Include a verified tracking link below `PR Tree` when the repository uses one.
4. Put per-PR specifics in `Description of Change`:
    - A short prose lead (usually 1-2 sentences) is a good default when it clarifies what this PR changes.
    - Follow the selected brief, focused, or grouped structure in `../SKILL.md`. Use a comparison only when selected. Reuse verified explanations, not private review content.
    - Lead with the change. Use active verbs and verified source names. Keep snippets short and link to the implementation when useful.
    - Skip headings, captions, and bullets that restate another view.
    - Summarize generated, mechanical, or bulk churn instead of listing repetitive file edits.
    - Optionally add `### Map for Reviewers` for non-trivial PRs; skip it for tiny PRs. Use this public shape instead of dense reviewer-guide tables:
      - `**Suggested route**`: numbered 1-3 semantic areas.
      - `**Key checkpoints**`: concise bullets for main correctness, config, API, or frame points.
      - `**Context anchors**`: concise bullets for parent/child PRs, issue/design/discussion context, key evidence, or validator follow-up.
    - Optionally add `### Watchouts` only for real risk or follow-up; skip it when there is no meaningful risk. Keep bullets compact: `**Risk**: ...`, `**Mitigation**: ...`, `**Follow-up**: ...`.
    - Both sections are optional; skip `Map for Reviewers` for tiny PRs and skip `Watchouts` when there is no real risk or follow-up. Do not include emoji, deep/skim labels, suggested comments, private TODOs, or unresolved inspection questions in public PR bodies.
5. Keep the repository template order unchanged, and preserve each existing PR's repository template checkbox blocks for `Criticality of Change` and `Release Notes` instead of collapsing them to prose such as `L3 Nonfunctional`. Use known repo checklist blocks when available; otherwise copy/preserve the exact checklist shape from the current PR template or style reference. Before finalizing, verify checked states reflect reality for the PR.
6. Follow the checklist-first `Verification` contract in `../SKILL.md`.
7. Maintain backward-compatible escape hatches:
   - `--omit-pr-tree` when stacked context is unnecessary.
   - `--description-style prose` or `--description-style bullets` when the user explicitly wants a non-hybrid script draft.
   - Manually rewrite the generated draft into a diagram or table when that is clearer than prose/bullets.

## Fictional examples

- Replace “Plumb retry configuration into the worker” with “`start_worker` passes `max_retries` to `RetryQueue`.”
- Replace “The parser does not retry failed requests” with “`RetryQueue` retries failed requests,” if the handoff matters. Otherwise, omit the line.

Example Verification for a benchmark:

- [x] Search benchmark: median lookup time fell from 30 ms to 20 ms.

```bash
python -m benchmarks.lookup --items 10000 --seed 7
```

| Metric | Before | After |
|---|---:|---:|
| Median lookup time (ms) | 30 | 20 |
