---
name: phoenix-hil-gha
description: Handle Phoenix HIL/GHA workflows: source recent HIL jobs, summarize exact GitHub Actions runs/jobs, generate evidence packets, check preset sync against /Systems, inspect artifacts, and debug failures when requested with handoff to ZML signal audit for deeper signal analysis.
---

# Phoenix HIL/GHA Workflows

## Goal

Given a GitHub Actions HIL run/job URL, S3/local artifact source, or bounded English run description, produce a first-pass HIL evidence packet and, when debugging is requested, identify the likely primary failure cause with artifact and code evidence. The helper supports the broader P2/System HIL test kinds represented in `/Systems`, not only historical Phoenix autokiosk and real-dock delivery presets.

Use symptom summaries to choose where to look, not as the causal answer. Do not claim root cause without pass/fail contrast or equivalent differential evidence; if only the failing run is available, label the conclusion as likely/inferred and name the missing comparison.

## Safety and non-goals

- Do not launch HIL/SIL, upload logs, mutate PRs/Jira, refresh credentials, start interactive auth, or perform other write/mutation workflows.
- Do not make broad root-cause claims from summaries alone. RCA needs artifact evidence plus code/source references; without contrast, mark conclusions as likely/inferred.
- Keep artifact downloads bounded to the selected run/job evidence and a local scratch directory. Do not fall back to run-wide or unrelated artifacts when job scoping is ambiguous.
- Report auth, rate-limit, missing-tool, and permission blockers exactly; ask for the next user decision instead of repairing credentials or waiting on prompts.

## Usual use cases and routing

| User intent | Route | Command/source shape | Response shape |
| --- | --- | --- | --- |
| Exact GHA run/job evidence packet | Summarize the exact job URL and lock analysis to that job attempt. | `hil_evidence_cli.py summarize "$JOB_URL" --format both --out-dir ...` | Evidence-only `Packet summary`, `Key evidence`, `Next steps`. |
| Recent HIL run sourcing by preset | Run `sync-check` when `/Systems` is relevant, then use a canonical preset. | `sync-check --systems-root /Systems`; `recent --preset zip_delivery...` | Candidate packet/list; ask the user to pick one exact job if ambiguous. |
| Recent HIL sourcing by generic filters | For non-preset or new tests, compose explicit filters instead of forcing a preset. | `recent --job-name ... --title ... --branch ... --conclusion ... --test-record-query ...` | Candidate packet/list with filter caveats and exact next disambiguation. |
| Preset freshness/sync-check against `/Systems` | Compare helper presets to local `/Systems` defaults before relying on preset names. | `hil_evidence_cli.py sync-check --systems-root /Systems --format text` | Status/blockers; prefer generic filters if sync is stale. |
| Local S3/`test_record`/log summarization | Summarize an already-known S3 root or downloaded local artifact without GitHub preflight. | `summarize s3://...`, `summarize /path/to/test_record.json`, or local log source | Evidence-only packet; include AWS/local blockers if inventory is partial. |
| First-pass triage of a failed HIL job | Generate and read the packet before deeper inspection. | `summarize "$JOB_URL" --format both`; inspect log summary, S3 roots, mission context, `test_record`, blockers | Evidence-only packet plus concrete next checks unless user asks for RCA. |
| Batch failure taxonomy across recent HIL jobs | Source N recent jobs, generate packets, then aggregate only packet-supported status/reason/link fields. | `recent --preset ... --status completed --conclusion failure --max-matches N --format both`; JSON-to-CSV/Markdown rollup | Taxonomy table with `job_url`, status, confirmation, failure summary, key artifact links; mark unknowns and avoid RCA claims. |
| Pass/fail GHA regression comparison | Summarize exact failing and passing job/run packets before source inspection. | `summarize "$FAIL_JOB" --format both`; `summarize "$PASS_JOB" --format both` | Compare `test_record.json`, log summaries, mission context, and `Key S3 artifacts`; inspect code/config only for supported differences. |
| Deeper failure RCA with code references | Start from packet evidence, then inspect only needed logs/ZML and source files. | Bounded download from packet S3 root; `rg` failing validator/alarm in logs and source | RCA `TL;DR`, `Detailed analysis`, `Potential fixes`, `Artifacts and steps used`. |
| Bounded artifact download for selected job evidence | Download only selected job evidence needed for a claim. | Use packet `Key S3 artifacts`/S3 root; `aws s3 cp/sync` into `/tmp/hil_<run>_<job>` | State artifact path, scope limit, and what it proves/does not prove. |
| ZML signal audit/pass-fail handoff | When validator/log evidence points to signal behavior, stop ad-hoc spelunking and hand off. | Pass selected job URL, packet path, key S3 rows, validator/alarm names, and question | Handoff packet; no unsupported signal RCA claim. |
| PR/Jira/verification evidence packet | Collect links/status/evidence for review or ticket context only. | `summarize`/`recent` packets plus relevant PR/Jira links provided by user | Evidence-only packet; do not edit PR/Jira unless a separate request/skill handles it. |
| Status/rate-limit/auth blocker reporting | Surface blocker from preflight or packet and stop safely. | `gh auth status`, packet `blockers`, command stderr/status | Exact blocker, affected workflow, and user action/decision needed. |

