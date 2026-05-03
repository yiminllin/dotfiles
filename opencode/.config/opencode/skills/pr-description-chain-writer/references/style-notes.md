# PR Chain Style Notes

Use this as a flexible reviewer-friendly starting point for PR bodies in a stack, not a rigid shape:

1. Keep the repository template section order exactly:
   - `## Reason for Change`
   - `## Description of Change`
   - `## Criticality of Change`
   - `## Verification`
   - `## Release Notes`
2. Under `Reason for Change`, include:
    - The shared chain-level reason paragraph/context. For stacked PRs in one chain, keep this text identical across PRs.
    - Optional context link.
    - Default-on `PR Tree` list for stacks, with all PR numbers and `◀` on the current PR as the only per-PR change in this section.
3. Put per-PR specifics in `Description of Change`:
    - A short prose lead (usually 1-2 sentences) is a good default when it clarifies what this PR changes.
    - Use `In particular:` bullets, a diagram, a table, or a before/after comparison when that better explains the change.
    - Keep top-level bullet labels semantically useful rather than generic catch-alls.
    - Keep the content reviewer-focused: concrete behavior changes first, file/config listings second.
4. Keep the repository template order unchanged, but default `Criticality of Change` to `L3 Nonfunctional` and default `Release Notes` to unchecked unless reality differs.
5. In `Verification`, prefer concrete evidence over generic placeholders:
    - Use exact commands, Baraza/GHA links, concise run tables, or concrete manual results when available.
    - Avoid vague `CI` claims unless CI itself is the changed surface or the only meaningful evidence.
    - Do not leave raw generated verification placeholders in final PR text.
    - For manual tests, keep it concise: scenario/workflow name, relevant mode/environment only if it matters, short result, and links when useful.
    - Use an indented fenced `bash` block only when command details are the real verification evidence.
    - Avoid long prose or generic filler.
6. Prefer concrete identifiers in prose or bullets:
    - Types, flags, modes, or function names in backticks.
    - Specific files only when they help reviewers.
7. Maintain backward-compatible escape hatches:
    - `--omit-pr-tree` when stacked context is unnecessary.
    - `--description-style prose` or `--description-style bullets` when the user explicitly wants a non-hybrid script draft.
    - Manually rewrite the generated draft into a diagram or table when that is clearer than prose/bullets.
