---
description: Review OpenCode prompt insights with an approval gate
agent: orchestrator
---

Run the approval-gated `/insights` workflow for shared OpenCode prompts, skills, and workflow memory.

## Goal
- Review recent high-signal evidence about OpenCode behavior.
- Compare that evidence against the current prompt/config state and the active plan/design artifacts.
- Produce a concise summary plus 1-3 narrow proposals.
- Do not write any prompt or config file under `~/dotfiles` until the user explicitly approves the exact change for a specific proposal.

## Default scope
- Start narrow and prioritize `opencode/.config/opencode/agents/orchestrator.md`.
- Optionally consider `~/dotfiles/opencode/.config/opencode/user-profile.yaml` when the issue is a stable user preference rather than an orchestrator-specific behavior.
- If `$ARGUMENTS` is provided, treat it as a scope hint, but keep proposals narrow and approval-gated.

## Required references
- shared OpenCode plan/design artifacts under `~/notes/opencode/` when available
- if those shared artifacts have not been migrated yet, legacy shared OpenCode notes under `~/notes/projects/dotfiles/` may still be relevant as fallback references
- `opencode/.config/opencode/opencode.json`
- the current target prompt/profile file(s)

## Auto-collected recent local history
Start from this evidence summary before weighing the current session. If the sample is thin or unavailable, say so explicitly and stay conservative.

!`python3 "$HOME/.config/opencode/scripts/insights_history.py"`

## Workflow
1. Inspect the auto-collected recent local history first, then compare it with the current session, explicit user feedback, and relevant note artifacts.
2. Prefer the history summary's root-session follow-ups and other user-correction-like evidence over child-session task prompts. If evidence is weak, say so and either propose no change or ask for a better sample.
3. Classify findings with this lightweight taxonomy: routing, autonomy, verbosity, artifact usage, safety, output format.
4. Produce at most 1-3 proposals. Prefer additive wording tweaks or a small shared-profile change over broad rewrites.
5. For each proposal, include:
   - proposal id
   - observed problem
   - evidence snippets or references
   - exact target file(s)
   - proposed wording or diff sketch
   - expected behavior change
   - risks and confidence
6. Lead with analysis and proposals only. Do not apply edits yet.

## Approval gate
- Treat repo prompt/config writes under `~/dotfiles` as forbidden until the user has reviewed the exact proposed diff/change and then explicitly approved that exact change.
- `refine`, `reject`, `sounds good`, continued discussion, or approval of the analysis alone are not approval to write repo files.
- If the user says `approve <proposal-id>` before seeing an exact diff/change, treat that as a request to show the exact diff/change only; do not edit any repo file yet.
- After showing the exact diff/change, ask for a final confirmation such as `approve apply <proposal-id>` before making any repo edit.
- Before any approved edit, restate the exact target file(s), the exact diff/change being applied, and the validation plan.
- Only after that final approval should you delegate one bounded implementation task to `builder` or `yolo` to apply only the approved change and run verification.
- If the user rejects or continues refining, keep changes limited to analysis/proposal output and optional note artifacts under `~/notes/opencode/insights/` when persistence is helpful.

## Response contract
- First response after `/insights`:
  1. insight summary
  2. proposals (1-3)
  3. recommended next step
  4. reply options: `refine <proposal-id or focus>`, `reject <proposal-id or all>`, `show-diff <proposal-id>`
- Prefer chooser/dropdown-style reply options when available. Otherwise present short numbered options and accept compact replies (for example `1`, `2`, or `1+3`) instead of requiring exact command phrases.
- On `refine`: revise the proposal set or wording only; do not edit `~/dotfiles`.
- On `reject`: close the proposal and confirm that no repo prompt/config files were changed.
- On `show-diff`: present the exact diff/change plus the validation plan only; do not edit `~/dotfiles`.
- If the user says `approve <proposal-id>` before the exact diff/change is shown, treat it the same as `show-diff <proposal-id>`.
- After the exact diff/change is shown, require final confirmation such as `approve apply <proposal-id>` before any repo edit.
- On final approval: prepare a bounded handoff to `builder` or `yolo` with objective, approved diff scope, files, constraints, and validation steps; then execute that handoff.

## Constraints
- Keep the workflow orchestrator-first.
- Do not redesign multiple agents unless the user explicitly approves that expansion.
- Do not invent telemetry, background services, or hidden self-modifying behavior.
- Keep the workflow concise, evidence-based, and human-reviewable.

If there is no credible improvement to recommend, say so plainly and stop after the summary.
