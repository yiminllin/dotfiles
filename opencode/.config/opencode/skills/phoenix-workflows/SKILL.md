---
name: phoenix-workflows
description: Run Phoenix SIL scenarios, exercise no_sync scenarios for flakiness, inspect Phoenix/HIL logs, and launch Phoenix HIL workflows conservatively.
---

# Phoenix Workflows

Use this skill for Zipline-internal Phoenix requests that involve:

- running local Phoenix SIL scenarios with `bazel test`
- running `no_sync` scenarios
- repeating Phoenix scenario runs to check flakiness or determinism
- reading local Phoenix ZML, validator, stdout, or stderr logs
- fetching Phoenix/HIL artifacts from S3
- launching a Phoenix HIL run locally or through the checked-in GitHub workflow

If the user gives a failing GitHub Actions run/job URL and wants root-cause analysis for one attempt, prefer `$debug-phoenix-hil-from-gha`. If they specifically want to upload a local Phoenix log directory and generate a LogPlots link, `$upload_local_log_to_s3` is the focused path.

For local Phoenix SIL runs, if `PHOENIX_LOG_UPLOAD_S3_PREFIX` is set, treat post-run log upload and Baraza-link return as the default behavior unless the user opts out. Do not apply this default to HIL runs unless the user explicitly asks.

## Safety gates

### Safe / read-only

- Read repo docs, workflow files, and existing local logs.
- Inspect existing `*.zml` / `*.zml.zst` files with read-only `zml` commands like `list`, `events`, and `print`.
- Inspect already-downloaded Phoenix/HIL artifacts on disk.

### Needs auth or environment setup

- `fetch-hil-logs` / `hil-tools-cli fetch_hil_logs` needs AWS credentials.
- `gh workflow run` needs GitHub auth.
- Local HIL execution should be done from the HIL container started with `./hil/dev_entrypoint.sh zsh`.

If AWS auth is stale, use `$aws-sso-login` first.

### Confirm first

- Any `bazel test` or `bazel run` that launches Phoenix.
- Repeated Phoenix runs such as `--runs_per_test=20` or larger, because they are slow and generate a lot of logs.
- Any `bazel run //hil/...` command or anything that touches real HIL hardware.
- Any `gh workflow run p2-zip-system-hil-build.yml` dispatch.
- Uploads or broad-scope runs like `PHOENIX_SUITE`, `RUN_DELIVERY_ALL_HILS`, or `DEPLOY_ONLY_ALL_HILS`.

If the request is ambiguous between local SIL and real HIL, ask which mode they want. Do not assume hardware.

## Workflow selection

First classify the request into one mode:

1. `inspect-zml`
2. `run-sil-scenario`
3. `run-no-sync-scenario`
4. `run-flakiness-check`
5. `fetch-hil-logs`
6. `launch-phoenix-hil`
7. `inspect-run-output`

If a request spans multiple modes, start with the safest read-only one.

## Default post-run upload for local SIL runs

For `run-sil-scenario`, `run-no-sync-scenario`, and `run-flakiness-check`:

1. Before launching Phoenix, confirm whether the run itself needs confirmation under the normal safety gates.
2. After a successful local run, resolve the produced log directory. Prefer the run-specific directory when available; otherwise fall back to `.phoenix/logs/latest/`.
3. If `PHOENIX_LOG_UPLOAD_S3_PREFIX` is set, upload that log directory with `phoenix/debug/scripts/upload_local_log_to_s3.sh` or `$upload_local_log_to_s3`.
4. Include the final S3 path and Baraza link in the response when upload succeeds.
5. If upload cannot happen because AWS auth is missing/expired or the destination prefix is unavailable, say that clearly instead of silently skipping it.

Do not auto-upload logs for HIL launches, fetched HIL logs, or purely read-only inspection requests.

## 1) inspect-zml

For an existing ZML path, start with read-only inspection:

```sh
zml -z "/path/to/compute_a.zml.zst" list
zml -z "/path/to/compute_a.zml.zst" events
zml -z "/path/to/compute_a.zml.zst" print '*GPS*'
```

Useful local Phoenix log roots:

- `.phoenix/logs/latest/`
- `.phoenix/logs/by_scenario/<scenario>/`

If `zml` is not available and the user wants CLI inspection, the checked-in setup in `tools/zml/README.md` is:

```sh
bazel build //tools/zml
tar -C /tmp xzf bazel-bin/tools/zml/zipline_zml-<version>.tar.gz
pip install -e /tmp/zipline_zml-<version>
```

Only do that with confirmation because it builds and installs tooling.

## 2) run-sil-scenario

Phoenix SIL scenario targets are spread across `ash/scenarios/**` packages such as:

