# Phoenix Inspector Usage Guide

`phoenix_inspector.py` is the read-only Phoenix/HIL/GHA/ZML evidence helper for agents. It inventories explicit sources, searches already-local text logs, discovers/extracts ZML fields, compares pass/fail signals, and packages repeatable recipes.

Canonical invocation:

```bash
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" <command> ...
```

## Intent → command

| If you know... | Run... | Then... |
|---|---|---|
| Only a source URL/path | `inventory <source> --out-dir /tmp/pi` | Use reported artifacts and `next_commands`. |
| Field/signal name, not topic | `fields <source> --fuzzy FIELD` or `find-field` | Run `extract` with the returned `zml_path`/`topic`/`field_path`. |
| Topic and field | `extract <source.zml.zst> --topic TOPIC --field FIELD --csv /tmp/pi/out.csv` | Use the report/CSV for evidence or plotting prep. |
| Text log pattern | `search-logs <local-log-dir> --query REGEX --context 2` | Use `validators` or `journal` for common presets. |
| Failing and passing ZMLs | `compare --fail fail.zml.zst --pass pass.zml.zst --topic TOPIC --field FIELD --out-dir /tmp/pi` | State what the delta supports and what it does not prove. |
| Recent HIL source needed | `recent-hil ...`, `sync-check --systems-root /Systems`, or `inventory <GHA_URL>` | Treat remote reads as bounded discovery, not diagnosis. |
| Recurring recipe | `spec init --name NAME --from-last-run --out NAME.yaml` | Validate with `spec validate NAME.yaml --fixture /path/to/fixture`. |

## Supported sources

- GitHub Actions run/job URL.
- `s3://bucket/prefix` source, never a bucket root.
- Local Phoenix/HIL/SIL log directory, extracted bundle, or supported local archive.
- Local HIL evidence packet JSON or `test_record.json`.
- Local `.zml` or `.zml.zst` file.

A bare flight/mission ID is intentionally unsupported in v1; ask for a local bundle, packet, GHA URL, or explicit S3 prefix.

## Backend policy

- Default `--backend auto` tries `zml-conv` before `zml-cli`.
- Prefer `zml-conv` for Phoenix-aware decoded reads/extraction when `/Systems` is available; `--systems-root` defaults to `/Systems` when present.
- Use `zml-cli` for topic listing, metadata, raw/schema-aware fallback, and portable local inspection.
- Use `local-text` only for fixtures, JSONL, and simple local tests; do not present it as production ZML decoding.

## Safety and handoff rules

- Read-only only: no launch, upload, workflow dispatch, mutation, auth refresh, or browser login.
- Remote/GHA/S3 commands may require existing credentials. If credentials are missing, stop with the exact blocked action and ask the user to refresh or provide a bounded local bundle.
- `search-logs`, `validators`, and `journal` do not download. For remote/packet-only sources, ask for selected local logs or a bounded fetched/extracted bundle.
- Do not broad-scan `/`, `/Systems`, home directories, or S3 bucket roots. Inspect explicit sources and selected artifact paths only.

## Output and local validation workspace

- Default output is Markdown on stdout.
- Use `--format json` or `--format both` when another tool will consume the report.
- Use `--out-dir /tmp/pi` for report files; use a task-specific directory such as `/tmp/pi-validation` for fixture checks.
- `extract` and `compare` can write CSVs, e.g. `--csv /tmp/pi/nav.csv`.
- For `recent-hil` and `taxonomy recent-hil`, `--limit` is the number of workflow runs listed/searched before filtering. Sparse presets may need high values such as `--limit 1000`. `--max-matches` is the number of matching jobs/rows returned and processed after filtering.
- `taxonomy recent-hil` is candidate-level by default. Add `--load-evidence` to load bounded per-job HIL evidence only for the returned `--max-matches` candidates and include evidence status/path/summary in CSV, Markdown, and JSON rows.
- Validate repeatable recipes offline with local fixtures:

```bash
python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py" spec validate recipe.yaml --fixture /tmp/pi-fixtures/sample-log
```