## Input and scope

- Preferred input for exact handling: `https://github.com/ZiplineTeam/FlightSystems/actions/runs/<run_id>/job/<job_id>`.
- Run URLs, S3 roots, local `test_record.json`, and local logs are valid for summarization when the user asks for evidence collection rather than root-cause debugging.
- English descriptions are allowed only long enough to resolve exact candidate job(s). If multiple candidates match, stop and ask the user to pick one exact `job_url`/`gha_url` before root-cause analysis.

## Canonical helper

Use `opencode/.config/opencode/scripts/hil_evidence_cli.py` for discovery and first-pass evidence. It is read-only and produces structured evidence packets in JSON and/or Markdown.

- `summarize` accepts one run/job/S3/local source and returns GitHub metadata, bounded log summary, S3/Baraza/mission context, key artifact paths, `test_record.json` summaries, blockers, and next-step hints.
- `recent` searches recent P2 HIL jobs. Use canonical `/Systems` preset names such as `zip_delivery`, `zip_delivery_ev3`, `zip_autokiosk`, `zip_delivery_real_dock`, `mission_suite`, `dock_hil_full_suite`, or `return_to_service`; compatibility aliases `autokiosk` and `real-dock-delivery` still work. Presets apply known HIL filters and confirm returned jobs with `test_record.json` evidence when AWS access is available.
- `zip_autokiosk`/`autokiosk` default to broader recent sourcing (`--limit 1000`, `--lookback-hours 3000`) because passing examples can be sparse; explicit flags still override. Mission-suite/member presets can source suite-titled runs, so rely on `test_record.json` confirmation before treating a candidate as the requested test.
- For non-preset or newly added HIL sourcing, compose generic filters: `--job-name`, `--title`, `--branch`, `--status`, `--conclusion`, and `--test-record-query`. An explicit `--test-record-query` overrides the preset query for confirmation.
- `sync-check` is a read-only local preflight that compares helper presets with statically parsed `/Systems` HIL defaults. It defaults to `/Systems`, accepts `--systems-root`, supports `--format text|markdown|json`, reports comparison source paths, presence-only optional source paths, blockers, missing/extra/mismatched presets, and exits nonzero on real sync failures.
- Packet statuses:
  - `ok`: first-pass evidence collection completed.
  - `partial`: useful evidence was collected, but structured blockers remain.
  - `error`: a required local/GitHub/AWS step failed before reliable evidence was available.
  - `no_matches`: broaden filters or ask for a more specific run/job.
  - `no_hil_jobs`: older packet wording for a run with no non-skipped real HIL jobs; treat like `no_matches`.

## Workflow

0. Target-aware preflight without triggering auth flows or write workflows.

```bash
command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }
```

When `/Systems` is available locally and the task depends on preset-based recent-run discovery, run the local preset freshness check before relying on preset names:

```bash
python3 "$HOME/.config/opencode/scripts/hil_evidence_cli.py" sync-check --systems-root /Systems --format text
```

If it reports missing presets, mismatches, or required blockers, mention that caveat and prefer explicit generic filters until the helper is updated.

For GitHub job/run sources and `recent` discovery, also check `gh` without trying to repair auth:

```bash
command -v gh >/dev/null || { echo "gh CLI not found"; exit 1; }

if ! gh auth status >/dev/null 2>&1; then
  echo "AUTH ERROR: gh is not authenticated. Ask user to run: gh auth login"
  exit 1
fi
```

If `gh` reports an API/rate-limit/abuse-limit or auth blocker, do not retry in a loop or silently broaden/narrow queries. Report the exact command, exit status, stderr/stdout excerpt, and current auth state (`gh auth status` output when available), then ask whether to resume later or narrow the query (`--limit`, `--lookback-hours`, filters, or `--max-matches`).