- `nominal`
- `off_nominal`
- `perception`
- `no_sync`
- `executive_nominal`
- `executive_off_nominal`
- `gnc_off_nominal`
- `framework`

If the user gives only a scenario name, first confirm the Bazel label by reading the matching `BUILD.bazel` in that package.

Common local shapes:

```sh
bazel test //ash/scenarios/nominal:redock_nest0 --config=debug
bazel test //ash/scenarios/nominal:delivery_nest0_mission_assignment --config=debug
```

`--config=debug` is the documented default for local Phoenix iteration because it surfaces subprocess stdout/stderr and avoids stale Bazel cache results.

Optional debug follow-up:

```sh
bazel test //ash/scenarios/nominal:redock_nest0 --config=debug --test_arg=--enable-perfetto-tracing
```

That creates a `trace.gz` file under the scenario log directory.

Important caveat: `ash/scenarios/hil/*.pbtxt` are config-only inputs for HIL suites. Do not treat `ash/scenarios/hil` as a standalone runnable Phoenix scenario package; launch those configs through the Phoenix HIL tests or workflow dispatch.

## 3) run-no-sync-scenario

`ash/scenarios/no_sync` contains SIL no-sync scenarios with their own Bazel targets.

Common targets from `ash/scenarios/no_sync/BUILD.bazel` include:

- `redock_nest0_no_sync`
- `redock_nest0_back_to_back_no_sync`
- `delivery_nest0_no_sync`
- `lower_and_raise_droid_no_sync`
- `autokiosk_load_and_deliver_no_sync`
- the matching `*_exec_v3` variants

Example commands:

```sh
bazel test //ash/scenarios/no_sync:redock_nest0_no_sync --config=debug
bazel test //ash/scenarios/no_sync:delivery_nest0_no_sync --config=debug
```

`redock_nest0_no_sync` is documented as an `exclusive` scenario in CI, but it is still a normal direct target for local runs.

## 4) run-flakiness-check

Use this when the user wants to run the same Phoenix scenario multiple times, especially for `no_sync` cases.

Start with one explicit scenario label unless the user asks for a batch.

### Quick local repro loop

For an interactive flakiness check, use a small repeat count first:

```sh
bazel test //ash/scenarios/no_sync:redock_nest0_no_sync \
  --config=debug \
  --runs_per_test=10
```

### CI-like repeated run shape

The checked-in nightly metrics pipeline uses this shape for no-sync flakiness data:

```sh
bazel test //ash/scenarios/no_sync:redock_nest0_no_sync \
  --test_tag_filters=phoenix-scenario \
  --nocache_test_results \
  --runs_per_test=50
```

It uses the same pattern for:

- `//ash/scenarios/no_sync:lower_and_raise_droid_no_sync`
- `//ash/scenarios/no_sync:delivery_nest0_no_sync`

If the user explicitly wants Bazel flake detection semantics, you can add:

```sh
--runs_per_test_detects_flakes
```

Use that only when they want flake classification rather than just repeated execution.

### Determinism metrics follow-up

If the user wants comparison metrics rather than manual log inspection, the checked-in helper is:

```sh
./buildkite/ci/bin/upload_phoenix_determinism_metrics.sh //ash/scenarios/nominal:redock_nest0
```

This expects `HONEYCOMB_API_KEY` for upload.

For repeated runs, inspect `by_scenario/<scenario>` rather than relying only on `latest`.

## 5) fetch-hil-logs

Use the checked-in HIL log fetcher to sync artifacts for a git SHA:

```sh
fetch-hil-logs <sha>
# or
hil-tools-cli fetch_hil_logs <sha> --local-directory ~/.hil
```

The underlying source is:

```text
s3://platform2-testing-logs/p2-zip-system-hil/<sha>
```

After download, inspect under:

```text
~/.hil/<sha>/<runner>/<run_number>_<run_attempt>/<test>/...
```

Prioritize:

- `**/*.zml` and `**/*.zml.zst`
- `**/validators/*/*_results.json`
- `**/*stdout.txt`
- `**/*stderr.txt`

## 6) launch-phoenix-hil

Prefer the existing GitHub workflow for shared HILs unless the user already has a claimed box/container and explicitly wants local execution.

### GitHub workflow dispatch

Confirm first, then dispatch the checked-in workflow:

```sh
gh workflow run p2-zip-system-hil-build.yml \
  --ref <branch> \
  --field dispatch_option=PHOENIX_ZIP_DELIVERY
```

Common Phoenix dispatch options from `.github/workflows/p2-zip-system-hil-build.yml`:

