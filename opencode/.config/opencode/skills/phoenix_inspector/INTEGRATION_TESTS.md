# Phoenix Inspector Prompt Integration Tests

These prompt-style checks validate that agents route common read-only Phoenix questions through `phoenix_inspector.py` and produce bounded evidence artifacts. They must not launch HIL/SIL/sim work, upload artifacts, mutate PR/GHA/Jira state, refresh auth, broad-scan roots, or broad-sync/download S3 content.

Use a task-specific workspace under `/tmp`, for example:

```bash
WORKSPACE=/tmp/phoenix-inspector-prompt-integration-2026-05-10
mkdir -p "$WORKSPACE"
```

## Test matrix

| Prompt text | Expected skill/tool route | Canonical command(s) | Pass criteria | Blockers policy |
|---|---|---|---|---|
| “Find recent 3 passing autokiosk HIL runs.” | Load `phoenix_inspector`; use `recent-hil` with current autokiosk preset defaults. | `python3 opencode/.config/opencode/scripts/phoenix_inspector.py recent-hil --preset zip_autokiosk --passing --max-matches 3 --format both --out-dir "$WORKSPACE/recent-autokiosk-passing-3"` | Command exits 0; report includes up to 3 passing matches with run/job IDs or names, counts, blockers, and JSON/Markdown artifacts. | If GHA/AWS metadata access or existing auth blocks the read-only lookup, report the exact command, stderr/blocker, and user action needed. Do not run auth refresh or alternate broad downloads. |
| “Inspect the latest Phoenix logs' `flight_phase_for_controller`.” | Load `phoenix_inspector`; use field-first discovery, then direct extraction for the best match. | `python3 opencode/.config/opencode/scripts/phoenix_inspector.py find-field /Systems/.phoenix/logs/latest --fuzzy flight_phase_for_controller --format both --out-dir "$WORKSPACE/flight-phase-fields"`<br><br>Then select the best returned `zml_path`, `topic`, and `field_path` and run:<br>`python3 opencode/.config/opencode/scripts/phoenix_inspector.py extract <zml_path> --topic <topic> --field <field_path> --csv "$WORKSPACE/flight-phase-extract/flight_phase_for_controller.csv"` | Discovery and extraction exit 0; report selected ZML/topic/field, CSV path, sample count, transitions, and first/last values. | If `/Systems/.phoenix/logs/latest` is unavailable or no matching field is found, report the local blocker and do not search unrelated roots. If extraction fails due a tool/backend bug, report exact stderr and artifacts produced. |
| “Investigate the GNSS-related signals in the latest Phoenix log.” | Load `phoenix_inspector`; use bounded inventory/topic/field discovery over `/Systems/.phoenix/logs/latest`, then extract a representative GNSS signal when discoverable. | Start with one bounded discovery command:<br>`python3 opencode/.config/opencode/scripts/phoenix_inspector.py find-field /Systems/.phoenix/logs/latest --fuzzy gnss --limit 20 --format json --out-dir "$WORKSPACE/gnss-fields"`<br><br>If needed, narrow by topic instead:<br>`python3 opencode/.config/opencode/scripts/phoenix_inspector.py topics /Systems/.phoenix/logs/latest --fuzzy gnss --limit 20 --format json --out-dir "$WORKSPACE/gnss-topics"`<br><br>When a representative topic/field is identified:<br>`python3 opencode/.config/opencode/scripts/phoenix_inspector.py extract <zml_path> --topic <topic> --field <field_path> --csv "$WORKSPACE/gnss-extract/<signal>.csv"` | Report relevant ZML files/topics, at least one extracted GNSS signal with CSV/report path, or a clear blocker if no GNSS topic/field is discoverable. | If `/Systems/.phoenix/logs/latest` is unavailable, report the local blocker. Keep discovery bounded by explicit path and limits; do not broad-scan `/Systems` or fetch remote data. |

## Output artifact convention

- Put each prompt under `$WORKSPACE/<short-test-name>/`.
- Use `--format both --out-dir <dir>` for field/topic discovery and other supported reports so JSON and Markdown artifacts are both available.
- Put direct extraction CSVs under `$WORKSPACE/<short-test-name>-extract/<signal>.csv`.
- Final summaries should include exact commands, exit statuses, report/CSV paths, counts, selected topic/field names, and first-class blockers.

## Safety notes

- Read-only GHA/AWS metadata checks are allowed only through the canonical tool and only with already-working credentials.
- Do not run `gh auth login`, `aws sso login`, workflow dispatches, PR/Jira mutations, uploads, HIL/SIL/sim launches, broad S3 sync/downloads, or broad root scans.
- If a required action crosses a runtime permission boundary, stop and report the exact action/path/command, why it is needed, and the decision required.
