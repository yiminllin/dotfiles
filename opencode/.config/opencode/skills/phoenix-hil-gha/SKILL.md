---
name: phoenix-hil-gha
description: "Legacy/expert escape hatch for low-level Phoenix HIL/GHA evidence helper debugging. Prefer `phoenix_inspector` for normal inventory, recent-HIL, packet inspection, and pass/fail comparison; prefer `phoenix-workflows` for launch/fetch/upload workflows."
---

# Phoenix HIL/GHA Legacy Escape Hatch

Use this legacy/expert escape hatch only when the user needs to debug or
operate the old `hil_evidence_cli.py` helper directly because a canonical
workflow is missing a low-level backend detail.

## Prefer canonical routes

- Use `phoenix_inspector` for normal read-only HIL/GHA/S3 inventory, recent HIL
  lookup, packet inspection, field discovery, extraction/comparison, and
  evidence summaries.
- Use `phoenix-workflows` for Phoenix/SIL/HIL launch, execution, rerun, fetch,
  upload, or other workflow operations.

## Use this skill only for

- Inspecting or reproducing legacy `hil_evidence_cli.py` behavior.
- Checking whether the legacy helper still supports a specific low-level
  `summarize`, `recent`, or `sync-check` path.
- Reporting a helper blocker from a bounded local command without broadening
  into canonical Phoenix investigation work.

## Do not use this skill for

- Normal inventory, recent HIL lookup, packet inspection, first-pass evidence
  packets, pass/fail comparison, field discovery, extract/compare, or RCA.
- Launching, executing, rerunning, fetching, uploading, or mutating Phoenix,
  SIL, HIL, GitHub, S3, PR, or Jira state.
- Auth repair, credential refresh, interactive prompts, destructive commands,
  broad downloads, or network workflows unless separately approved and routed
  through the correct canonical skill.

## Helper boundary

- Helper name: `hil_evidence_cli.py`.
- Source path: `opencode/.config/opencode/scripts/hil_evidence_cli.py`.
- Runtime path when installed: `$HOME/.config/opencode/scripts/hil_evidence_cli.py`.
- Relevant legacy subcommands: `summarize`, `recent`, `sync-check`.

Keep use read-only unless the user explicitly asks to debug the helper source
itself. If the helper is missing, stale, blocked by `gh`/AWS/auth, or would need
network/destructive/write behavior, stop and report the blocker instead of
repairing credentials or continuing in this skill.

## Minimal output contract

Return only the relevant compact fields:

- `blocker`: missing approval, tool, auth, path, or exact input, if any.
- `evidence`: bounded artifact, stderr/stdout excerpt, or source path inspected.
- `command`: exact helper command, cwd, exit status, and output path when run.
- `helper`: `hil_evidence_cli.py` path/subcommand and whether source or runtime.
- `result`: what the legacy helper check showed, with limits.
- `next step`: route to `phoenix_inspector` / `phoenix-workflows`, ask for a
  narrower input, or request separate approval.
