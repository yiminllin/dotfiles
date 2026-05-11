---
name: phoenix_inspector
description: Canonical read-only Phoenix/HIL/GHA/ZML evidence inspector for inventory, bounded text artifact search, field-first ZML discovery, extraction, pass/fail compare, reusable specs, and batch taxonomy.
---

# Phoenix Inspector

Use this skill for read-only Phoenix inspection and evidence work: GHA HIL run/job or S3 artifact inventory, local Phoenix/HIL/SIL/sim/real-flight bundle inventory, bounded non-ZML text artifact search, field-first ZML discovery, topic discovery/extraction/CSV, pass/fail comparison, reusable specs, and batch taxonomy.

Do **not** use this skill to launch SIL/HIL workflows, upload artifacts, mutate PRs/Jira, refresh credentials, or start interactive auth. Hand launch/execution work to `phoenix-workflows`.

For the longer operator guide, see `opencode/.config/opencode/scripts/phoenix_inspector/README.md`.

## Decision table

| Intent | Command path |
|---|---|
| New or uncertain source | `inventory <source>` first, then follow `next_commands`. |
| Inventory-oriented evidence report | `inspect <source>`; add `--spec recipe.yaml` for repeatable recipes. |
| Known field, unknown topic | `fields <source> --fuzzy FIELD` or `find-field`; then `extract`. |
| Known topic + field | `extract <zml-or-log-dir> --topic TOPIC --field FIELD`. |
| Text log signatures | `search-logs`, `validators`, or `journal` on local inventoried logs. |
| Passing vs failing signal contrast | `compare --fail FAIL --pass PASS --topic TOPIC --field FIELD`; use `--preset`/`--spec` only for known bundles. |
| Recent HIL source discovery or preset sync | `recent-hil`, `sync-check`, or `inventory <GHA_URL>`. |
| Repeated investigation recipe | `spec init --from-last-run`, then `spec validate --fixture ...`. |

## Command templates

```bash
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" --help
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" inventory <source> --format markdown --out-dir /tmp/pi
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" inspect <source> --out-dir /tmp/pi
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" inspect <source> --spec question.yaml --out-dir /tmp/pi
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" search-logs <source> --query 'Traceback|Exception|Error Code' --max-matches 100 --context 2 --format json
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" validators <source> --format markdown
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" journal <source> --query 'watchdog|service|restart' --format markdown
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" topics <source.zml.zst> --pattern nav --systems-root /Systems --format json
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" topics <source.zml.zst> --fuzzy controller --limit 20 --systems-root /Systems --format json
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" fields <source> --fuzzy flight_phase_for_controller --sample-top 0 --systems-root /Systems --format json
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" extract <source.zml.zst> --topic /nav --field pose.x --systems-root /Systems --csv /tmp/nav.csv
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" compare --fail fail.zml.zst --pass pass.zml.zst --topic /nav --field pose.x --systems-root /Systems --out-dir /tmp/pi
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" recent-hil --preset zip_autokiosk --passing --max-matches 3
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" sync-check --systems-root /Systems
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" taxonomy recent-hil --limit 1000 --max-matches 3 --load-evidence --csv /tmp/taxonomy.csv --out-dir /tmp/pi
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" spec init --name my-question --from-last-run --out my-question.yaml
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" spec validate my-question.yaml --fixture /path/to/fixture
```

`<source>` may be a GitHub Actions run/job URL, `s3://` prefix, local Phoenix log directory or extracted bundle, local archive, local `.zml`/`.zml.zst`, HIL evidence packet JSON, or `test_record.json`. A bare flight/mission ID is not a v1 source; return the structured unsupported-source blocker and ask for a local bundle or packet.

## Routing choices

