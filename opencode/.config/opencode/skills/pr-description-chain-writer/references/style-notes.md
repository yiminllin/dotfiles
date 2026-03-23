# PR Chain Style Notes

Use this shape for every PR body in a stack:

1. Keep the repository template section order exactly:
   - `## Reason for Change`
   - `## Description of Change`
   - `## Criticality of Change`
   - `## Verification`
   - `## Release Notes`
2. Under `Reason for Change`, include:
    - One short paragraph that leads with the concrete symptom/problem or reviewer pain point.
    - Prefer following with the mechanism/root cause this PR changes.
    - Optional context link.
    - Default-on `PR Tree` list for stacks, with all PR numbers and `◀` on the current PR.
3. Start `Description of Change` with:
    - A short prose lead (usually 1-2 sentences) that names what this PR changes.
    - Then `In particular:` followed by detailed nested bullets.
    - Keep top-level bullet labels semantically useful (for example: config resolution, graph/domain bring-up, inter-domain routing, validator guardrails, scenario plumbing) rather than generic catch-alls.
    - Keep the bullets reviewer-focused: concrete behavior changes first, file/config listings second.
4. Keep the repository template order unchanged, but default `Criticality of Change` to `L3 Nonfunctional` and default `Release Notes` to unchecked unless reality differs.
5. In `Verification`, prefer concrete evidence over generic placeholders:
    - Name the exact test, command, scenario, CI job, log, screenshot, or metric when possible.
    - Avoid generic `AB-compare with develop` filler as the fallback.
6. Prefer concrete identifiers in prose or bullets:
    - Types, flags, modes, or function names in backticks.
    - Specific files only when they help reviewers.
7. Maintain backward-compatible escape hatches:
    - `--omit-pr-tree` when stacked context is unnecessary.
    - `--description-style prose` or `--description-style bullets` when the user explicitly wants a non-hybrid shape.
