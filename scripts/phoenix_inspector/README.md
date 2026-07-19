# Phoenix Inspector Usage Guide

`phoenix_inspector.py` is the read-only Phoenix/HIL/GHA/ZML evidence helper for agents and humans. It inventories explicit sources, searches already-local text logs, discovers/extracts ZML fields, compares pass/fail signals, summarizes extracted CSVs, and finds recent HIL source candidates.

Canonical invocation:

```bash
PI="$HOME/dotfiles/scripts/phoenix_inspector.py"
python3 "$PI" <command> ...
```

For source-tree validation in this dotfiles repo, use:

```bash
PI="scripts/phoenix_inspector.py"
```

Human/manual CLI use defaults to Markdown on stdout. `--out-dir` saves report files without changing stdout: `--format markdown` prints Markdown, `--format json` prints JSON, and `--format both` prints Markdown while writing both files. For agent investigations and report-producing workflows, prefer `--format both --out-dir /tmp/pi/<short-task>` on `inventory`, `topics`, `fields`/`find-field`, `compare`, and `recent-hil` when artifacts are useful. Use `extract --csv /tmp/pi/<short-task>/<name>.csv` for sample rows, adding `--format both --out-dir /tmp/pi/<short-task>` when an extract report artifact is useful.

## Recommended manual validation order

### 1. Help and local fixture smoke tests

Start with help. Each command family has concrete examples and placeholder explanations.

```bash
python3 "$PI" -h
python3 "$PI" inventory -h
python3 "$PI" extract -h
python3 "$PI" summary -h
python3 "$PI" compare -h
```

Create a local, no-network fixture:

```bash
python3 - <<'PY'
from pathlib import Path
root = Path('/tmp/pi-validation')
root.mkdir(exist_ok=True)
(root / 'run.zml').write_text(
    '{"topic":"/nav","timestamp":1,"fields":{"pose":{"x":1},"phase":"ARMED"}}\n'
    '{"topic":"/nav","timestamp":2,"fields":{"pose":{"x":4},"phase":"BOUND"}}\n',
    encoding='utf-8',
)
(root / 'pass.zml').write_text(
    '{"topic":"/nav","timestamp":1,"fields":{"pose":{"x":1}}}\n'
    '{"topic":"/nav","timestamp":2,"fields":{"pose":{"x":2}}}\n',
    encoding='utf-8',
)
(root / 'phoenix.log').write_text('boot\nError Code 17 in phoenix\nhealthy\n', encoding='utf-8')
(root / 'validator_summary.txt').write_text('FAIL_VALIDATORS Error Code 22\n', encoding='utf-8')
(root / 'process_status.log').write_text('WATCHDOG service restart requested\n', encoding='utf-8')
(root / 'test_record.json').write_text('{"test_info":{"name":"fixture","result":"failed"}}\n', encoding='utf-8')
PY
```

Then run smoke commands:

```bash
python3 "$PI" inventory /tmp/pi-validation --out-dir /tmp/pi-validation/reports
python3 "$PI" search-logs /tmp/pi-validation --query 'Error Code|FAIL' --context 1
python3 "$PI" validators /tmp/pi-validation
python3 "$PI" journal /tmp/pi-validation
python3 "$PI" topics /tmp/pi-validation/run.zml --backend local-text --pattern nav
python3 "$PI" fields /tmp/pi-validation/run.zml --backend local-text --fuzzy phase --sample-top 1
python3 "$PI" extract /tmp/pi-validation/run.zml --backend local-text --topic /nav --all-fields --csv /tmp/pi-validation/nav-all.csv
python3 "$PI" summary /tmp/pi-validation/nav-all.csv --metric transitions --metric minmax --metric delta
python3 "$PI" compare --fail /tmp/pi-validation/run.zml --pass /tmp/pi-validation/pass.zml --backend local-text --topic /nav --field pose.x --csv /tmp/pi-validation/compare.csv
```

### 2. Local ZML and log workflows