- Use `inventory` first when the source shape or available artifacts are uncertain.
- Use `inspect` for source inventory-oriented evidence reports and next-command routing.
- After inventory, use `search-logs <source> --query REGEX`, `validators <source>`, or `journal <source>` for bounded line-oriented search of local non-ZML text artifacts such as `phoenix.log`, `test_record.json`, `test_log_*.log`, validator/alarm outputs, and journal/journalctl/process/system logs. These commands search only inventoried local text artifacts, skip binary/ZML/archive/packet artifacts, cap total matches, include line numbers/context, and return a blocker for GHA/S3/packet sources until a bounded local bundle or selected local logs are provided.
- Use `fields`/`extract` for ZML signal content. Do not try to use text search as a ZML decoder.
- Known local ZML/ZST + topic + field: go directly to `extract`; it skips broad topic/field discovery and extracts that topic/field selection.
- Known field/signal but unknown topic: run `fields <source> --fuzzy FIELD_QUERY` first. It searches candidate ZMLs field-first via metadata/schema/index where available, probes independent files with bounded `--workers`, samples only bounded top candidates when needed or requested (`--sample-top N`), and returns ranked `zml_path`/`topic`/`field_path` matches.
- Known topic family but unknown exact topic: use `topics` or `topics --fuzzy`; do not use topic search for known-field discovery.
- Use `compare --topic --field`, `compare --preset`, or `compare --spec` for generic differential evidence workflows.
- Use `inspect --spec` when a debugging question is repeatable as an ad hoc recipe.
- Use `spec init --from-last-run`, then `spec validate` with fixtures when the question recurs.
- Use `recent-hil` for source discovery only; use `taxonomy recent-hil` for batch labeling. For both commands, `--limit` is the workflow-run search/list bound before filtering (sparse presets may need values such as `1000`), while `--max-matches` is the returned/processed matching job-row count. `taxonomy recent-hil` remains lightweight by default; add `--load-evidence` only when per-row bounded HIL evidence should be loaded for the selected matches.
- Hand off to `phoenix-workflows` for scenario/HIL launch, rerun, fetch/upload, or hardware workflows.

## Evidence and blocker contract

Reports include summary, source/inventory, evidence table, signal/check findings, timebase/alignment, proves/does-not-prove, blockers, output paths, and next commands. Treat `blockers` as first-class data.

For final answers, include only material trace: exact source/report paths, decisive commands, what evidence supports, what it does not prove, and exact auth/network/tool/user-decision blockers.

Do not convert signal deltas or log summaries into causal RCA unless artifact/code evidence supports that claim. If only one failing side exists, state the missing comparison.

## Backend and safety boundaries

- Phoenix-aware ZML commands default `--systems-root` to `/Systems` when that checkout exists. Bazel `zml-conv` fallback and schema/registry behavior use that root and report `systems_root`, `cwd`, selected backend, direct-vs-Bazel invocation, and fallbacks. Standalone `.zml`/`.zml.zst` files can still use portable `zml-cli` or `local-text` without requiring `/Systems`.
- Default `--backend auto` order is `zml-conv` first, then `zml-cli`; prefer `zml-conv` for decoded reads/extraction and use `zml-cli` for topic listing, metadata, raw/schema-aware fallback, and portable local inspection. `local-text` is only for fixtures, JSONL, and simple local testing.
- Field discovery reports whether it used `metadata`/`zml-list`, `sample`, schema, or fallback; direct known topic/field extraction can fall back to schema-aware `zml print_raw`, reported as `zml-print-raw` with decoded failure metadata.
- Default output is Markdown on stdout. Use `--format json|both` for machine-readable reports, `--out-dir /tmp/pi` for report files, and `--csv /tmp/pi/<name>.csv` for extract/compare samples.
- Do not broad-scan `/` or bucket roots. Inspect only the explicit source or selected artifact paths from an evidence packet.
- Do not download for `search-logs`, `validators`, or `journal`; if the source is GHA/S3/packet-only, report the structured local-artifact blocker and ask for a bounded fetched/extracted bundle first.
- Optional live GHA/S3 checks are read-only and only when credentials already work. Do not run `gh auth login`, `aws sso login`, browser auth, uploads, workflow dispatches, or artifact mutation.
- For missing auth, report the exact command/action/path and required user action; continue offline/local validation when possible.

## Recipes and presets

Current domain bundles are non-diagnostic `--preset` selections or reusable `spec` recipes. Do not imply diagnostic authority from presets, specs, or inventory reports without supporting artifact/code evidence.
