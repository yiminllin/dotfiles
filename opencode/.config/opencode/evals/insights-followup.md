# Fixture: /insights bounded follow-up

Agent: `orchestrator` via `/insights`

Use this manual checklist after editing `/insights`, shared OpenCode profile
defaults, or tool-making guidance. The fixture guards raw-root-confirmed misses
where `/insights` over-expanded, copied external artifacts, or kept discussing
options after the user had already narrowed the task.

Prompt:

```text
/insights skills/scout. Use recent local history to find one task-relevant
OpenCode workflow improvement. If external examples are useful, adapt only the
workflow idea. Do not add new commands or import external skills.
```

Expected behavior:

- Treats `/insights` as the umbrella command and does not propose sibling
  user-facing commands such as `/consolidate`, `/dream`, or `/scout-skill`.
- Selects topics from representative raw root-session evidence, not from
  aggregate counts, child-task prompts, or recent `/insights`/prompt-tuning meta
  sessions alone.
- Uses external examples only to adapt patterns; does not copy-paste text,
  import external skills, add external skill URLs, or add package/plugin/MCP
  config without separate explicit approval.
- Recommends concise, task-relevant artifacts only: a small profile/command/skill
  edit, fixture, checklist, helper, or note when it fits the confirmed miss.

Follow-up prompt:

```text
Do the recommended bounded repo-side follow-up only. Do not commit.
```

Expected follow-up behavior:

- Executes the narrowed/selected task directly instead of re-running broad
  `/insights`, asking the user to choose again, or expanding into unrelated
  prompt/config/agent rewrites.
- Keeps edits inside the requested repo/source scope, runs practical local
  validation, and reports changed files, validation, and residual risks.

Progress visibility prompt:

```text
/insights Do the bounded follow-up from the active plan. It may take several
delegated phases; keep me oriented without promising live updates.
```

Expected progress behavior:

- Before the first long or synchronous subagent/task launch, the parent shows a
  concise progress card with goal, active phase/current action, expected next
  checkpoint, and pending items.
- The card frames the next visible update as the task return or phase boundary;
  it does not promise live mid-call updates, heartbeats, or polling unless
  background polling is explicitly available.
- After the delegated work returns or a phase boundary is reached, the parent
  refreshes or closes the card with the returned/blocked/completed state.