Use local commands before remote lookup when you already have a bounded artifact bundle.

```bash
python3 "$PI" inventory /path/to/hil-run --format both --out-dir /tmp/pi/hil-run
python3 "$PI" search-logs /path/to/hil-run --query 'Traceback|Exception|Error Code' --context 2 --max-matches 100
python3 "$PI" validators /path/to/hil-run --query 'FAIL_VALIDATORS|Error Code'
python3 "$PI" journal /path/to/hil-run --query 'watchdog|service|restart|alarm'
```

For ZML, prefer field-first discovery when you know a signal but not a topic:

```bash
python3 "$PI" topics /path/to/run.zml.zst --fuzzy controller --limit 20 --systems-root /Systems --format both --out-dir /tmp/pi/controller-topics
python3 "$PI" fields /path/to/run.zml.zst --fuzzy flight_phase_for_controller --topic-fuzzy cloud_bound --systems-root /Systems --format both --out-dir /tmp/pi/flight-phase-fields
python3 "$PI" extract /path/to/run.zml.zst --topic /nav --field pose.x --csv /tmp/pi/nav-extract/nav.csv --systems-root /Systems --format both --out-dir /tmp/pi/nav-extract
python3 "$PI" extract /path/to/run.zml.zst --topic /nav --all-fields --csv /tmp/pi/nav-extract/nav-all.csv --systems-root /Systems --format both --out-dir /tmp/pi/nav-extract
python3 "$PI" summary /tmp/pi/nav-extract/nav-all.csv --metric transitions --metric minmax --metric delta --field pose.x
```

### 3. Compare and summary workflows

Use `compare` when you have explicit failing and passing local ZMLs. State what the signal delta supports and what it does not prove.

```bash
python3 "$PI" compare --fail /tmp/pi-validation/run.zml --pass /tmp/pi-validation/pass.zml --backend local-text --topic /nav --field pose.x --csv /tmp/pi/fixture-compare/compare.csv --format both --out-dir /tmp/pi/fixture-compare
python3 "$PI" compare --fail /path/fail.zml.zst --pass /path/pass.zml.zst --topic /nav --field pose.x --format both --out-dir /tmp/pi/nav-compare --systems-root /Systems
python3 "$PI" compare --fail /path/fail.zml.zst --pass /path/pass.zml.zst --preset gnss-timing --format both --out-dir /tmp/pi/preset-compare --systems-root /Systems
```

`summary` expects CSVs written by `extract --csv` with `path,topic,timestamp,field,value`. Simple CSVs with `timestamp`, `field`, and `value` can work best-effort.

### 4. Remote HIL/GHA/S3 discovery

Remote commands are read-only discovery only. They may require already-working `gh`/AWS credentials; do not start auth flows from this tool.

```bash
python3 "$PI" inventory 'https://github.com/ZiplineTeam/FlightSystems/actions/runs/123456789' --format both --out-dir /tmp/pi/gha-run-123456789
python3 "$PI" inventory 'https://github.com/ZiplineTeam/FlightSystems/actions/runs/123456789/job/987654321' --format both --out-dir /tmp/pi/gha-job-987654321
python3 "$PI" inventory 's3://zipline-artifacts/hil/runs/123456789/' --format both --out-dir /tmp/pi/s3-hil-run-123456789
python3 "$PI" recent-hil --preset zip_autokiosk --passing --limit 1000 --max-matches 3 --format both --out-dir /tmp/pi/recent-autokiosk-passing
```

If remote inventory identifies useful artifacts, download/fetch only through an approved bounded workflow outside Phoenix Inspector, then re-run local commands on the selected bundle or files.

## Supported `source` forms

- GitHub Actions run or job URL.
- `s3://bucket/prefix/...` source, never a bucket root.
- Local Phoenix/HIL/SIL log directory or extracted bundle.
- Local `.zml` or `.zml.zst` file.

