# Phoenix Workflow Command Recipes

These examples never replace the approval and decision-packet gates in `SKILL.md`.

## Local SIL and no_sync

```sh
bazel test //ash/scenarios/nominal:redock_nest0 --config=debug
bazel test //ash/scenarios/no_sync:redock_nest0_no_sync --config=debug
```

Confirm the exact label from its `BUILD.bazel`. Repeats such as `--runs_per_test=10` require approval of the count; add `--runs_per_test_detects_flakes` only when explicit Bazel flake semantics are requested.

## HIL fetch and dispatch

```sh
fetch-hil-logs <sha>
hil-tools-cli fetch_hil_logs <sha> --local-directory ~/.hil
gh workflow run p2-zip-system-hil-build.yml --ref <branch> --field dispatch_option=PHOENIX_ZIP_DELIVERY
```

Fetches use `s3://platform2-testing-logs/p2-zip-system-hil/<sha>` and normally land under `~/.hil/<sha>/...`. Each fetch or dispatch requires explicit active-prompt network/auth approval. Suite/all-HIL options, runner overrides, stale-branch overrides, and hardware actions require exact separate approval.

## Local claimed HIL

```sh
./hil/dev_entrypoint.sh zsh
bazel run //hil/p2_tests/phoenix_missions:phoenix -- \
  -k 'test_missions[phoenix_delivery]' \
  --param version_set=/path/to/resolved_version_set.json
```

Require a claimed box/container and a resolved version set with usable `infra.sim_image`, or an explicit decision to use software already deployed on that HIL.

## Upload

The checked-in leaf helper is:

```sh
phoenix/debug/scripts/upload_local_log_to_s3.sh
```

Use it only after exact source, destination/prefix, auth/network state, expected output, and upload approval are resolved. Never auto-upload after a run.