For local `test_record.json` or local log summarization, do not run the `gh` check. Do not hard-fail preflight on missing AWS. Let `hil_evidence_cli.py` emit structured AWS blockers for S3 inventory and `test_record.json` reads. Check `zml` only before deep ZML inspection.

1. Generate evidence packet(s) under a stable validation directory.

```bash
# Exact job URL: write both JSON and Markdown.
OUT_DIR="/tmp/hil_evidence_${RUN_ID}_${JOB_ID}"
python3 "$HOME/.config/opencode/scripts/hil_evidence_cli.py" summarize "$JOB_URL" --format both --out-dir "$OUT_DIR"

# Exact run URL: summarize matching HIL jobs, then ask user to pick one if multiple jobs remain.
python3 "$HOME/.config/opencode/scripts/hil_evidence_cli.py" summarize "$RUN_URL" --preset zip_delivery --max-jobs 5 --format both --out-dir /tmp/hil_evidence_run

# English description: find recent confirmed candidates, then ask the user to choose if ambiguous.
python3 "$HOME/.config/opencode/scripts/hil_evidence_cli.py" recent --preset zip_autokiosk --passing --max-matches 3 --format both --out-dir /tmp/hil_evidence_recent_autokiosk
python3 "$HOME/.config/opencode/scripts/hil_evidence_cli.py" recent --preset zip_delivery_real_dock --max-matches 5 --format both --out-dir /tmp/hil_evidence_recent_real_dock
python3 "$HOME/.config/opencode/scripts/hil_evidence_cli.py" recent --job-name "HIL Test: zip_delivery" --branch develop --conclusion failure --test-record-query phoenix_delivery --max-matches 3 --format both --out-dir /tmp/hil_evidence_recent_delivery

# Local artifact/fixture pass when logs or test_record.json are already downloaded.
python3 "$HOME/.config/opencode/scripts/hil_evidence_cli.py" summarize /path/to/test_record.json --preset autokiosk --format markdown
```

For batch failure taxonomy, keep the workflow evidence-only: source N recent jobs with `recent`, read the JSON packet(s), and aggregate columns such as `job_url`, `job_status`/`job_conclusion`, `test_record_confirmation`, `test_records[].result`, `log_summary.failed_scenarios_or_tests`, `log_summary.validator_failures`, `log_summary.alarm_error_lines`, and `Key S3 artifacts` URIs into CSV or Markdown. Use `unknown` when the packet lacks evidence; do not convert repeated symptoms into root cause without deeper artifact/code proof.

For pass/fail regression comparison, create separate failing and passing packets first. Compare `test_record.json` names/results/parameters, high-signal log summary lines, mission/Baraza context, and `Key S3 artifacts` before opening source. Inspect code/config only for differences supported by packet evidence, and label unsupported hypotheses as unknown.

2. Read the packet before deeper inspection.

- Prefer the generated Markdown for human triage and JSON for exact fields.
- Use sections in this order: `jobs[].log_summary`, `jobs[].s3.roots`, `jobs[].s3.inventories[].key_artifact_hints`, mission/Baraza context, `jobs[].test_records`, `blockers`, `next_steps`.
- In Markdown, prioritize `Key S3 artifacts` and `Mission context` tables before deeper downloads. They should contain bounded concrete S3 URIs, sizes when known, direct Baraza links when observed, and ID-only rows when links were not directly observed.
- Treat `blockers` as authoritative structured stop signs for missing CLIs/auth, failed `gh`/`aws` commands, inaccessible S3 roots, invalid JSON, or ambiguous/missing `test_record.json` evidence.
- If `recent` returns more than one plausible job, ask the user to choose one exact `job_url`/`gha_url`, then rerun `summarize` on that URL.

3. Debug only when requested; otherwise stop at first-pass evidence.

For failure analysis, start from packet evidence, then inspect only the missing bounded artifacts needed for a specific claim. Use the S3 root from the packet, not a run-level fallback. Keep downloads local and bounded to the selected job evidence; do not upload, launch, or mutate anything.

Common high-signal artifacts:

- `test_record.json`: authoritative result, parameters, measurements, and manifest.
- `test_log_*.log`: HTF/pytest harness logs; inspect first for broad `SIMULATION_FAILED`, `FAIL_TEST`, or teardown failures.
- `phoenix_logs/phoenix.log`: Phoenix orchestration/sim log.
- `journal` / `journalctl` artifacts: system journal context when exported.
- validator/validation artifacts: validator output or summaries.
- `*.zml` / `*.zml.zst`: compute, droid, dock, and world logs used by validators.
- Journal content often appears as `journalctl_log` topics inside ZML streams rather than standalone text files.