Standalone packet/test_record JSON files and archives are intentionally unsupported as inventory sources. If you have an archive, extract it first and pass the resulting bundle directory. A bare flight/mission ID is also unsupported in v1; ask for a local bundle, GHA URL, or explicit S3 prefix.

## Expected blockers and safety cases

These are expected safety/blocker outcomes, not necessarily bugs:

```bash
python3 "$PI" inventory 's3://bucket'
python3 "$PI" inventory /
python3 "$PI" search-logs 's3://bucket/prefix/' --query FAIL
python3 "$PI" extract /tmp/pi-validation/run.zml --topic /missing --field pose.x --backend local-text
```

Blocker rules:

- Read-only only: no launch, upload, workflow dispatch, mutation, auth refresh, browser login, or destructive cleanup.
- `search-logs`, `validators`, and `journal` do not download. For GHA/S3 sources, provide selected local logs or a bounded extracted bundle.
- Do not broad-scan `/`, `/Systems`, home directories, or S3 bucket roots. Inspect explicit supported sources and selected artifact paths only.
- Missing auth should be reported as the exact blocked command/action and the needed user refresh; continue local validation when possible.

## Output and backend policy

- Default output is Markdown on stdout for human/manual use.
- `--out-dir` additionally saves report files and keeps stdout as the rendered report: Markdown for `--format markdown`, JSON for `--format json`, and Markdown for `--format both`.
- For agent investigations, prefer `--format both --out-dir /tmp/pi/<short-task>` on supported report commands so Markdown and JSON artifacts are both available.
- Use `--csv /tmp/pi/<short-task>/<name>.csv` for extract/compare sample rows; `extract` may also use `--format both --out-dir /tmp/pi/<short-task>` when a report artifact is useful.
- Default `--backend auto` tries `zml-conv` before `zml-cli`.
- Prefer `zml-conv` for Phoenix-aware decoded reads/extraction when `/Systems` is available; `--systems-root` defaults to `/Systems` when present.
- Use `zml-cli` for topic listing, metadata, raw/schema-aware fallback, and portable local inspection.
- Use `local-text` only for fixtures, JSONL, and simple local tests; do not present it as production ZML decoding.

## Intent → command

| If you know... | Run... | Then... |
|---|---|---|
| Only a source URL/path | `inventory <source> --format both --out-dir /tmp/pi/<short-task>` | Use reported artifacts and `next_commands`. |
| Field/signal name, not topic | `fields <source> --fuzzy FIELD --format both --out-dir /tmp/pi/<short-task>` or `find-field <source> --fuzzy FIELD --format both --out-dir /tmp/pi/<short-task>` | Run `extract` with the returned `zml_path`/`topic`/`field_path`. |
| Topic and field | `extract <source.zml.zst> --topic TOPIC --field FIELD --csv /tmp/pi/<short-task>/out.csv` | Use the CSV for sample rows; add `--format both --out-dir /tmp/pi/<short-task>` when a report artifact is useful. |
| Topic, all fields | `extract <source.zml.zst> --topic TOPIC --all-fields --csv /tmp/pi/<short-task>/topic.csv` | Use `summary /tmp/pi/<short-task>/topic.csv --metric transitions --metric minmax --metric delta`. |
| Text log pattern | `search-logs <local-log-dir> --query REGEX --context 2` | Use `validators` or `journal` for common presets; add `--out-dir` when saving a text-search report. |
| Failing and passing ZMLs | `compare --fail fail.zml.zst --pass pass.zml.zst --topic TOPIC --field FIELD --format both --out-dir /tmp/pi/<short-task>` | Record supports / does-not-prove boundaries. |
| Preset pass/fail bundle | `compare --fail fail.zml.zst --pass pass.zml.zst --preset PRESET --format both --out-dir /tmp/pi/<short-task>` | Treat preset selections as non-diagnostic bundles. |
| Recent HIL source needed | `recent-hil` or `inventory <GHA_URL>` with `--format both --out-dir /tmp/pi/<short-task>` | Treat remote reads as bounded discovery, not diagnosis. |
