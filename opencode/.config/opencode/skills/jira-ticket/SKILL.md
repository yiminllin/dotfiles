---
name: jira-ticket
description: Create and update concise Jira tickets using the Jira CLI, especially Phoenix Simulation tickets. Use when asked to create a Jira ticket, update a Jira description, move ticket status, link Jira tickets, or add ticket update comments.
---

# Jira Ticket

## Overview

Use the Jira CLI to create and update short, readable Jira tickets.

This skill is optimized for Phoenix Simulation work:

- new ticket summaries are prefixed with `[Phoenix]` and use Title Case after the prefix, e.g. `[Phoenix] Add Prod-Nav Ideal Sensor Diagnostics`
- component is set to `Phoenix`
- team is set to `Simulation`
- default to high-level work-item grouping rather than one Jira ticket per PR unless the user asks for per-PR tickets
- assign Phoenix tickets to `Yimin Lin` by default unless the user says otherwise
- descriptions stay concise and skim-friendly

Do not turn Jira tickets into design docs. Link to design docs, PRs, Slack threads, logs, simulations, and dashboards instead of pasting long details.

## Local Jira Helpers

The user already has fish helpers/abbreviations:

- `jl`: list active personal Jira issues
- `jm`: move issue to arbitrary status
- `jms`: move to `Select for Development`
- `jmp`: move to `In Progress`
- `jmr`: move to `In Review`
- `jmd`: move to `Done`
- `je`: edit issue description through `nvim`
- `jc`: add comment through `nvim`
- `jn`: create Phoenix ticket

Important: fish abbreviations expand interactively, so agents should usually call the underlying `jira` commands directly unless operating in an interactive fish shell.

## Interaction Style

Prefer prompting the user with choices instead of open-ended questions.

Guidelines:

- Ask for one section or decision at a time.
- Offer 3-5 concise choices when possible.
- Put the recommended/default choice first when there is a clear default.
- Always allow custom text or edits.
- Let the user pick by number and optionally add refinements.
- After collecting ticket sections, show the complete draft before writing to Jira.
- Keep generated text concise.

Example prompt for a section:

```md
For `Why`, choose one or edit:

1. Bug / regression affecting Phoenix simulation
2. Follow-up from PR review or investigation
3. Cleanup to reduce future confusion
4. Support upcoming validation / rollout
5. Custom
```

## Description Template

Use this structure by default:

```md
## Summary
1-2 sentences describing the ticket.

## Goal & Non-goal

### Why
- Why this matters
- Problem / motivation

### Goal
- What this ticket should accomplish
- Expected behavior or outcome

### Non-goal
- What is intentionally out of scope

## Context
- Relevant Slack threads, docs, PRs, code links, logs
- Current behavior / constraints / prior decisions
- Parent ticket: none / `<KEY>` / not sure
- Due date: none / today / this week / custom date

## Plan
- Step 1
- Step 2
- Step 3

## Artifacts
- PRs:
  - ...

## Definition of Done
- Implementation is complete
- Tests / validation are complete
- Reviewer can verify the expected behavior
```

Keep each section to 1-5 bullets when possible. If the ticket needs more detail, link to a doc instead of putting all details in Jira.

## Workflow: Create a Phoenix Ticket

1. Confirm the ticket shape before drafting:
   - Prefer one high-level work item for a feature, investigation, validation effort, or rollout; create one ticket per PR only when the user requests that granularity.
   - Parent ticket: offer `none`, `existing key`, or `not sure`. Use `-P "<PARENT-KEY>"` only when an existing parent key is supplied and confirmed.
   - Due date: offer `none`, `today`, `this week`, or `custom`. Capture the choice in the description unless exact Jira CLI/custom-field syntax is confirmed.
   - Assignee defaults to `Yimin Lin`; ask only if the user wants a different assignee or no assignee.
2. Collect fields one by one:
   - Summary, in Title Case after `[Phoenix]`
   - Parent ticket
   - Due date
   - Why
   - Goal
   - Non-goal
   - Context
   - Plan
   - Artifacts / PRs
   - Definition of Done
3. For each section:
   - offer short suggested options when possible
   - ask the user to choose, edit, skip, or provide custom text
   - keep wording short and concrete
   - prefer useful Slack, PR, log, simulation, dashboard, and context links over pasted detail
4. Draft the full description and show it before creating the ticket.
5. Confirm before writing to Jira, including assignee, parent, due-date handling, and any parent/child/epic writes.
6. Create the ticket:

```bash
jira issue create \
  -t Task \
  -s "[Phoenix] <summary>" \
  -C Phoenix \
  --custom team=Simulation \
  -a "Yimin Lin" \
  -b "$body" \
  --no-input
```