- `PHOENIX_ZIP_REDOCK`
- `PHOENIX_ZIP_DELIVERY`
- `PHOENIX_ZIP_AUTOKIOSK`
- `PHOENIX_ZIP_DELIVERY_LONG`
- `PHOENIX_ZIP_DELIVERY_EV3`
- `PHOENIX_ZIP_FIXED_WING`
- `PHOENIX_ZIP_LOWER_AND_RAISE_DROID`
- `PHOENIX_SUITE`

Optional fields:

```sh
--field override_hil_runner='p2-ev-zp-hil-2'
```

Use bare enum values like `PHOENIX_ZIP_DELIVERY`; the workflow input parser can also accept the UI label text, but the enum form is cleaner.
Only pass `override_version_set` when the user explicitly wants to override the dispatch default for that test, and match the EV/test variant carefully. The workflow resolves version-set inputs before execution; that is safer than passing the raw checked-in Phoenix version-set JSON directly to a local HIL pytest run.

Do not dispatch suite or all-HIL variants without explicit approval.

Manual workflow dispatches also fail a stale-branch guard when the branch is more than 48 hours behind `develop`. Only use:

```sh
--field workflow_flags='--unsafe-allow-old-branches'
```

if the user explicitly wants to override that protection.

### Local / claimed HIL execution

Enter the HIL container:

```sh
./hil/dev_entrypoint.sh zsh
```

Only use local / claimed-HIL execution when one of these is true:

- the user explicitly wants to iterate on the software already deployed on that claimed box, or
- you have a **resolved** version-set JSON for this exact run.

For a reproducible local run, prefer passing the resolved version set:

```sh
bazel run //hil/p2_tests/phoenix_missions:phoenix -- \
  -k 'test_missions[phoenix_delivery]' \
  --param version_set=/path/to/resolved_version_set.json
```

If you do **not** have a resolved version-set JSON, do not pretend the local run is a clean repro. In that case, either:

- stop and prefer workflow dispatch, or
- say clearly that you are re-running against the software already on the claimed HIL.

Before doing this, verify the local claimed-HIL environment already has a usable `SIM_DOCKER_IMAGE` exported or that the resolved version set contains a non-empty `infra.sim_image`.

Do **not** assume the checked-in Phoenix version-set files are safe local defaults for `--param version_set=...`; the raw files leave `infra.sim_image` empty and rely on workflow-side resolution.

Useful filter mappings from `hil/ci/workflow/utils/default_test_configs.py`:

- `PHOENIX_ZIP_REDOCK` -> `-k 'test_missions[phoenix_redock]'`
- `PHOENIX_ZIP_DELIVERY` -> `-k 'test_missions[phoenix_delivery]'`
- `PHOENIX_ZIP_DELIVERY_EV3` -> `-k 'test_missions[phoenix_delivery_ev3]'` on an EV3-compatible runner with a resolved sim image
- `PHOENIX_ZIP_DELIVERY_LONG` -> `-k 'test_missions[phoenix_delivery_long_transit]'`
- `PHOENIX_ZIP_AUTOKIOSK` -> `-k 'test_missions[phoenix_autokiosk_load_and_deliver]'`
- `PHOENIX_ZIP_FIXED_WING` -> `-k 'test_missions[phoenix_fixed_wing]'`
- `PHOENIX_ZIP_LOWER_AND_RAISE_DROID` -> `-k 'test_missions[phoenix_lower_and_raise_droid]'`
- `PHOENIX_SUITE` -> `-m phoenix_suite`

Local HTF/pytest exports go to `${HTF_OUTPUT_DIRECTORY:-~/runner_output}` and are usually written into per-test folders named like `<short_test_name>_<uuid>/`.

## 7) inspect-run-output

For Phoenix SIL runs:

- inspect `.phoenix/logs/latest/.../compute_{a,b}.zml[.zst]`
- inspect `.phoenix/logs/by_scenario/<scenario>/...`
- inspect `validators/**/*_results.json`
- inspect service `*_stdout.txt` and `*_stderr.txt`

For fetched or CI HIL logs:

- start at `~/.hil/<sha>/...`
- identify the specific runner / run attempt / test directory first
- inspect validator JSON before deep-diving into ZML
- use service stderr/stdout to find the failing component, then use `zml` to inspect the relevant compute logs

If the user wants local visualization, `ash/scenarios/README.md` documents the `fs:///...` LogPlots path shape for `.phoenix/logs/latest/...`.

If the user wants a shareable LogPlots link from a local Phoenix log directory, either run `phoenix/debug/scripts/upload_local_log_to_s3.sh` directly or use `$upload_local_log_to_s3`.

## Response pattern

When using this skill, reply with:

- chosen mode
- the exact Phoenix label or identifiers being used
- the safest next read-only step
- any confirmation needed before launching Phoenix, repeated flakiness runs, or real HIL
- if a local Phoenix run was executed and uploaded, the final S3 path and Baraza link
