---
name: phoenix_inspector
description: Canonical read-only Phoenix/HIL/GHA/ZML evidence inspector for inventory, bounded text artifact search, field-first ZML discovery, extraction, CSV summary, pass/fail compare, and recent HIL lookup.
---

# Phoenix Inspector

Use this skill for read-only Phoenix inspection and evidence work: GHA HIL run/job or S3 artifact inventory, local Phoenix/HIL/SIL/sim/real-flight bundle inventory, bounded non-ZML text artifact search, field-first ZML discovery, topic discovery/extraction/CSV, pass/fail comparison, and recent HIL source lookup.

Do **not** use this skill to launch SIL/HIL workflows, upload artifacts, mutate PRs/Jira, refresh credentials, or start interactive auth. Hand launch/execution/fetch/upload work to `phoenix-workflows`.

For the richer operator/manual-validation guide, including copy-pasteable local fixture, local ZML/log, compare/summary, remote, and expected-blocker workflows, see `scripts/phoenix_inspector/README.md`.

## Decision table

| Intent | Command path |
|---|---|
| Unknown source shape or available artifacts | `inventory <source>` first, then follow `next_commands`. |
| Known signal/field, unknown topic | `fields <source> --fuzzy FIELD` or `find-field`; do not start with inventory just to discover the topic. |
| Known topic + field | `extract <zml-or-log-dir> --topic TOPIC --field FIELD`. |
| Known topic, want all values | `extract <zml-or-log-dir> --topic TOPIC --all-fields --csv /tmp/topic.csv`, then `summary`. |
| Text log signatures | `search-logs`, `validators`, or `journal` on local inventoried logs. |
| Pass/fail signal question with fail/pass ZMLs and known topic/field/preset | `compare` directly with `--topic --field` or `--preset`. |
| Recent HIL source discovery | `recent-hil` or `inventory <GHA_URL>`. |

## Command templates

Agent investigations should save report artifacts with `--format both --out-dir /tmp/pi/<short-task>` where useful for `inventory`, `topics`, `fields`/`find-field`, `compare`, and `recent-hil` so Markdown and JSON are both available. Human/manual CLI use can omit these flags and keep the default Markdown stdout. When `--out-dir` is present, stdout still prints the rendered report (`both` prints Markdown) and the report lists written output paths. For `extract`, write sample rows with `--csv /tmp/pi/<short-task>/<name>.csv`; add `--format both --out-dir /tmp/pi/<short-task>` when an extract report artifact is useful.

```bash
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" --help
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" inventory -h
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" extract -h
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" summary -h
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" inventory <source> --format both --out-dir /tmp/pi/<short-task>
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" search-logs <source> --query 'Traceback|Exception|Error Code' --max-matches 100 --context 2 --format json --out-dir /tmp/pi/<short-task>
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" validators <source> --out-dir /tmp/pi/<short-task>
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" journal <source> --query 'watchdog|service|restart' --out-dir /tmp/pi/<short-task>
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" topics <source.zml.zst> --pattern nav --systems-root /Systems --format both --out-dir /tmp/pi/<short-task>
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" topics <source.zml.zst> --fuzzy controller --limit 20 --systems-root /Systems --format both --out-dir /tmp/pi/<short-task>
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" fields <source> --fuzzy flight_phase_for_controller --sample-top 0 --systems-root /Systems --format both --out-dir /tmp/pi/<short-task>
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" extract <source.zml.zst> --topic /nav --field pose.x --systems-root /Systems --csv /tmp/pi/<short-task>/nav.csv --format both --out-dir /tmp/pi/<short-task>
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" extract <source.zml.zst> --topic /nav --all-fields --systems-root /Systems --csv /tmp/pi/<short-task>/nav-all.csv --format both --out-dir /tmp/pi/<short-task>
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" summary /tmp/pi/<short-task>/nav-all.csv --metric transitions --metric minmax --metric delta --field pose.x --format both --out-dir /tmp/pi/<short-task>
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" compare --fail fail.zml.zst --pass pass.zml.zst --topic /nav --field pose.x --systems-root /Systems --format both --out-dir /tmp/pi/<short-task>
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" compare --fail fail.zml.zst --pass pass.zml.zst --preset gnss-timing --systems-root /Systems --format both --out-dir /tmp/pi/<short-task>
python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" recent-hil --preset zip_autokiosk --passing --max-matches 3 --format both --out-dir /tmp/pi/<short-task>
```

`<source>` may be a GitHub Actions run/job URL, non-root `s3://` prefix, local Phoenix log directory or extracted bundle, or local `.zml`/`.zml.zst`. Standalone packet/test_record JSON files, archives, and bare flight/mission IDs are not v1 inventory sources; return the structured unsupported-source blocker and ask for an extracted bundle, GHA URL, explicit S3 prefix, or local ZML/ZST.

