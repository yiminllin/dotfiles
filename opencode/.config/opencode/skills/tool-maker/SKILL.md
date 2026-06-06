---
name: tool-maker
description: Turn repeated OpenCode workflows into the right reusable tool: skill, command, script/helper, agent prompt, profile/config change, or MCP integration. Use when asked to create, evaluate, improve, adapt, or compare one specific OpenCode skill or candidate workflow, or decide how to package repeated behavior.
---

# Tool Maker

## Purpose

Create and tune reusable OpenCode workflow tools using small, realistic evaluations and reviewable edits.

This is narrower than `/insights`: `/insights` mines broad OpenCode history for prompt/config improvement opportunities, while `tool-maker` turns a known workflow or candidate source into one concrete reusable tool and checks whether it behaves better than the baseline.

## When to use

- The user asks to create, update, evaluate, optimize, adapt, or compare one OpenCode skill or candidate workflow.
- The user asks whether repeated OpenCode behavior should become a skill, command, script/helper, agent prompt, profile/config change, or MCP integration.
- The user provides a public skill/prompt/workflow and asks to adapt it into this repo.
- The user brings one candidate from `/insights` scout mode or asks for a bounded comparison of one small candidate set.
- The user wants baseline-vs-candidate checks for a skill change.

Do not use this for broad prompt-tuning discovery or open-ended external scouting; use `/insights` first when the target workflow is unknown or the user wants `skills/scout`.

## Guardrails

- Keep the scope to one skill or one small candidate set.
- Do not add plugins, MCP servers, package installs, or scripts unless explicitly requested as a separate implementation task.
- For prompt/config/skill edits, propose exact diffs and apply them only after user approval unless the user explicitly asked to implement that specific change.
- Adapt public sources by extracting the useful workflow pattern; do not copy large proprietary, license-unclear, or repo-irrelevant text verbatim.
- Do not add external skill URLs, background hooks, package/plugin/MCP config, or direct imports without separate explicit approval.
- Follow `user-profile.yaml`: small reviewable changes, lean validation, direct top-down structure, and final cleanup for nontrivial edits.

## Workflow

### 1. Scope the reusable workflow

- Identify the target workflow, trigger phrases, intended users, and expected outputs.
- Capture non-goals and safety boundaries.
- Check for existing overlapping skills, commands, scripts/helpers, agents, profile/config defaults, and orchestrator routing before proposing a new artifact.
- For dotfiles-stowed OpenCode work, distinguish source under `opencode/.config/opencode/` from runtime-loaded files under `~/.config/opencode/` when behavior or loading matters.
- Decide the right home: skill vs command vs script/helper vs agent prompt vs profile/config vs ordinary docs vs MCP.

A workflow is a good skill candidate when it is repeatable, specialized, tool- or context-aware, easy to trigger from user intent, and benefits from an operational checklist.

Anti-rationalization checks before creating a skill:

- Is this a repeated specialized workflow, not just a one-off preference?
- Does an existing command, agent, skill, helper, note, or profile default already cover it?
- Would a deterministic helper/script, docs/notes, or one profile line be simpler?
- Does the skill improve trigger precision without bloating common prompts?
- Are negative cases, approval boundaries, and prohibited actions clear enough to prevent over-triggering?

### 2. Choose the right artifact

Use the smallest durable form that fits the workflow:

| Artifact | Use when | Avoid when |
|---|---|---|
| Skill | Repeatable judgment/workflow with domain procedure, tool boundaries, or output contract | It is only a shortcut command or deterministic parsing task |
| Command | User-facing shortcut for invoking a known OpenCode flow | It needs substantial reusable instructions or resources |
| Script/helper | Deterministic command sequence, parsing, extraction, validation, or formatting | Human judgment or tool-routing decisions dominate |
| Agent prompt | Stable specialist behavior, permissions, or model settings are needed | A load-on-demand skill is enough |
| Profile/config | Cross-agent preference, routing default, permission, or style rule | It applies only to one workflow |
| MCP/tool service | Stable multi-operation external service/API integration with shared auth, state, discovery, or structured tool outputs | A local script gives enough reliability and reuse |
| Docs/notes | Durable explanation or operator memory | The agent must execute the workflow repeatedly |

Default to skill or script before MCP. Promote to MCP only when scripts stop scaling because tool discovery, shared auth/state, typed outputs, or multiple clients matter.

### 3. New skill intake

Collect only what is needed:

- use cases and non-use cases
- required inputs and optional hints
- step-by-step workflow
- approval gates and tool boundaries
- output format
- lightweight validation plan

Draft `SKILL.md` with valid YAML frontmatter:

