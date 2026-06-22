---
name: phoenix-workflows
description: Run Phoenix SIL/no_sync scenarios, launch/rerun Phoenix HIL workflows, and fetch/upload Phoenix artifacts conservatively; hand read-only lookup and evidence inspection to phoenix_inspector.
---

# Phoenix Workflows

Use this skill for Zipline-internal Phoenix requests that involve:

- running local Phoenix SIL scenarios with `bazel test`
- running `no_sync` scenarios
- repeating Phoenix scenario runs to check flakiness or determinism
- collecting local Phoenix ZML, validator, stdout, or stderr logs for later inspection
- fetching Phoenix/HIL artifacts from S3
- uploading or presigning Phoenix/SIL artifacts for Baraza, LogPlots, dashboards, or shareable links
- launching or rerunning a Phoenix HIL run locally or through the checked-in GitHub workflow

Do **not** use this skill for read-only HIL/GHA evidence collection, recent HIL run lookup, recent passing-run discovery, S3/artifact inventory, artifact inspection, local log inspection, ZML signal extraction, topic-name/source lookup, time-window extraction, CSV summary prep, pass/fail or before/after signal comparison, prod-nav preset signal checks, or one-run root-cause evidence. Hand those to `$phoenix_inspector`. Launch/run/fetch/upload workflows stay here.

For PR babysit, PR CI retry/rerun/relaunch, or manual dispatch requests involving failed HIL jobs, HIL workflow dispatch, `p2-zip-system-hil-build.yml`, `gh workflow run`, or HIL hardware-like launch semantics, use this skill for the launch decision packet before any relaunch or dispatch. PR babysit remains owner for PR status, comments, and CI monitoring.

For Phoenix/SIL artifact upload, presign, Baraza, LogPlots, or dashboard upload requests, use this skill's fetch/upload mode first to produce the safety/decision packet. `$upload_local_log_to_s3` or `phoenix/debug/scripts/upload_local_log_to_s3.sh` is only the leaf helper after the mode, destination, auth/network status, source log directory, and expected link/artifact are clear.

For command catalogs, target examples, optional flags, HIL dispatch options, and local HIL filter mappings, lazy-load `references/command-recipes.md` only after the workflow mode is chosen or the user asks for concrete commands.

## Safety gates

### Safe / read-only

- Read repo docs, workflow files, and existing local logs.
- Inspect existing `*.zml` / `*.zml.zst` files with read-only `zml` commands like `list`, `events`, and `print`.
- Inspect already-downloaded Phoenix/HIL artifacts on disk.

### Needs auth, network, or environment setup

- `fetch-hil-logs` / `hil-tools-cli fetch_hil_logs` needs AWS credentials and S3 network access.
- `gh workflow run` needs GitHub auth and dispatch permissions.
- Upload/presign helpers need AWS credentials, the intended S3 destination/prefix, and network access.
- Local HIL execution should be done from the HIL container started with `./hil/dev_entrypoint.sh zsh`.

If AWS auth is stale, use `$aws-sso-login` first when it is available from repo/system skill roots; otherwise stop and ask the user to run `aws sso login`. Do not run login, GitHub auth, credential, or hardware setup commands implicitly.

### Confirm first

Wait for explicit confirmation before:

- Any `bazel test` or `bazel run` that launches Phoenix.
- Repeated Phoenix runs such as `--runs_per_test=20` or larger, because they are slow and generate a lot of logs.
- Any network fetch from S3 or GitHub workflow dispatch unless the user already requested that exact action in the current turn and all decision-packet fields are resolved.
- Any upload, presign, dashboard publish, or broad-scope run like `PHOENIX_SUITE`, `RUN_DELIVERY_ALL_HILS`, or `DEPLOY_ONLY_ALL_HILS`.
- Any `bazel run //hil/...` command or anything that touches real HIL hardware.

If the request is ambiguous between local SIL and real HIL, ask which mode they want. Do not assume hardware.

For readiness checks before any confirm-first action, such as "ready to one shot?", "are we ready to start?", or "can I tell you to run it?", reply in this shape:

```text
Answer: Yes/No
Why:
- blockers:
- exact command/action (wrapped and underlying when longrun applies):
- validation/log upload plan:
- waiting for your confirm before launch:
```

Use `No` if the mode, target, credentials, branch/ref, HIL runner, log destination, or other launch-critical input is unresolved. If ready, name the exact SIL/HIL dispatch/run/fetch/upload action and the validation or log-upload plan, then wait for confirmation before launching, dispatching, or starting upload-heavy behavior.

