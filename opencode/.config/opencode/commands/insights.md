---
description: Review OpenCode prompt insights and recommend bounded improvements
agent: orchestrator
---

Run the `/insights` workflow for shared OpenCode prompts, skills, and workflow memory.

## Goal
- Review recent high-signal evidence about OpenCode behavior.
- Compare that evidence against the current prompt/config state and the active plan/design artifacts.
- Produce a concise summary plus a comprehensive list of credible narrow proposals surfaced by the evidence.
- Identify recurring reusable workflows or manual patterns that may be better converted into deterministic scripts/helpers instead of prompt-only guidance.

## Default scope
- Start from the overall last-month OpenCode behavior across repos, root sessions, child/subagent sessions, skills, PR/coding workflows, debugging workflows, and prompt-tuning workflows.
- Treat the aggregate history summary as a routing map, not as sufficient evidence by itself. Use it to identify dominant worktrees and workflow themes, then inspect representative raw root-session follow-ups before proposing changes.
- In the default workflow, explicitly include `/Systems`, `~/dotfiles`, and their recorded worktrees when present in the scan. Do not let recent `/insights` or prompt-tuning sessions dominate unless raw root-session evidence shows they are the main issue.
- After ranking evidence by confidence and actionability, keep target files narrow and prioritize `opencode/.config/opencode/agents/orchestrator.md` for orchestrator-specific behavior.
- Optionally consider `~/dotfiles/opencode/.config/opencode/user-profile.yaml` when the issue is a stable user preference rather than an orchestrator-specific behavior.
- If `$ARGUMENTS` is provided, treat it as a scope hint, but keep proposals narrow and bounded.

## Required references
- shared OpenCode plan/design artifacts under `~/notes/opencode/` when available
- if those shared artifacts have not been migrated yet, legacy shared OpenCode notes under `~/notes/projects/dotfiles/` may still be relevant as fallback references
- `opencode/.config/opencode/opencode.json`
- the current target prompt/profile file(s)

## Auto-collected recent local history
Start from this deterministic local evidence summary scanned across all local machine OpenCode history before weighing the current session. Counts/category signals come from the full requested scan while displayed examples may be truncated. The helper defaults to `$HOME/.local/share/opencode/opencode.db`; if the script is unavailable, do not grep/search for the history database path, and instead use that path or an explicit `--db-path` for a bounded read-only SQLite scan. If neither can be inspected, say so explicitly and stay conservative.

!`python3 "$HOME/.config/opencode/scripts/insights_history.py" --scope all`

Additional bounded helper modes are available when needed:

```sh
python3 "$HOME/.config/opencode/scripts/insights_history.py" --mode raw-corrections --scope worktree --worktree "$PWD" --followup-examples 5
python3 "$HOME/.config/opencode/scripts/insights_history.py" --mode latency --scope all --followup-examples 5 --session-examples 5
python3 "$HOME/.config/opencode/scripts/insights_history.py" --mode tool-patterns --scope all --followup-examples 5
python3 "$HOME/.config/opencode/scripts/insights_history.py" --scope all --since "2026-05-31T00:00" --write-cache /tmp/opencode-insights-cache.json
python3 "$HOME/.config/opencode/scripts/insights_history.py" --scope all --since-cache /tmp/opencode-insights-cache.json
```

## Workflow
1. Inspect the auto-collected recent local history first, then compare it with the current session, explicit user feedback, and relevant note artifacts. Do not recursively delegate this same `/insights` request back to `orchestrator` or re-run `/insights` as a substitute for the local history script/bounded DB scan.
2. Perform a raw-history correction pass before drafting proposals:
   - Identify dominant non-trivial worktrees and themes from the aggregate summary.
   - Inspect representative raw root-session follow-ups from those worktrees, prioritizing user corrections, repeated follow-up questions, and workflow-specific requests.
   - Prefer root-session follow-ups and other user-correction-like evidence over child-session task prompts.
   - Treat child/subagent prompts as workflow context unless independently supported by root user messages.
   - Raw evidence from the current session, explicit user corrections, or current worktree root follow-ups overrides aggregate category hints when they conflict.
   - Do not let aggregate/meta categories dominate concrete current-session evidence; use aggregate categories to find where to inspect, not to overrule the inspected raw messages.
   - Downweight recent `/insights`/prompt-tuning meta sessions unless they remain dominant after the raw worktree review.
   - Use `insights_history.py --mode raw-corrections` when worktree matching or aggregate/raw disagreement is in question; it checks both `project.worktree` and `session.directory/path`.
   - If raw evidence cannot be inspected, say so explicitly and keep proposals conservative.
