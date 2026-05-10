---
name: grill-me
description: Stress-test a plan, design, requirement, or implementation idea before building. Use when the user says "grill me", asks for pre-implementation critique, or wants hidden assumptions, scope gaps, risks, and success criteria uncovered.
---

# Grill Me

## Purpose

Pressure-test an idea before execution by finding unclear requirements, hidden assumptions, risky tradeoffs, and missing success criteria.

## When to use

- The user explicitly says "grill me" or asks for Socratic questioning.
- The user wants a plan, design, requirement, or implementation approach stress-tested before building.
- The user asks to uncover assumptions, sharpen scope, or validate readiness before committing to a direction.

## When not to use

- Routine implementation requests that are already clear enough to execute.
- Debugging or review tasks with concrete evidence to inspect first.
- Broad brainstorming where the user wants many ideas rather than focused critique.

## Guardrails

- This is an explicit pre-planning critique, not a mandatory planning gate.
- Inspect the repo, docs, notes, or provided context before asking questions that are answerable locally.
- Ask one high-leverage question at a time unless the user requests a full checklist.
- Include a recommended answer or default, plus why, when asking the user to choose.
- Keep clarification minimum-needed by default; go deeper only when explicitly invoked or when risk remains material.
- Do not turn every implementation request into grilling.

## Workflow

1. Restate the idea and the current goal in one or two sentences.
2. Inspect available local context for facts, constraints, prior decisions, and obvious unknowns.
3. Identify the sharpest unresolved issue across scope, risk, constraints, success criteria, dependencies, and rollback/validation.
4. Ask one question that would most improve the plan if answered.
5. Provide a recommended answer/default and a brief reason.
6. Capture the user's answer as a decision or assumption.
7. Repeat only while a material gap remains.
8. Stop when scope, main risks, success criteria, and the next implementation or planning step are clear.

## Output format

```markdown
Current read:
- Goal: <concise restatement>
- Known constraints: <facts from context>
- Main uncertainty: <highest-leverage gap>

Question:
<one question>

Recommended answer:
<recommended choice/default> — <why>

Captured so far:
- Decisions: <confirmed choices>
- Assumptions: <working assumptions>
- Next step when clear: <plan/design/implementation action>
```
