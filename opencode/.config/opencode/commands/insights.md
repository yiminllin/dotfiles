---
description: Review OpenCode prompt, memory, and skill workflow insights
agent: orchestrator
---

Run the unified `/insights` workflow for shared OpenCode prompts, config,
memory, skills, and reusable workflow opportunities.

## Contract

`/insights` is the single umbrella command. Do not split it into sibling
commands such as `/consolidate`, `/dream`, or `/scout-skill`.

Every final `/insights` answer must use these stable sections:

1. **Prompt/config findings**
2. **Memory consolidation**
3. **Skill/workflow gaps**
4. **Recommended next action**

Do not include a final `Progress Pin` by default. Use progress/status blocks
only for long-running scans, stuck/status updates, or explicit user requests.

## Focus modes via `$ARGUMENTS`

Treat `$ARGUMENTS` as a scope hint, not a separate command surface:

- `memory`, `consolidate`: emphasize note schema, stale/duplicate memory, and
  failure-reflection packets.
- `skills`, `skill quality`: emphasize skill anatomy, overlap, registry,
  routing, and prompt eval quality.
- `external skills`, `scout`, `skills/scout`: run the internal external-scout
  mode described below.
- `quick`: inspect a smaller representative sample and label evidence limits.
- `latency`, `tool patterns`, or a repo/worktree/path: narrow the history helper
  mode or raw-evidence pass while preserving the stable response sections.

## Required references

- shared OpenCode plan/design artifacts under `~/notes/opencode/` when relevant
- fallback legacy shared OpenCode notes under `~/notes/projects/dotfiles/` only
  when migration status is relevant
- stowed source config under `opencode/.config/opencode/`
- runtime config under `~/.config/opencode/` when behavior/loading matters
- the current target prompt/profile/skill/agent file(s)

Notes are routing memory, not proof. Repo source, runtime config, command output,
and raw user-session evidence win when they conflict.

## Auto-collected recent local history

Start from this deterministic local evidence summary scanned across local
OpenCode history before weighing the current session. Treat aggregate history as
a routing map: use it to choose representative raw evidence to inspect, not as
sufficient evidence for broad prompt/profile proposals.

The helper defaults to `$HOME/.local/share/opencode/opencode.db`; if the script
is unavailable, do not grep/search for the history database path. Use that path
or an explicit `--db-path` for a bounded read-only SQLite scan. If neither can
be inspected, say so and stay conservative.

!`python3 "$HOME/.config/opencode/scripts/insights_history.py" --scope all`

Additional bounded helper modes are available when needed:

```sh
python3 "$HOME/.config/opencode/scripts/insights_history.py" --mode raw-corrections --scope worktree --worktree "$PWD" --followup-examples 5
python3 "$HOME/.config/opencode/scripts/insights_history.py" --mode raw-corrections --scope worktree --worktree "/Systems/FlightSystems" --followup-examples 5 --session-examples 3
python3 "$HOME/.config/opencode/scripts/insights_history.py" --mode raw-corrections --scope worktree --worktree "$HOME/dotfiles" --followup-examples 5 --session-examples 3
python3 "$HOME/.config/opencode/scripts/insights_history.py" --mode latency --scope all --followup-examples 5 --session-examples 5
python3 "$HOME/.config/opencode/scripts/insights_history.py" --mode tool-patterns --scope all --followup-examples 5
python3 "$HOME/.config/opencode/scripts/insights_history.py" --scope all --since "2026-05-31T00:00" --write-cache /tmp/opencode-insights-cache.json
python3 "$HOME/.config/opencode/scripts/insights_history.py" --scope all --since-cache /tmp/opencode-insights-cache.json
```

## Workflow

1. Inspect the auto-collected history, `$ARGUMENTS`, the current session, and
   relevant note artifacts. Do not recursively delegate this same `/insights`
   request back to `orchestrator` or re-run `/insights` as a substitute for the
   local history script/bounded DB scan.
2. Perform a raw-evidence correction pass before proposals:
   - Identify dominant non-trivial worktrees and themes from the aggregate map.
   - Inspect representative raw root-session follow-ups from those worktrees,
     prioritizing user corrections, repeated follow-up questions, and explicit
     workflow requests.
   - Prefer root-session user evidence over child/subagent task prompts.
   - Downweight recent `/insights` or prompt-tuning meta sessions unless raw
     root evidence shows they are the main issue.
   - If raw evidence cannot be inspected, say so and keep proposals conservative.
