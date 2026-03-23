# PR Chain Style Notes

Use this shape for every PR body in a stack:

1. Keep the repository template section order exactly:
   - `## Reason for Change`
   - `## Description of Change`
   - `## Criticality of Change`
   - `## Verification`
   - `## Release Notes`
2. Under `Reason for Change`, include:
   - One short shared paragraph for chain context.
   - Optional context link.
   - `PR Tree` list with all PR numbers and `◀` on the current PR.
3. Start `Description of Change` with:
   - `This PR ... In particular:`
   - Flat-to-nested bullets grouped by change area.
   - Prefer compact structure: 3-5 top-level bullets, each with 1-3 sub-bullets.
4. Keep criticality/verification/release-notes wording aligned across the chain unless a PR truly differs.
5. Prefer concrete identifiers in bullets:
   - Types, flags, modes, or function names in backticks.
   - Specific files only when they help reviewers.