For any confirm-first Phoenix/SIL/HIL/fetch/upload action, include a compact decision packet before launch:

- chosen mode
- source repo/worktree and branch/ref or SHA
- exact command/action, including the `opencode_longrun.py` wrapper and underlying command when applicable
- safety status: confirmation, auth, network, hardware/HIL, and upload state
- expected artifacts: Phoenix log dir, downloaded HIL root, S3 prefix, Baraza link, ZML/CSV outputs, or dashboard link
- timeout/checkpoint cadence
- validation or stop condition
- blockers or unresolved choices

Preserve routing: launch/run/fetch/upload stays here; read-only evidence inspection goes to `$phoenix_inspector`.

## Phoenix log source priority

For Phoenix SIL/HIL runs, collect logs under `/Systems/.phoenix/logs/**` as the preferred local log source, then hand inspection to `$phoenix_inspector`. Do not read `~/.cache/bazel/**/testlogs/**` by default; use Bazel cache testlogs only when Phoenix logs are missing/insufficient or the user explicitly asks for them.

Before attempting a Bazel cache fallback, stop and surface the exact cache path/action and required permission or decision instead of waiting behind an external-directory prompt.

## Long local run wrapper

For local Phoenix/SIL/Bazel/ZML/Python runtime commands expected to take more than about 5-10 minutes, default to the existing long-run helper:

```sh
python3 "$HOME/.config/opencode/scripts/opencode_longrun.py" run --name <safe-name> -- <command...>
```

Use this especially for local Phoenix SIL `bazel test` scenario runs, repeated/flakiness `bazel test --runs_per_test=...`, long ZML extraction or ad-hoc Python analysis, and long local validation loops. Do not require it for tiny/quick commands, simple read-only inspections, or commands where wrapping would obscure interactive prompts, permission behavior, or auth setup.

When a wrapped command already produces canonical Phoenix log directories, the helper records the wrapper command, stdout/stderr, and wrapper log path; final answers should still report the Phoenix log directory plus any Baraza, S3, ZML, or CSV artifacts. For confirm-first Phoenix actions, readiness and exact-command responses must show both the wrapped command and the underlying command clearly.

Preserve the upload rules below: longrun wraps the run or analysis command, not necessarily the upload step, unless the upload itself is expected to be long and is explicitly included. Child processes may buffer output under a wrapper; use unbuffered flags only when appropriate for that specific command, such as Python analysis you own, and do not invent generic unsafe changes.

## Workflow selection

First classify the request into one mode:

1. `inspect-existing-evidence` (handoff to `$phoenix_inspector`)
2. `run-sil-scenario`
3. `run-no-sync-scenario`
4. `run-flakiness-check`
5. `fetch-hil-logs`
6. `launch-phoenix-hil`
7. `upload-local-log-or-artifact`
8. `inspect-run-output-after-run` (handoff to `$phoenix_inspector`)

If a request spans multiple modes, start with the safest read-only one. Read-only recent HIL/GHA lookup, recent passing-run discovery, S3/artifact inventory, and one-run evidence collection stay with `$phoenix_inspector`; only launch, rerun, fetch, or upload stays here.

For complex Phoenix/SIL explanations, start with a tiny dataflow map before prose. Label each step as `mocked/simulated input or state`, `real runtime plumbing`, or `authoritative output/log`, for example:

```text
scenario config (mocked/simulated) -> Phoenix orchestration/services (real runtime plumbing) -> validators/ZML/test_record (authoritative output)
```

For failure triage, do not make causal RCA claims without pass/fail contrast or equivalent differential evidence. If only the failing run is available, say what the current evidence supports and what it does not prove.

## Traceability for Phoenix/ZML/HIL evidence

- Follow the shared traceability defaults from `user-profile.yaml` for nontrivial inspection, evidence, and RCA-style answers.
- For Phoenix/ZML/HIL work, keep the `Topic Ledger` grounded in the exact scenario/job/log root, topic/signal/source file, time window or run attempt, status, and next decisive probe.
- Preserve material local log, validator, ZML, `test_record.json`, downloaded artifact, generated report, and helper-command records when they affect the answer or blocker.
- For ZML topic inventory, signal extraction, time-window extraction, CSV summary prep, or pass/fail/before-after comparisons after SIL/sim/HIL log collection, hand off to `$phoenix_inspector` with the topic ledger seed, source-type context, and selected local ZML paths instead of broad ad-hoc signal spelunking.
- If the same Phoenix/ZML extraction or comparison recipe recurs, preserve the exact inspector command recipe, outputs, evidence limits, and proves/does-not-prove boundaries instead of creating another one-off script.

