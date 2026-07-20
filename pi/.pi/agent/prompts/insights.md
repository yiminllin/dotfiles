---
description: Review Pi and dotfiles prompts, memory, skills, and workflow gaps
argument-hint: "[focus or path]"
---

Review the broad Pi/dotfiles workflow surface for prompt or config tuning,
durable memory cleanup, and reusable skill or helper gaps. Treat
`$ARGUMENTS` as an optional focus; `quick` means a smaller representative
sample with explicit evidence limits.

Work from current evidence:

- repository Pi source under `pi/.pi/agent/`, relevant callsites, guidance, and
  active plans or notes
- runtime `~/.pi/agent/` only when loading or source/runtime drift matters
- current-session or user-supplied correction/history evidence

Repo source and observed behavior outrank notes. Notes are routing memory, not
proof. Separate observations from proposals and identify the evidence, impact,
confidence, and smallest owning file for each useful finding. Do not infer broad
defaults from aggregate or indirect evidence alone.

Inventory existing prompts, skills, scripts, settings, and system guidance
before proposing a new surface. Review routing, scope, verbosity, artifacts,
memory use, safety boundaries, output contracts, validation, source/runtime
confusion, and deterministic-helper opportunities. Use `tool-maker` only after
this review narrows one concrete reusable workflow; do not duplicate behavior
already owned by an installed skill.

Do not assume subagents, orchestration, parallel workers, or background work.
Do not scout external sources unless explicitly requested; any network access
still requires approval after local inventory. For an implementation request,
apply only the requested bounded change and validate it offline where possible.

Use these exact final sections:

## Prompt/config findings
- Findings or `No credible change`.

## Memory consolidation
- Only durable actions. For a recurring miss, include: trigger, expected versus
  actual behavior, likely root habit and confidence, durable owner, and next
  decisive probe. Otherwise say `No consolidation needed`.

## Skill/workflow gaps
- Existing owner, narrow gap, or `No credible gap`. Include a small evaluation
  idea only when recommending a skill or prompt change.

## Recommended next action
- Give one default action. Add alternatives only when a real design choice
  remains; otherwise say `No change`.