3. Build findings across routing, autonomy, verbosity, artifact/memory use,
   safety, output format, validation, source-vs-runtime confusion, latency, and
   deterministic helper/script opportunities.
4. Screen candidates before recommending changes: separate observations from
   proposals; label frequency, impact, false-positive risk, first-edit location,
   and evidence class (`raw-root-confirmed`, `aggregate-supported`,
   `artifact-supported`, or `inferred/downweighted`). Shared prompt/profile
   edits need raw-root evidence, explicit user approval, or an active plan—not
   aggregate counts alone.
5. Keep target files narrow. Prefer additive wording or a small shared-profile
   default over broad rewrites. Use `tool-maker` only after `/insights` has
   narrowed one concrete reusable workflow or candidate artifact.

## Memory consolidation guidance

Use note-based memory only when it will improve future behavior. Do not write a
new note for every review or conversational proposal.

Suggested memory schema for durable OpenCode notes:

- `Context`: workflow, repo/source path, runtime path if different, date range.
- `Memory kind`: `episodic` for concrete events/corrections, `semantic` for
  stable facts/preferences, or `procedural` for reusable workflows/steps.
- `Observed failure or habit`: user-visible symptom or repeated correction.
- `Evidence`: raw root-session snippets, commands, artifacts, or links; include
  what the evidence does not prove.
- `Decision/default`: prompt/profile/skill behavior to preserve.
- `Owner`: command, agent, skill, profile, helper, or docs/notes.
- `Consolidation status`: active, superseded, duplicate, stale, or rejected.
- `Confidence/staleness`: confidence level and stale signal when scoped.
- `Review trigger`: what future signal should refresh or remove this memory.

Use the memory kind to decide the durable home: event/correction notes,
stable-preference/profile defaults, or reusable workflow/skill/helper guidance.

When a run exposes a reusable miss, include a compact failure-reflection packet
in **Memory consolidation** instead of overfitting prompt text immediately:

- `Trigger`: what the user asked or corrected.
- `Expected behavior`: what should have happened.
- `Actual behavior`: what happened.
- `Root habit`: likely workflow/prompt gap, with confidence.
- `Durable home`: profile, command, agent, skill, helper, or note.
- `Next probe`: one check that would confirm whether this is recurring.

## Skill/workflow quality spine

When skills are in scope, inventory local sources before proposing changes:

- stowed source skills under `opencode/.config/opencode/skills/`
- runtime skills under `~/.config/opencode/skills/` when loading behavior matters
- repo/system/global skill roots exposed by the current OpenCode session
- orchestrator routing text and any related command/agent prompt

Evaluate skill candidates against the shared skill-quality defaults from
`user-profile.yaml` and `skills/tool-maker/SKILL.md`: concise anatomy,
trigger/non-trigger clarity, overlap, bloat, safety boundaries, and a 3-8 prompt
eval/checklist with positive and negative prompts.

## Internal external-scout mode

Only run external scouting when `$ARGUMENTS` explicitly asks for `scout`,
`skills/scout`, or `external skills`.

1. Inventory local skills/tools/notes and current workflow gaps first.
2. Use external sources only to identify workflow patterns, not text to copy.
3. Classify each candidate as: adapt pattern, local skill, helper/script,
   docs-or-notes, skip, or defer.
4. Recommend at most one concrete `tool-maker` follow-up candidate unless the
   user asks for comprehensive scouting.
5. Do not add package/plugin/MCP config, external skill URLs, background hooks,
   or direct imports without separate explicit approval.

## Response contract

Use the stable section names exactly:

```md
## Prompt/config findings
- <finding/proposal with evidence class, target file, risk/confidence>

## Memory consolidation
- <memory action, schema note, or failure-reflection packet>

## Skill/workflow gaps
- <skill/helper/workflow gap, inventory note, eval idea, or scout classification>

## Recommended next action
1. <default recommendation>
2. <optional alternative>
```

If there is no credible improvement, say so plainly in the relevant section and
make the recommended next action `No change` or one narrow follow-up inspection.
Otherwise, provide 2-4 concise choices with one clear default recommendation.

For implementation requests, apply only the requested bounded change, run
validation, and report files changed, validation results, and material caveats.
For OpenCode prompt/config/agent/skill/command edits under
`opencode/.config/opencode/`, state that OpenCode must be quit and restarted
before runtime behavior changes can be observed.