## Default post-run upload for local SIL runs

For `run-sil-scenario`, `run-no-sync-scenario`, and `run-flakiness-check`:

1. Before launching Phoenix, confirm whether the run itself needs confirmation under the normal safety gates.
2. After a successful local run, resolve the produced log directory under `/Systems/.phoenix/logs/`. Prefer the run-specific directory when available; otherwise fall back to `/Systems/.phoenix/logs/latest/`.
3. If `PHOENIX_LOG_UPLOAD_S3_PREFIX` is set, upload that log directory with `$upload_local_log_to_s3` when available; otherwise run `phoenix/debug/scripts/upload_local_log_to_s3.sh`.
4. When upload output includes a Baraza link, capture it from the upload output. If `TMUX` is set and `tmux` is available, copy it into the tmux buffer with `tmux set-buffer -- "$baraza_link"`.
5. Include the final S3 path and Baraza link in the response when upload succeeds, and say whether the tmux copy happened.
6. If upload cannot happen because AWS auth is missing/expired or the destination prefix is unavailable, say that clearly instead of silently skipping it.

Do not auto-upload logs for HIL launches, fetched HIL logs, or purely read-only inspection requests.

## Mode workflows

### 1) inspect-existing-evidence

For existing logs, packets, S3/GHA references, or ZML paths, hand off to `$phoenix_inspector` rather than using this launch workflow skill. Seed the handoff with known paths, scenario/job IDs, topic/signal hints, source-type context, time window, and any selected local ZML paths. Choose an inspector command from known inputs instead of defaulting to broad discovery; use `inventory` first only when the source shape or available artifacts are unknown.

Useful local Phoenix log roots to seed:

- `/Systems/.phoenix/logs/latest/`
- `/Systems/.phoenix/logs/by_scenario/<scenario>/`

If `zml` is not available and the user wants low-level legacy CLI inspection, the setup in `tools/zml/README.md` builds and installs tooling; only do that with confirmation.

### 2) run-sil-scenario

Use `bazel test <label> --config=debug` for local Phoenix iteration unless the user asks for a different checked-in shape. `--config=debug` is the documented default because it surfaces subprocess stdout/stderr and avoids stale Bazel cache results.

Phoenix SIL scenario targets are spread across `ash/scenarios/**` packages. If the user gives only a scenario name, first confirm the Bazel label by reading the matching `BUILD.bazel` in that package. Do not treat `ash/scenarios/hil/*.pbtxt` as standalone runnable Phoenix scenario packages; launch those configs through the Phoenix HIL tests or workflow dispatch.

Use the long-run wrapper for expected long local runs. After success, apply the default post-run upload rule for local SIL runs when `PHOENIX_LOG_UPLOAD_S3_PREFIX` is set.

### 3) run-no-sync-scenario

`ash/scenarios/no_sync` contains SIL no-sync scenarios with their own Bazel targets. Confirm the label from `ash/scenarios/no_sync/BUILD.bazel`, then run it like a local SIL scenario with `--config=debug` unless the user asks for another checked-in shape.

Treat no-sync repeats as potentially slow/log-heavy. Use the long-run wrapper and apply the default post-run upload rule when `PHOENIX_LOG_UPLOAD_S3_PREFIX` is set.

### 4) run-flakiness-check

Use this when the user wants to run the same Phoenix scenario multiple times, especially for `no_sync` cases. Start with one explicit scenario label unless the user asks for a batch. Use a small repeat count first for interactive repro; confirm before large repeat counts such as `--runs_per_test=20` or higher.

If the user explicitly wants Bazel flake classification, use `--runs_per_test_detects_flakes`; otherwise keep repeated execution separate from flake detection semantics. For repeated runs, inspect `/Systems/.phoenix/logs/by_scenario/<scenario>` rather than relying only on `latest`.

If the user wants determinism metrics or Honeycomb upload, surface that it needs the checked-in metrics helper and `HONEYCOMB_API_KEY` before running.

### 5) fetch-hil-logs

Use the checked-in HIL log fetcher to sync artifacts for a git SHA. This is a network/auth action: produce the decision packet with SHA/ref, local destination, AWS auth status, expected `~/.hil/<sha>/...` root, timeout/checkpoint plan, and stop condition before fetching.

