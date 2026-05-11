---
name: zml-signal-audit
description: "Legacy/expert escape hatch for the low-level zml_signal_audit.py helper. Prefer `phoenix_inspector` for normal ZML field discovery, topic lookup, extract, compare, preset, and spec workflows."
---

# ZML Signal Audit

> Legacy route: prefer `$phoenix_inspector` for normal local ZML/ZST/log field discovery, topic lookup, extraction, CSV output, pass/fail comparison, presets, and reusable specs. Use this skill only when debugging or operating the older `zml_signal_audit.py` helper directly.

## Goal and scope

Use this skill for read-only signal/log analysis of local `.zml`, `.zml.zst` files and bounded log roots across HIL, SIL, simulation, and real-flight contexts. It owns topic discovery/search, time-window audits, CSV extraction for plotting/manual follow-up, transition inspection, domain preset checks, pass/fail or before/after comparisons, and questions like "what topic/log did you read?"

Remote sources are upstream work: if the needed data is only a GHA job, S3 URI, Baraza/LogPlots link, or other remote artifact pointer, first use the appropriate artifact/source workflow to produce local paths, or return a structured blocker with the exact source needed.

## Use when

- The user asks which ZML topics exist or which topic/log/source supports a claim.
- The user asks to audit one or more topics over a time window, centered event, or transition.
- The user asks to extract CSV for plotting or manual follow-up.
- The user asks to compare failing vs passing, before vs after, sim vs HIL, or real-flight vs simulated ZML outputs.
- A Phoenix/HIL/GHA investigation points to signal behavior and hands off selected local ZML paths, validator/alarm names, packet paths, or key S3 rows.
- The user mentions prod-nav, GNSS timing, IMU bias, PIM/residuals, truth-vs-nav, dock/winch/latch, wind/airdata/qbar, or process/alarm/watchdog signals.

Prefer `phoenix_inspector` for GHA job sourcing, S3 artifact discovery, recent-run lookup, HIL preset sync-checks, first-pass evidence packets, and normal ZML/log inspection. Prefer `phoenix-workflows` for launching or rerunning Phoenix/SIL/HIL scenarios.

## Safety and boundaries

- Read local `.zml` / `.zml.zst` files or bounded local log roots only.
- Do not launch scenarios, upload logs, mutate PRs/Jira, refresh credentials, start auth flows, or discover/download GHA/S3/HIL artifacts.
- If the needed ZML file is only available remotely, return a blocker or hand back to `phoenix_inspector` with the exact artifact row/source needed.
- If a directory resolves to multiple candidates for pass/fail comparison, stop and ask for exact files or a narrower directory.
- HIL, SIL, simulation, and real-flight sources have different expected topics and clock/reference behavior. Do not claim a missing topic is a failure without first stating the source type and why that topic is expected there.
- Sim/HIL logs may include truth, injected-fault, or validator-only topics that real-flight logs do not; real-flight logs may have hardware timing, sensor availability, and privacy/export limits absent from sim.
- Follow the shared traceability defaults from `user-profile.yaml` for observable evidence, action, and command records.

## Canonical helper

Use the available helper script:

```bash
python3 "$HOME/.config/opencode/scripts/zml_signal_audit.py" --help
```

In this dotfiles repo, the source path is `opencode/.config/opencode/scripts/zml_signal_audit.py`; active runtime setups usually resolve it at `$HOME/.config/opencode/scripts/zml_signal_audit.py`. If the helper is missing, report that as a blocker instead of inventing ad-hoc parsing.

Common read-only commands:

```bash
# Topic inventory or name/source lookup; supports markdown or json.
python3 "$HOME/.config/opencode/scripts/zml_signal_audit.py" topics /path/to/logs --contains nav --systems-root /Systems --format markdown --out-dir /tmp/zml_topics_nav

# Topic-name lookup only. If the field/signal is known, prefer `fields --fuzzy` instead.
python3 "$HOME/.config/opencode/scripts/zml_signal_audit.py" topics /path/to/logs --fuzzy controller --limit 20 --format markdown

# Known field/signal, unknown topic: search fields across candidate ZMLs first; metadata/schema/index is preferred before bounded sampling and independent files are probed with bounded workers.
python3 "$HOME/.config/opencode/scripts/zml_signal_audit.py" fields /path/to/logs --fuzzy flight_phase_for_controller --sample-top 0 --max-zmls 200 --workers 4 --max-topics 500 --systems-root /Systems --format markdown

# If the exact local ZML/ZST file, topic, and field are known, audit directly; this skips topic/field discovery and topic listing for the exact file.
python3 "$HOME/.config/opencode/scripts/zml_signal_audit.py" audit /path/to/compute_a.zml.zst --topic /compute_a.nav.gnc_state --field pose.x --start 120 --end 180 --systems-root /Systems --format both --csv /tmp/zml_audit_topic.csv --out-dir /tmp/zml_audit_topic

# Summarize one explicit topic over an optional time window; CSV is for plotting/manual follow-up.
python3 "$HOME/.config/opencode/scripts/zml_signal_audit.py" audit /path/to/compute_a.zml.zst --topic /compute_a.nav.gnc_state --start 120 --end 180 --format both --csv /tmp/zml_audit_topic.csv --out-dir /tmp/zml_audit_topic

# Summarize a preset over an optional time window.
python3 "$HOME/.config/opencode/scripts/zml_signal_audit.py" audit /path/to/compute_a.zml.zst --preset prod-nav-truth-vs-nav --start 120 --end 180 --format both --csv /tmp/zml_audit_prod_nav.csv --out-dir /tmp/zml_audit_prod_nav

# Compare one failing and one passing ZML/ZST candidate.
python3 "$HOME/.config/opencode/scripts/zml_signal_audit.py" compare --fail /path/to/fail.zml.zst --pass /path/to/pass.zml.zst --preset gnss-timing-residuals --format both --csv /tmp/zml_compare_gnss.csv --out-dir /tmp/zml_compare_gnss

# Preset/transition-focused inspection around an event.
python3 "$HOME/.config/opencode/scripts/zml_signal_audit.py" audit /path/to/logs --preset dock-winch-latch --center 2026-05-10T12:34:56Z --duration 30 --transition-limit 10 --format both --out-dir /tmp/zml_dock_event
```