If a failure points to ZML signal behavior, hand off to the ZML signal audit workflow instead of doing broad ad-hoc signal spelunking. Pass the selected job URL, packet JSON/Markdown path, relevant `Key S3 artifacts` rows, validator/alarm names, and the specific question to answer.

```bash
command -v aws >/dev/null || { echo "aws CLI not found; use packet blockers or install aws before artifact download"; exit 1; }
OUT_DIR="/tmp/hil_${RUN_ID}_${JOB_ID}"
mkdir -p "$OUT_DIR"

# Prefer exact artifacts listed in packet Markdown under "Key S3 artifacts".
aws s3 cp "s3://bucket/path/from/key-s3-artifacts/test_record.json" "$OUT_DIR/test_record.json"
aws s3 cp "s3://bucket/path/from/key-s3-artifacts/test_log_0.log" "$OUT_DIR/test_log_0.log"

# Only when broader context is needed, use an include/exclude-limited sync.
aws s3 sync "$S3_URI" "$OUT_DIR" --exclude "*" --include "*test_record.json" --include "*test_log*.log" --include "*phoenix.log"
find "$OUT_DIR" -maxdepth 3 -type f | sort
```

Avoid a broad root `aws s3 sync "$S3_URI" "$OUT_DIR"` by default; it is slower, can pull unrelated evidence, and weakens attempt scoping.

4. Inspect failure evidence, then code.

```bash
command -v rg >/dev/null || { echo "rg not found"; exit 1; }
rg -n "=== FAILURE REASONS ===|Error Code|FAIL_TEST|FAIL_VALIDATORS|unexpected-alarms|Traceback|Exception" "$OUT_DIR"
find "$OUT_DIR" -type f \( -name "*.zml" -o -name "*.zml.zst" \) | sort
command -v zml >/dev/null || { echo "zml CLI not found; skip ZML inspection or install zml"; exit 1; }
zml -z <log.zml.zst> list
zml -z <log.zml.zst> print '*<topic_or_alarm_hint>*'
zml -z <log.zml.zst> list | rg 'journalctl|process_status|alarm|fault|dock_status'
```

Map failing validator/alarm/error to code and re-check every major claim against source files before finalizing.

```bash
rg -n "<validator_name>" p2_validation hil ash sim
rg -n "<ALARM_OR_ERROR_NAME>" ash p2_zip p2_droid p2_dock gnc p2_validation
```

## Output contract

For evidence-only packet generation or recent-job sourcing, respond with:

1. `Packet summary`
   - Status, source/job(s), packet path(s) or command output, and notable blockers.
2. `Key evidence`
   - Compact bullets or tables for key S3 artifacts, Mission context, `test_record.json`, and high-signal log summary lines.
3. `Next steps`
   - Only concrete follow-ups needed to resolve blockers, disambiguate candidates, or start deeper debugging.

For PR/Jira/verification contexts, include provided links/status/evidence in the packet summary, but do not edit external systems. For auth, rate-limit, status, or permission blockers, return the exact blocker, affected route, and requested user action.

For requested failure debugging/root-cause analysis, respond with:

1. `TL;DR`
   - 2-4 bullets: primary issue, failing validator/alarm/error, confidence.
2. `Detailed analysis`
   - Failure timeline, key log findings, validator/alarm mapping, code trace with file references.
3. `Potential fixes`
   - Immediate mitigation, durable fix, and verification ideas.
4. `Artifacts and steps used`
   - Compact table listing artifact/command, `this proves/supports`, and `does not prove`.

Keep both response shapes concise. Prefer short evidence-backed statements over broad speculation.

## Evidence rules

- Do not claim root cause without at least one artifact signal and one code reference.
- Label decisive evidence as `this proves/supports ...` and important limits as `this does not prove ...`.
- If data is insufficient, state `unknown` and list missing artifacts needed.
- For multiple simultaneous failures, identify one primary blocker and clearly mark secondary effects.
- In safety-critical contexts, never suggest bypassing alarms/validators without explicit user request.
- Do not treat prior `LLM Bot Summary` text in job logs as primary evidence.

## Helpful local references

- `notes/autokiosk_no_sync_investigation.md`
- `hil/htf/src/zipline/htf/hil/failure_analyzer.py`
- `hil/htf/src/zipline/htf/core/executor.py`
- `hil/htf/src/zipline/htf/core/context.py`
- `hil/htf/src/zipline/htf/pytest_plugins/htf_export.py`
- `ash/phoenix/orchestration/src/logging.rs`
- `tools/zml/README.md`
- `hil/utils/remote_machine.py`