The underlying S3 source is `s3://platform2-testing-logs/p2-zip-system-hil/<sha>`. After download, hand inspection to `$phoenix_inspector`, seeded with the downloaded root and known runner / run attempt / test directory when available.

### 6) launch-phoenix-hil

Prefer the existing GitHub workflow for shared HILs unless the user already has a claimed box/container and explicitly wants local execution.

For workflow dispatch, confirm first, then dispatch `p2-zip-system-hil-build.yml` with the chosen branch/ref and dispatch option. Use bare enum values like `PHOENIX_ZIP_DELIVERY`; do not dispatch suite or all-HIL variants without explicit approval. Only pass `override_version_set` when the user explicitly wants to override the dispatch default for that test, and match the EV/test variant carefully. Only pass `workflow_flags='--unsafe-allow-old-branches'` when the user explicitly wants to override the stale-branch guard.

For local / claimed-HIL execution, enter the HIL container with `./hil/dev_entrypoint.sh zsh`. Only use local execution when the user explicitly wants to iterate on the software already deployed on that claimed box, or when you have a resolved version-set JSON for this exact run. Before doing this, verify the local claimed-HIL environment already has a usable `SIM_DOCKER_IMAGE` exported or that the resolved version set contains a non-empty `infra.sim_image`.

Do **not** assume the checked-in Phoenix version-set files are safe local defaults for `--param version_set=...`; the raw files leave `infra.sim_image` empty and rely on workflow-side resolution. If you do not have a resolved version-set JSON, either stop and prefer workflow dispatch, or say clearly that the local rerun uses the software already on the claimed HIL.

Local HTF/pytest exports go to `${HTF_OUTPUT_DIRECTORY:-~/runner_output}` and are usually written into per-test folders named like `<short_test_name>_<uuid>/`.

### 7) upload-local-log-or-artifact

For local Phoenix/SIL log upload, presign, Baraza, LogPlots, or dashboard upload requests, first produce the confirm-first decision packet from the Safety gates section: mode, repo/worktree and branch/ref, source log directory or artifact, destination/prefix, auth/network status, helper command, expected S3/Baraza/LogPlots/dashboard output, and blockers. Then call `$upload_local_log_to_s3` when available; otherwise use `phoenix/debug/scripts/upload_local_log_to_s3.sh` as the leaf helper.

Do not treat upload as evidence inspection. If the user wants to choose the right artifact, compare runs, inspect ZML, discover a recent passing run, or inventory S3/GHA artifacts before upload, hand that read-only step to `$phoenix_inspector` first.

### 8) inspect-run-output-after-run

This is a handoff seed only: read-only one-run evidence collection belongs to `$phoenix_inspector`, not this skill. For Phoenix SIL runs, seed the inspector with likely roots such as:

- `/Systems/.phoenix/logs/latest/.../compute_{a,b}.zml[.zst]`
- `/Systems/.phoenix/logs/by_scenario/<scenario>/...`
- `validators/**/*_results.json`
- service `*_stdout.txt` and `*_stderr.txt`

For fetched or CI HIL logs, seed the inspector with:

- `~/.hil/<sha>/...`
- the specific runner / run attempt / test directory, when known
- validator JSON, service stderr/stdout, and relevant compute ZML paths when already identified

For root-cause requests, tell `$phoenix_inspector` that high-level result tables are symptom summaries unless they identify the earliest causal signal, and ask it to inspect lower-level harness, Phoenix, ZML, or journal logs when validator/error summaries do not distinguish cause from downstream effect.

If the user wants local visualization, `ash/scenarios/README.md` documents the `fs:///...` LogPlots path shape for `/Systems/.phoenix/logs/latest/...`.

If the user wants a shareable LogPlots link from a local Phoenix log directory, return to `upload-local-log-or-artifact` first; helper/script upload remains the leaf action after the decision packet.

## Response pattern

When using this skill, reply with:

- chosen mode
- the exact Phoenix label, SHA/ref, workflow option, HIL runner, log source, or upload destination being used
- the safest next read-only step
- any confirmation needed before launching Phoenix, repeated flakiness runs, network fetches, uploads, workflow dispatch, or real HIL
- if a local Phoenix run was executed and uploaded, the final S3 path and Baraza link, plus whether the tmux buffer copy happened
- for RCA-style answers, an `Evidence Trace` with concise labels: `this proves/supports ...` and `this does not prove ...`
- for artifact/log/ZML evidence work, the material `Topic Ledger`, commands used, artifacts read, and blockers or next decisive probe