Canonical presets: `prod-nav-truth-vs-nav`, `gnss-timing-residuals`, `imu-bias-pim-nav-filter`, `dock-winch-latch`, `wind-airdata-qbar`, and `process-alarm-watchdog-status`. Supported aliases include `prod-nav`, `truth-vs-nav`, `gnss-timing`, `imu-bias`, and `pim-residuals`.

Backend selection defaults to `--backend auto`, which prefers `zml-conv` for decoded topic reads/extraction, uses `zml-cli` for topic listing and metadata, and can fall back to schema-aware `zml print_raw` for direct known topic/field extraction when decoded reads fail. Raw fallback is reported as `zml-print-raw` with decoded failure metadata. Phoenix-aware commands default `--systems-root` to `/Systems` when present because Bazel `zml-conv` fallback and schema/registry behavior still need that checkout; direct-vs-Bazel invocation, `systems_root`, `cwd`, and fallbacks are reported in backend metadata. Standalone ZMLs can still use `zml-cli` or `local-text` without `/Systems`. Use `--backend zml-cli` or `--backend zml-conv` to force one and get a structured blocker instead of fallback when unavailable. Use `--backend local-text` only for JSONL/text fixtures, not binary ZML/ZST evidence. `topics`/`list-topics` need topic-listing support, so auto uses a listing-capable backend. `--timeout` controls per-backend command timeout.

Explicit `--field` paths support dotted names plus bounded expansion for list indexes/wildcards and dict wildcards, e.g. `items[0].x`, `items[*].x`, `foo.*.value`, and `*.timestamp`. Expanded concrete field names appear in stats and CSV sample rows; expansion is capped at 1000 fields per sample, truncation is reported in metadata/CSV markers, and long-form CSV sample rows are bounded by `--csv-sample-limit`.

Use the generated CSV for local plotting, spreadsheet inspection, or a manual plotting follow-up. Do not claim the helper creates plots unless another user-approved plotting step actually does so.

## Workflow

1. Restate the active question and create a `Topic Ledger` seed: source path(s), topic/preset, fields if relevant, time window, fail/pass side, status, and next decisive probe.
2. Confirm the source is local and bounded. If the source is a GHA/S3/HIL artifact pointer rather than a local file/root, stop with the exact blocker or route back to `phoenix_inspector`.
3. Run the smallest read-only command that answers the question:
   - `audit` directly when the exact local file/topic/field is known; this is the direct extraction path and avoids topic/field discovery.
   - `fields --fuzzy FIELD` when the field/path name is known but the topic is not; then pass the ranked `zml_path`, `topic`, and `field_path` to direct `audit`/extract.
   - `topics` for topic inventory or topic-name lookup only; use it when both field and exact topic are unknown.
   - `audit` for summarized extraction from one local source using selected `--topic` or `--preset` inputs and a time window.
   - `compare` for pass/fail checks between one failing and one passing local ZML/ZST candidate.
4. Read the generated Markdown for human evidence and JSON/CSV when exact fields, samples, transitions, or plotting inputs are needed. Record which sections/fields were read and why.
5. For RCA-style conclusions, require differential evidence where possible. If only one side exists, label conclusions as likely/inferred and name the missing comparison.
6. Stop once the ledger's active question is answered or the next decisive probe needs new artifacts, credentials, a narrower source, or user selection.

## Output contract

Return the relevant subset, kept concise:

1. `Result`
   - Direct answer, status, confidence, explicit limits, and whether the conclusion is observed, inferred, or unknown.
2. `Topic Ledger`
   - Table with `question`, `source/log`, `topic_or_preset`, `window`, `side`, `status`, and `next_probe`.
3. `Evidence Trace`
   - Table with `claim`, `artifact_or_command`, `this proves/supports`, and `does not prove`.
4. `Artifacts read`
   - Path/URI or packet/report/CSV path, sections/fields read, why, and result/blocker.
5. `Commands used`
   - Exact command, cwd, output path(s), exit status, and material stdout/stderr excerpts for blockers.
6. `Next step or blocker`
   - Only include if more evidence, a narrower source, upstream artifact sourcing, or a user decision is needed.

## Non-goals

- GHA/S3 discovery, artifact download/upload, or remote log sourcing.
- Running SIL/HIL/scenario workflows or triggering GitHub Actions.
- PR/Jira mutation.
- Broad RCA without local artifact evidence plus code/source references when code causality is claimed.

Preserve material command records and evidence limits for any handoff back to `debugger`, `phoenix_inspector`, or `phoenix-workflows`.
