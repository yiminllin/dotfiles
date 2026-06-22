---
name: zml-signal-audit
description: "Legacy/expert escape hatch for low-level zml_signal_audit.py helper debugging. Prefer `phoenix_inspector` for normal ZML field discovery, topic lookup, extract, compare, and preset workflows; prefer `phoenix-workflows` for launch/fetch/upload workflows."
---

# ZML Signal Audit Legacy Escape Hatch

Use this legacy/expert escape hatch only when the user needs to debug or
operate the old `zml_signal_audit.py` helper directly because a canonical
`phoenix_inspector` workflow is missing a low-level backend detail.

## Prefer canonical routes

- Use `phoenix_inspector` for normal ZML/ZST/log inventory, recent HIL lookup,
  packet inspection, field discovery, topic lookup, extraction, CSV output,
  pass/fail comparison, presets, and evidence summaries.
- Use `phoenix-workflows` for Phoenix/SIL/HIL launch, execution, rerun, fetch,
  upload, or other workflow operations.

## Use this skill only for

- Inspecting or reproducing legacy `zml_signal_audit.py` behavior.
- Checking whether the legacy helper still supports a specific low-level
  `topics`, `fields`, `audit`, or `compare` path.
- Reporting a helper blocker from bounded local files without broadening into a
  canonical Phoenix/ZML investigation.

## Do not use this skill for

- Normal inventory, recent HIL lookup, packet inspection, field discovery,
  topic lookup, extract/compare, preset audits, evidence summaries, or RCA.
- GHA/S3 discovery, artifact download, launch, execution, rerun, fetch, upload,
  PR/Jira mutation, or remote log sourcing.
- Auth repair, credential refresh, interactive prompts, destructive commands,
  broad downloads, or network workflows unless separately approved and routed
  through the correct canonical skill.

## Helper boundary

- Helper name: `zml_signal_audit.py`.
- Source path: `opencode/.config/opencode/scripts/zml_signal_audit.py`.
- Runtime path when installed: `$HOME/.config/opencode/scripts/zml_signal_audit.py`.
- Relevant legacy subcommands: `topics`, `fields`, `audit`, `compare`.

Keep use read-only on bounded local `.zml`, `.zml.zst`, or log-root inputs
unless the user explicitly asks to debug the helper source itself. If the helper
is missing, stale, needs remote artifacts, or would need network/destructive/write
behavior, stop and report the blocker instead of inventing ad-hoc parsing.

## Minimal output contract

Return only the relevant compact fields:

- `blocker`: missing approval, tool, local file, exact topic/field, or source.
- `evidence`: bounded local artifact, stderr/stdout excerpt, or source path
  inspected.
- `command`: exact helper command, cwd, exit status, and output path when run.
- `helper`: `zml_signal_audit.py` path/subcommand and whether source or runtime.
- `result`: what the legacy helper check showed, with limits.
- `next step`: route to `phoenix_inspector` / `phoenix-workflows`, ask for a
  narrower local input, or request separate approval.
