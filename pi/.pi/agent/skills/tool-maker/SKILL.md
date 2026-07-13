---
name: tool-maker
description: Turn one known repeated Pi workflow into the smallest suitable reusable artifact, or improve and evaluate one existing Pi skill. Use when asked to create, adapt, compare, or package a bounded Pi workflow; do not use for broad workflow discovery or unrelated application code.
---

# Tool Maker

## Purpose

Choose and tune the smallest durable Pi artifact for one known workflow using realistic evaluations and reviewable edits.

## Guardrails

- Keep scope to one workflow or one small candidate set.
- Inventory repository-owned Pi artifacts first, then global Pi artifacts. Repository source is authoritative when both exist; runtime links are loading evidence, not edit targets.
- Do not add extensions, packages, providers, models, external skill URLs, background hooks, network integrations, or scripts unless explicitly requested and separately approved.
- For config, prompt, extension, or skill edits, show the intended change and ask approval unless the user already explicitly requested that exact implementation.
- Stop before network/auth, credential access, external-directory writes, destructive commands, or other permission-triggering actions and name the exact action required.
- Adapt external patterns rather than copying license-unclear or irrelevant text.

## Choose the artifact

| Artifact | Use when | Avoid when |
|---|---|---|
| Skill (`skills/<name>/SKILL.md`) | Repeatable judgment or a triggered workflow needs procedure and boundaries | A deterministic command is sufficient |
| Prompt template (`prompts/*.md`) | The user deliberately invokes an argument-bearing reusable prompt | Natural trigger-driven loading is needed |
| Script/helper | Deterministic parsing, extraction, validation, or formatting dominates | Judgment and routing dominate |
| Extension | A proven Pi API/tool/lifecycle gap cannot be solved by a skill, prompt, or script | It only emulates another agent framework |
| `APPEND_SYSTEM.md` | A compact cross-workflow Pi operating or safety rule is required | The behavior belongs to one workflow |
| Settings | A documented Pi runtime setting is required | Instructions or workflow logic are being encoded |
| Docs/notes | Durable operator context is enough | Pi must execute the workflow repeatedly |

Prefer a skill or script before an extension. Do not invent framework-specific surfaces that Pi does not locally provide.

## Workflow

1. Define trigger phrases, users, required inputs, output, non-goals, safety boundaries, and success criteria.
2. Inspect overlapping source skills, prompts, scripts, extensions, `APPEND_SYSTEM.md`, settings, repository guidance, and relevant plans/designs. Compare `~/.pi/agent/` only when loading or runtime behavior matters; never edit runtime symlinks directly.
3. Choose the smallest artifact from the table. Prefer updating an owner artifact over creating overlap.
4. For a skill, use YAML frontmatter with kebab-case `name` and an action-oriented, trigger-specific `description`; include purpose, use/non-use cases, approval/tool boundaries, workflow, output contract, and lean evaluation guidance.
5. For an external pattern, map assumptions to installed Pi tools, paths, permissions, and lifecycle; drop unsupported vendor machinery.
6. Design 3-8 evaluations: positive trigger, adjacent negative, ambiguous input, approval boundary, and a representative historical prompt when available. Define expected routing, key steps, output, and prohibited behavior.
7. Compare baseline and candidate on trigger precision, completeness, safety handling, usefulness, and instruction bloat. Keep the candidate only when it materially improves behavior.
8. After approval, apply the narrow source edit under the owning repository path. Validate metadata, relative resources, overlap, offline discovery, runtime resolution when activated, and vendor-specific residue.
9. Remove redundant prose, speculative guardrails, unsupported tools, stale names, and unnecessary files before handoff.

## Pi lifecycle

- Repository-managed source in this dotfiles repo lives under `pi/.pi/agent/`; stow resolves it into `~/.pi/agent/`.
- Pi discovers global skills recursively under `~/.pi/agent/skills/` and prompt templates under `~/.pi/agent/prompts/`.
- Use `/skill:<name>` for explicit skill evaluation when supported; natural-language discovery remains the normal trigger.
- Store temporary evaluation artifacts under `/tmp/pi/`, not in source or runtime state.
- Do not claim model-backed discovery from static checks. Record exact provider-free checks separately from exact prompts pending a later model-enabled run.

## Output

Report the artifact decision, authoritative source path, exact applied files/adaptations, evaluation prompts/results, offline validation, runtime activation note, and material remaining risks. Keep evidence concise and distinguish static/provider-free proof from model-backed behavior still pending.