```yaml
---
name: <kebab-case-name>
description: <action-oriented description with when-to-use trigger>
---
```

Skill anatomy standard:

- Frontmatter has `name` and an action-oriented `description` that says when to trigger the skill.
- Body starts with purpose and when-to-use/non-use cases.
- Guardrails name approval boundaries, tool/source limits, and prohibited actions.
- Workflow is step-by-step and ends with the smallest useful output contract.
- Eval/validation guidance uses realistic prompts and avoids ceremony for tiny edits.

Keep the body practical and compact. Avoid generic style defaults that already live in `user-profile.yaml`.

### 4. Improve an existing skill

- Read the current `SKILL.md`, related orchestrator routing, relevant command/agent prompts, and any local notes the user points to.
- Identify the smallest behavior gap: trigger precision, missing step, unclear guardrail, weak output format, or validation gap.
- Patch the skill instructions directly around that gap; avoid broad rewrites.
- Remove redundant text introduced by the change before handoff.

Lightweight registry/inventory guidance:

- Track enough to avoid overlap: skill purpose, trigger phrases, owner path, related command/agent/profile text, eval prompts, and last meaningful review when useful.
- Inventory source skills and runtime-loaded skills separately when behavior differs; do not assume stowed source has already been loaded by the running OpenCode session.
- Use the inventory to update an existing artifact before creating a new one unless the trigger/workflow boundary is genuinely distinct.

### 5. Adapt a public skill pattern

- Inspect the source for reusable workflow shape, not phrasing to copy.
- Map external assumptions to this repo's tools, permissions, agents, and style.
- Drop irrelevant vendor-specific machinery, plugin installers, broad marketplaces, and unsupported integrations.
- Note provenance briefly when useful.
- Validate the adapted skill against local trigger phrases and expected outputs.

### 6. Candidate scouting follow-up

Use after `/insights` internal `skills/scout` mode or when the user explicitly provides a bounded candidate set.

1. Inventory local workflow, existing skills/tools, and relevant history/artifacts first.
2. Use external sources to identify patterns; do not copy text directly.
3. Sample only enough implementation/docs/examples to judge local fit.
4. Classify each candidate:
   - adapt pattern into existing artifact
   - create local skill
   - create helper/script
   - capture docs-or-notes only
   - skip or defer
5. Prioritize by workflow fit, repeatability, overlap, setup cost, safety/permission impact, maintenance burden, and validation path.
6. Recommend a small next action, usually one candidate, one local improvement, or one bakeoff.

Keep scouting output concise per candidate, but do not hide credible options when the user asks for comprehensive coverage.

### 7. Design eval prompts

Use a small realistic prompt set, usually 3-8 prompts:

- positive happy path where the skill should load
- negative boundary where it should not load
- ambiguous request that should ask one clarifying question
- approval-gated edit or external-boundary request when relevant
- historical prompt from local OpenCode history when available and representative

For each prompt, define expected routing, key workflow steps, output shape, and any prohibited behavior.

### 8. Compare baseline vs candidate

- Capture the current baseline behavior or instructions before editing.
- Run or reason through the same eval prompts against baseline and candidate.
- Score only practical criteria: trigger precision, workflow completeness, safety/approval handling, output usefulness, and instruction bloat.
- Prefer the candidate only when it improves meaningful behavior without adding low-value complexity.

### 9. Edit, validate, and clean up

- Present the exact diff first when approval is required.
- After approval or explicit implementation request, apply the narrow patch.
- Validate YAML frontmatter and search for skill routing references.
- Check that orchestrator routing is not duplicated or conflicting.
- For OpenCode prompt/config/agent/skill/command source edits under `opencode/.config/opencode/`, report that OpenCode must be quit and restarted before runtime behavior changes can be observed.
- Final cleanup: trim redundant prose, speculative guardrails, unsupported tools, stale names, and unrelated scope.

## Output format

Use the relevant subset:

```markdown
Outcome: <created | improved | evaluated | not a skill candidate>

Artifact decision:
- <skill | command | script/helper | agent prompt | profile/config | MCP | docs/notes | no new artifact>
- <why this is the right form>

Proposed/applied changes:
- `<path>`: <summary>

Candidate scouting:
- <candidate>: <adapt pattern | local skill | helper/script | docs-or-notes | skip | defer> — <why>

Eval prompts/results:
- <prompt>: <baseline> -> <candidate/result>

Validation:
- <checks run and result>

Runtime note:
- <restart caveat for OpenCode source config edits, when applicable>

Remaining risks/assumptions:
- <concise uncertainty or none>
```