When a parent key is supplied and confirmed, add `-P "<PARENT-KEY>"` to the create command. If the installed Jira CLI does not support `-b` during create, create the ticket first, then update the body with `jira issue edit`. Do not invent due-date CLI syntax; include the due date in the description or apply it only when exact Jira CLI/custom-field syntax is confirmed.

## Workflow: Sync Jira With PR

Use when the user wants a Jira ticket kept aligned with PR state. Confirm each Jira write/status/description change unless the user explicitly requested that exact update.

1. Collect the ticket key and PR URL/title.
2. PR created or draft-ready: confirm moving the ticket to `In Review`.
3. Add the PR link under `## Artifacts` / `PRs` in the description, or as a concise comment if preserving the existing description is safer.
4. Add validation results as a short comment or description update.
5. Blocked PR: add a blocker comment and confirm any status change.
6. Merged PR: confirm moving the ticket to `Done`.

## Workflow: Update Description

1. Fetch or ask for the ticket key.
2. Draft a concise replacement description using the template.
3. Show the draft to the user.
4. Prefer user review/edit in `nvim`:

```bash
f="$(mktemp)"
printf '%s\n' "$draft_body" > "$f"
nvim "$f"
body="$(<"$f")"
jira issue edit "<KEY>" -b "$body" --no-input
rm -f "$f"
```

Do not overwrite a detailed existing description unless the user confirms.

## Workflow: Move Status

Use:

```bash
jira issue move "<KEY>" "<STATUS>"
```

Common statuses:

```bash
jira issue move "<KEY>" "Select for Development"
jira issue move "<KEY>" "In Progress"
jira issue move "<KEY>" "In Review"
jira issue move "<KEY>" Done
```

Confirm before moving status unless the user gave an explicit status-change command.

## Workflow: Link Tickets

Use this when the user asks to connect Jira tickets based on a human description such as "blocks", "is blocked by", "relates to", "duplicates", or "is caused by".

1. Collect:
   - source ticket
   - target ticket
   - intended relationship in human terms
2. Prefer prompting with choices:

```md
What relationship should these tickets have?

1. `<SOURCE>` blocks `<TARGET>`
2. `<SOURCE>` is blocked by `<TARGET>`
3. `<SOURCE>` relates to `<TARGET>`
4. `<SOURCE>` duplicates `<TARGET>`
5. Custom / not sure
```

3. Translate the selected relationship into the Jira link type supported by the installed Jira CLI / Jira instance.
4. Confirm before writing:
   - `<SOURCE>` will be linked to `<TARGET>` as `<RELATIONSHIP>`.
5. Apply with the installed Jira CLI's supported syntax. Common form:

```bash
jira issue link "<SOURCE>" "<TARGET>" "<LINK_TYPE>"
```

If the link type name or direction is ambiguous, ask the user instead of guessing.

## Workflow: Add Comment

Use comments for progress updates, handoff notes, validation results, or blockers.

Prefer short comments:

```md
Update:
- ...
- ...

Next:
- ...
```

Apply with:

```bash
f="$(mktemp)"
printf '%s\n' "$comment_body" > "$f"
nvim "$f"
jira issue comment add "<KEY>" --template "$f" --no-input
rm -f "$f"
```

## Guardrails

- Ask before performing Jira create/update/move/link/comment writes unless the user explicitly requested the exact write.
- Keep tickets short; link to detailed docs instead of embedding them.
- Do not invent Slack links, PRs, simulations, dashboards, logs, or validation artifacts.
- Include useful Slack/PR/log/context links when known; summarize instead of pasting long threads or logs.
- Do not create per-PR tickets by default for a PR stack; group related Phoenix work into a higher-level work item unless the user asks otherwise.
- Do not invent Jira parent/child or epic CLI syntax. If the exact command is not documented or already known, draft the relationship and ask/confirm before writing.
- Default Phoenix ticket creates assign to `Yimin Lin`; confirm if using a different assignee or leaving the ticket unassigned.
- If Jira auth fails, stop and ask the user to refresh Jira CLI credentials or environment variables.
- If a section is unknown, use `TBD` only with user approval.
- For Phoenix tickets, always ensure:
  - summary starts with `[Phoenix]`
  - text after `[Phoenix]` uses Title Case
  - component is `Phoenix`
  - team is `Simulation`

## Done Criteria

A Jira operation is complete when:

- the ticket key is known
- the requested create/update/move/link/comment operation succeeded
- the final ticket key or URL is reported back to the user
- any assumptions or omitted sections are called out briefly
