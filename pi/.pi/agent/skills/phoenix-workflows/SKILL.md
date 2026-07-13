---
name: phoenix-workflows
description: Plan and, only after explicit active-prompt approval, run Phoenix SIL/no_sync scenarios, launch or rerun HIL, and fetch or upload Phoenix artifacts; route read-only evidence inspection to phoenix-inspector.
---

# Phoenix Workflows

Use for runtime-changing Phoenix work: SIL/no_sync/flakiness runs, HIL launch/rerun, bounded artifact fetch, or upload/presign/publish. Route read-only inventory, recent-run lookup, local logs, ZML extraction, and comparisons to `phoenix-inspector` (natural request or `/skill:phoenix-inspector`).

Load [references/command-recipes.md](references/command-recipes.md) only after choosing a mode or when concrete commands are requested.

## Mandatory approval boundary

Before **every** Phoenix runtime command, `bazel test`/`bazel run`, repeated run, network/auth/AWS/S3/GitHub action, fetch, upload, presign/publish, workflow dispatch, hardware/HIL action, or other runtime mutation:

1. Produce the decision packet below.
2. Require explicit approval in the active prompt for that exact action.
3. Stop. Do not treat prior turns, configured credentials, environment variables, or a general request as approval for an unresolved command/destination.

Never initiate auth/login, inspect credentials, install tools, use `sudo`, or silently broaden a target. If the mode is ambiguous between SIL and HIL, ask which. HIL always requires explicit hardware approval.

### Decision packet

- chosen mode
- repo/worktree and branch/ref or SHA
- exact underlying command/action
- approval, auth, network, hardware/HIL, and upload status
- expected local/remote artifacts and destination
- timeout/checkpoint cadence
- validation/stop condition
- blockers/unresolved choices

Readiness replies use `Answer: Yes/No`, blockers, exact action, validation/log plan, and `waiting for your confirm`. Use **No** while any launch-critical field is unresolved.

## Modes

1. `inspect-existing-evidence` → `phoenix-inspector`
2. `run-sil-scenario`
3. `run-no-sync-scenario`
4. `run-flakiness-check`
5. `fetch-hil-logs`
6. `launch-phoenix-hil`
7. `upload-local-log-or-artifact`
8. `inspect-run-output-after-run` → `phoenix-inspector`

If multiple modes are requested, begin with the safest approved read-only local step. Remote reads still require active-prompt approval.

## Execution rules

- Confirm scenario labels from the matching `BUILD.bazel`; `ash/scenarios/hil/*.pbtxt` are not standalone runnable targets.
- Local runs normally use `bazel test <label> --config=debug`; repeats require separate approval of the count.
- Prefer `/Systems/.phoenix/logs/**` after runs. Do not inspect Bazel cache testlogs unless Phoenix logs are insufficient or explicitly requested; surface the exact cache path first.
- Do not use the OpenCode progress/orchestrator or `opencode_longrun.py`. Pi owns foreground progress: state the exact command and checkpoint/timeout plan, execute only after approval, and report command status and artifact paths. Do not promise background monitoring.
- Fetches require exact SHA/ref, bounded destination, approved network/AWS access, and stop condition. Uploads require exact source, destination/prefix, expected link/artifact, and separate approval.
- Prefer checked-in GitHub HIL workflow for shared HILs. Local claimed-HIL execution requires an explicit claimed-box/container decision and a resolved version set or an explicit decision to use deployed software. Never assume raw checked-in version sets provide a usable sim image.
- Post-run inspection belongs to `phoenix-inspector`; seed it with exact log root, run attempt, selected ZMLs, topic/signal hints, and time window.

## Evidence and response contract

Keep a Topic Ledger with scenario/job/log root, topic/signal/source, time window or run attempt, status, and next decisive probe. Record exact commands, exit statuses, local/remote artifact paths, and blockers. Distinguish `mocked/simulated input`, `real runtime plumbing`, and `authoritative output/log` when explaining a flow.

Do not claim causal RCA without differential or equivalent evidence. Final responses state chosen mode, exact target/action, safest next read-only step, approval still needed, and evidence supports/does-not-prove limits.
