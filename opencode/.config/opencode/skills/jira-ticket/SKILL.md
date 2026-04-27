---
name: jira-ticket
description: Create and update concise Jira tickets using the Jira CLI, especially Phoenix Simulation tickets. Use when asked to create a Jira ticket, update a Jira description, move ticket status, link Jira tickets, or add ticket update comments.
---

# Jira Ticket

## Overview

Use the Jira CLI to create and update short, readable Jira tickets.

This skill is optimized for Phoenix Simulation work:

- new ticket summaries are prefixed with `[Phoenix]`
- component is set to `Phoenix`
- team is set to `Simulation`
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

1. Collect fields one by one:
   - Summary
   - Why
   - Goal
   - Non-goal
   - Context
   - Plan
   - Artifacts / PRs
   - Definition of Done
2. For each section:
   - offer short suggested options when possible
   - ask the user to choose, edit, skip, or provide custom text
   - keep wording short and concrete
3. Draft the full description and show it before creating the ticket.
4. Confirm before writing to Jira.
5. Create the ticket:

```bash
jira issue create \
  -t Task \
  -s "[Phoenix] <summary>" \
  -C Phoenix \
  --custom team=Simulation \
  -b "$body" \
  --no-input
```

If the installed Jira CLI does not support `-b` during create, create the ticket first, then update the body with `jira issue edit`.

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

- Ask before performing Jira write operations unless the user explicitly requested the exact write.
- Keep tickets short; link to detailed docs instead of embedding them.
- Do not invent Slack links, PRs, simulations, dashboards, logs, or validation artifacts.
- If Jira auth fails, stop and ask the user to refresh Jira CLI credentials or environment variables.
- If a section is unknown, use `TBD` only with user approval.
- For Phoenix tickets, always ensure:
  - summary starts with `[Phoenix]`
  - component is `Phoenix`
  - team is `Simulation`

## Done Criteria

A Jira operation is complete when:

- the ticket key is known
- the requested create/update/move/link/comment operation succeeded
- the final ticket key or URL is reported back to the user
- any assumptions or omitted sections are called out briefly