## Routing choices

- Use `inventory` first only when the source shape or available artifacts are uncertain.
- After inventory, use `search-logs <source> --query REGEX`, `validators <source>`, or `journal <source>` for bounded line-oriented search of local non-ZML text artifacts such as `phoenix.log`, `test_record.json`, `test_log_*.log`, validator/alarm outputs, and journal/journalctl/process/system logs. These commands search only inventoried local text artifacts, skip binary/ZML/archive artifacts, cap total matches, include line numbers/context, and return a blocker for GHA/S3 sources until a bounded local bundle or selected local logs are provided.
- Use `fields`/`extract` for ZML signal content. Do not try to use text search as a ZML decoder.
- Known local ZML/ZST + topic + field: go directly to `extract`; it skips broad topic/field discovery and extracts that topic/field selection.
- Known local ZML/ZST + topic but exploratory fields: use `extract --all-fields --csv ...`, then `summary <csv> --metric transitions|minmax|delta` to triage extracted values by path/topic/field. `summary` is built for Phoenix Inspector's `path,topic,timestamp,field,value` CSV shape; other CSVs are best-effort only if they already have timestamp/field/value columns.
- Known field/signal but unknown topic: run `fields <source> --fuzzy FIELD_QUERY` first. It searches candidate ZMLs field-first via metadata/schema/index where available, probes independent files with bounded `--workers`, samples only bounded top candidates when needed or requested (`--sample-top N`), and returns ranked `zml_path`/`topic`/`field_path` matches.
- Known topic family but unknown exact topic: use `topics` or `topics --fuzzy`; do not use topic search for known-field discovery.
- Use `compare --topic --field` or `compare --preset` directly for pass/fail signal questions when the fail/pass ZMLs and topic/field or preset are known.
- Use `recent-hil` for source discovery only. `--limit` is the workflow-run search/list bound before filtering (sparse presets may need values such as `1000`), while `--max-matches` is the returned matching job-row count.
- Hand off to `phoenix-workflows` for scenario/HIL launch, rerun, fetch/upload, or hardware workflows.

## Evidence and blocker contract

Reports include summary, source/inventory, evidence table, signal/check findings, timebase/alignment, proves/does-not-prove, blockers, output paths, and next commands. Treat `blockers` as first-class data.

For final answers, include only material trace: exact source/report paths, decisive commands, what evidence supports, what it does not prove, and exact auth/network/tool/user-decision blockers.

Do not convert signal deltas or log summaries into causal RCA unless artifact/code evidence supports that claim. If only one failing side exists, state the missing comparison.

## Backend and safety boundaries

- Phoenix-aware ZML commands default `--systems-root` to `/Systems` when that checkout exists. Bazel `zml-conv` fallback and schema/registry behavior use that root and report `systems_root`, `cwd`, selected backend, direct-vs-Bazel invocation, and fallbacks. Standalone `.zml`/`.zml.zst` files can still use portable `zml-cli` or `local-text` without requiring `/Systems`.
- Default `--backend auto` order is `zml-conv` first, then `zml-cli`; prefer `zml-conv` for decoded reads/extraction and use `zml-cli` for topic listing, metadata, raw/schema-aware fallback, and portable local inspection. `local-text` is only for fixtures, JSONL, and simple local testing.
- Field discovery reports whether it used `metadata`/`zml-list`, `sample`, schema, or fallback; direct known topic/field extraction can fall back to schema-aware `zml print_raw`, reported as `zml-print-raw` with decoded failure metadata.
- Default output is Markdown on stdout for human/manual use. `--out-dir` additionally saves report files without replacing stdout; `--format both` prints Markdown while writing Markdown and JSON. For agent investigations, prefer `--format both --out-dir /tmp/pi/<short-task>` on supported report commands so Markdown and JSON artifacts are both available; use `--csv /tmp/pi/<short-task>/<name>.csv` for extract/compare sample rows.
- Do not broad-scan `/` or bucket roots. Inspect only explicit supported sources or selected local artifact paths.
- Do not download for `search-logs`, `validators`, or `journal`; if the source is GHA/S3, report the structured local-artifact blocker and ask for a bounded fetched/extracted bundle first.
- Optional live GHA/S3 checks are read-only and only when credentials already work. Do not run `gh auth login`, `aws sso login`, browser auth, uploads, workflow dispatches, or artifact mutation.
- For missing auth, report the exact command/action/path and required user action; continue offline/local validation when possible.

## Presets

Current domain bundles are non-diagnostic `--preset` selections. Do not imply diagnostic authority from presets or inventory reports without supporting artifact/code evidence.
