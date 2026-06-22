# Phoenix Workflow Command Recipes

Load this reference only after the `phoenix-workflows` mode is chosen or when the user asks for concrete commands, optional flags, target examples, HIL dispatch options, or local HIL filter mappings. Keep safety gates and decision packets in `SKILL.md`; these recipes do not replace confirmation, auth, network, or hardware checks.

## Local SIL scenarios

Phoenix SIL scenario targets are spread across `ash/scenarios/**` packages such as:

- `nominal`
- `off_nominal`
- `perception`
- `no_sync`
- `executive_nominal`
- `executive_off_nominal`
- `gnc_off_nominal`
- `framework`

Common local shapes:

```sh
bazel test //ash/scenarios/nominal:redock_nest0 --config=debug
bazel test //ash/scenarios/nominal:delivery_nest0_mission_assignment --config=debug
```

Optional debug follow-up:

```sh
bazel test //ash/scenarios/nominal:redock_nest0 --config=debug --test_arg=--enable-perfetto-tracing
```

That creates a `trace.gz` file under the scenario log directory.

Important caveat: `ash/scenarios/hil/*.pbtxt` are config-only inputs for HIL suites. Do not treat `ash/scenarios/hil` as a standalone runnable Phoenix scenario package; launch those configs through the Phoenix HIL tests or workflow dispatch.

## no_sync scenarios

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

## Flakiness and determinism

For an interactive flakiness check, use a small repeat count first:

```sh
bazel test //ash/scenarios/no_sync:redock_nest0_no_sync \
  --config=debug \
  --runs_per_test=10
```

The checked-in nightly metrics pipeline uses this CI-like shape for no-sync flakiness data:

```sh
bazel test //ash/scenarios/no_sync:redock_nest0_no_sync \
  --test_tag_filters=phoenix-scenario \
  --nocache_test_results \
  --runs_per_test=50
```

It uses the same pattern for:

- `//ash/scenarios/no_sync:lower_and_raise_droid_no_sync`
- `//ash/scenarios/no_sync:delivery_nest0_no_sync`

If the user explicitly wants Bazel flake detection semantics, add:

```sh
--runs_per_test_detects_flakes
```

If the user wants comparison metrics rather than manual log inspection, the checked-in helper is:

```sh
./buildkite/ci/bin/upload_phoenix_determinism_metrics.sh //ash/scenarios/nominal:redock_nest0
```

This expects `HONEYCOMB_API_KEY` for upload.

## HIL log fetch

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

Prioritize when seeding `$phoenix_inspector`:

- `**/*.zml` and `**/*.zml.zst`
- `**/validators/*/*_results.json`
- `**/*stdout.txt`
- `**/*stderr.txt`

## HIL GitHub workflow dispatch

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

Optional field:

```sh
--field override_hil_runner='p2-ev-zp-hil-2'
```

Manual workflow dispatches fail a stale-branch guard when the branch is more than 48 hours behind `develop`. Only use:

```sh
--field workflow_flags='--unsafe-allow-old-branches'
```

if the user explicitly wants to override that protection.

## Local / claimed HIL execution

Enter the HIL container:

```sh
./hil/dev_entrypoint.sh zsh
```

For a reproducible local run, prefer passing the resolved version set:

```sh
bazel run //hil/p2_tests/phoenix_missions:phoenix -- \
  -k 'test_missions[phoenix_delivery]' \
  --param version_set=/path/to/resolved_version_set.json
```

Useful filter mappings from `hil/ci/workflow/utils/default_test_configs.py`:

- `PHOENIX_ZIP_REDOCK` -> `-k 'test_missions[phoenix_redock]'`
- `PHOENIX_ZIP_DELIVERY` -> `-k 'test_missions[phoenix_delivery]'`
- `PHOENIX_ZIP_DELIVERY_EV3` -> `-k 'test_missions[phoenix_delivery_ev3]'` on an EV3-compatible runner with a resolved sim image
- `PHOENIX_ZIP_DELIVERY_LONG` -> `-k 'test_missions[phoenix_delivery_long_transit]'`
- `PHOENIX_ZIP_AUTOKIOSK` -> `-k 'test_missions[phoenix_autokiosk_load_and_deliver]'`
- `PHOENIX_ZIP_FIXED_WING` -> `-k 'test_missions[phoenix_fixed_wing]'`
- `PHOENIX_ZIP_LOWER_AND_RAISE_DROID` -> `-k 'test_missions[phoenix_lower_and_raise_droid]'`
- `PHOENIX_SUITE` -> `-m phoenix_suite`

## Local log upload

For explicit upload/presign/Baraza/LogPlots/dashboard requests, use `$upload_local_log_to_s3` when available; otherwise use:

```sh
phoenix/debug/scripts/upload_local_log_to_s3.sh
```

The helper/script is a leaf action only after the mode, source log directory or artifact, destination/prefix, auth/network status, and expected link/artifact are clear in the decision packet.
