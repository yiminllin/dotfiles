# PR Chain Style Notes

Use this as a flexible reviewer-friendly starting point for PR bodies in a stack, not a rigid shape:

1. Do a short finalization pass before posting:
   - Preserve title capitalization the user explicitly requested.
   - When drafting from commits, preserve commit title capitalization/style unless the user asks for a rewrite.
   - For ticketed Phoenix work, use `[FSW-#####] [Phoenix] ...`; add `[DNL]` for throwaway/test PRs when requested.
   - Ensure commit-derived PR titles or wording still follow requested `[FSW-#####] [Phoenix] ...` and `[DNL]` conventions.
   - Links are evidence: do not invent Baraza, S3, GHA, Jira, Slack, or log links, and upload/link logs only when requested or authorized.
2. Keep the repository template section order exactly:
   - `## Reason for Change`
   - `## Description of Change`
   - `## Criticality of Change`
   - `## Verification`
   - `## Release Notes`
3. Under `Reason for Change`, include:
   - The shared chain-level reason paragraph/context. For stacked PRs in one chain, keep this text identical across PRs.
   - Optional context link.
   - Default-on `PR Tree` list for stacks, with PR numbers only such as `- #123`, no PR titles or markdown links, and `◀` on the current PR as the only per-PR change in this section.
   - `Jira Ticket: [FSW-XXXXX](https://flyzipline.atlassian.net/browse/FSW-XXXXX)` directly below `PR Tree` when a ticket is known.
4. Put per-PR specifics in `Description of Change`:
   - A short prose lead (usually 1-2 sentences) is a good default when it clarifies what this PR changes.
   - Use `In particular:` bullets, a diagram, a table, or a before/after comparison when that better explains the change.
   - Keep top-level bullet labels semantically useful rather than generic catch-alls.
   - Keep the content reviewer-focused and low-jargon: feature/mechanism first, file inventory second.
5. Keep the repository template order unchanged, but default `Criticality of Change` to `L3 Nonfunctional` and default `Release Notes` to unchecked unless reality differs.
6. In `Verification`, prefer checked concrete evidence over generic placeholders:
   - Use `- [x] Manual Test [Baraza](...) [S3](...)`, exact commands, concise run tables, or concrete manual results when available.
   - Use one checked bullet per test or verification item.
   - Prefer Baraza and `[S3](...)` links over Aspect links or local paths when available.
   - Avoid vague `CI` claims unless CI itself is the changed surface or the only meaningful evidence.
   - Do not leave TODOs, empty query results, or raw generated verification placeholders in final PR text.
   - For manual tests, keep it concise: scenario/workflow name, relevant mode/environment only if it matters, short result, and links when useful.
   - Use a fenced `bash` block only when command details are real verification evidence.
   - Avoid long prose or generic filler.
7. Prefer concrete identifiers in prose or bullets:
   - Types, flags, modes, or function names in backticks.
   - Specific files only when they help reviewers.
8. Maintain backward-compatible escape hatches:
   - `--omit-pr-tree` when stacked context is unnecessary.
   - `--description-style prose` or `--description-style bullets` when the user explicitly wants a non-hybrid script draft.
   - Manually rewrite the generated draft into a diagram or table when that is clearer than prose/bullets.