3. Build a broad behavior model across recent history, including:
   - routing and subagent selection patterns
   - autonomy vs clarification behavior
   - validation and evidence-reporting habits
   - artifact and memory usage
   - safety and runtime permission boundaries
   - output format and verbosity
   - coding-style, PR-review, and subagent-improvement feedback when present in recent history
   - recurring domain workflows, such as PR chains, PR review comments, stacked branches, Jira ticket updates, Phoenix/HIL/SIL debugging, config/stow validation, and dotfiles review UI work
   - recurring deterministic helper/script opportunities; use `--mode tool-patterns` when repeated command/tool payloads may justify a narrow helper/script instead of prompt wording
   - latency or time-sink patterns when the user mentions speed, thrash, repeated corrections, slow tool use, subagent fanout, or model/reasoning settings
   - When latency is in scope, use `insights_history.py --mode latency` if local history is available and explicitly label model-setting evidence as `supported`, `weak`, or `absent` rather than implying configuration causality from timing alone.
   - Classify expected slow helpers, bounded long commands, stale runtime-history entries, and trailing subagent completions separately from behavior problems; do not let delegation tail noise inflate conclusions unless raw root follow-ups show user impact.
4. Classify findings with this lightweight taxonomy: routing, autonomy, verbosity, artifact usage, safety, output format, validation.
5. Screen candidate improvements before recommending prompt/workflow changes: separate raw observations from candidates, label candidates as `narrow`, `duplicate`, and/or `high-risk` when applicable, and record frequency, impact, false-positive risk, and first-edit location. Shared prompt/profile edits should have raw-root evidence or explicit current-session/user approval, not aggregate counts alone.
6. Produce a comprehensive list of credible narrow proposals surfaced by the evidence, grouped or ordered by confidence and actionability. Prefer additive wording tweaks or a small shared-profile change over broad rewrites; do not cap the proposal list at three.
   - Lead with proposals derived from recurring real workflows across the dominant worktrees, not with `/insights` mechanics.
   - Put `/insights`-specific fixes in a separate subsection unless `/insights` is clearly the dominant issue in the raw worktree evidence.
   - When evidence shows repeated command sequences, data extraction, formatting, or validation steps, consider a narrow script/helper proposal as an alternative to changing agent wording.
7. For each proposal, include:
   - proposal id
   - observed problem
   - evidence snippets or references
   - exact target file(s)
   - first-edit location and false-positive/high-risk notes when relevant
   - proposed wording or diff sketch
   - expected behavior change
   - risks and confidence
   - evidence class: `raw-root-confirmed`, `aggregate-supported`, `artifact-supported`, or `inferred/downweighted`
   - if applicable, whether this is better as prompt guidance, a deterministic script/helper, or both
8. Lead with analysis and proposals unless the user requests a bounded implementation. For implementation requests, apply only the requested narrow change, run validation, and report the result.

## Implementation and reporting
- Use normal OpenCode edit permissions for prompt/config file changes, while honoring active runtime safety rules, explicit user constraints, and configured tool boundaries.
- Do not add boilerplate approval prompts unless the user explicitly asks for approval-gated review.
- Before a bounded edit, restate the target file(s), intended change, and validation plan when doing so adds clarity.
- For shared prompt/profile edits, cite the raw-root evidence, explicit user approval, or plan artifact that justifies the edit; if only aggregate evidence exists, propose rather than implement.
- After edits, report files changed, validation results, and any material caveats.
- If the user rejects or continues refining, keep changes limited to analysis/proposal output and optional note artifacts under `~/notes/opencode/insights/` when persistence is helpful.

## Response contract
- First response after `/insights`:
  1. insight summary
  2. raw workflow evidence summary by dominant worktree/theme, including representative root follow-ups or clear caveats if raw evidence was unavailable
  3. corrected comprehensive proposal list, led by broad workflow-derived OpenCode improvements and with `/insights`-specific fixes separated
  4. deterministic helper/script opportunities
  5. recommended next step
- Prefer chooser/dropdown-style next-step options when useful. Otherwise present short numbered options and accept compact replies (for example `1`, `2`, or `1+3`) instead of requiring exact command phrases.
- On `refine`: revise the proposal set or wording.
- On `reject`: close the proposal.
- On implementation requests: prepare a bounded handoff to `builder` or `yolo` with objective, edit scope, files, constraints, and validation steps; then execute that handoff.

## Constraints
- Keep the workflow orchestrator-first.
- Do not redesign multiple agents unless the user explicitly approves that expansion.
- Do not invent telemetry, background services, or hidden self-modifying behavior.
- Keep the workflow concise, evidence-based, and human-reviewable.

If there is no credible improvement to recommend, say so plainly and stop after the summary.
