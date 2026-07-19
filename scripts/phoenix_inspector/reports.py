from __future__ import annotations

import json
import re
from pathlib import Path

from .models import EvidenceReport, JsonDict


MAX_INVENTORY_GROUP_ITEMS = 20
INVENTORY_GROUP_ORDER = (
  "zml_zst",
  "zml",
  "phoenix_log",
  "validator_output",
  "journal",
  "test_log",
  "test_record",
  "alarm_output",
  "archive",
)

MAX_REMOTE_JOBS = 5
MAX_REMOTE_LIST_ITEMS = 10
MAX_REMOTE_TABLE_ROWS = 20
REMOTE_LOG_SUMMARY_KEYS = (
  ("validator_failures", "Validator failures"),
  ("alarm_error_lines", "Alarm/error lines"),
  ("artifact_hint_lines", "Artifact hints"),
  ("failed_scenarios_or_tests", "Failed scenarios/tests"),
)


def render_json(report: EvidenceReport | JsonDict) -> str:
  data = report.to_dict() if isinstance(report, EvidenceReport) else report
  return json.dumps(data, indent=2, sort_keys=True) + "\n"


def render_markdown(report: EvidenceReport | JsonDict) -> str:
  data = report.to_dict() if isinstance(report, EvidenceReport) else report
  lines = [f"# {data.get('title', 'Phoenix Inspector Report')}", ""]
  lines.extend(["## Summary", "", data.get("summary") or f"Status: `{data.get('status')}`; confidence: `{data.get('confidence', 'low')}`.", ""])
  hil_report = is_hil_legacy_report(data)
  lines.extend(section_source_inventory(data))
  if hil_report:
    lines.extend(section_hil_gha_inventory(data))
  else:
    lines.extend(section_evidence(data))
  lines.extend(section_text_search(data))
  lines.extend(section_summary_metrics(data))
  if not is_plain_inventory_report(data) and not hil_report:
    lines.extend(section_findings(data))
    lines.extend(section_timebase(data))
  lines.extend(section_proves(data))
  lines.extend(section_blockers(data))
  lines.extend(section_outputs(data))
  lines.extend(section_next(data))
  return "\n".join(lines).rstrip() + "\n"


def section_source_inventory(data: JsonDict) -> list[str]:
  lines = ["## Source and Inventory", ""]
  for source in data.get("sources") or []:
    run_source = source.get("run_source") or {}
    lines.append(f"- `{run_source.get('raw', source.get('root'))}` → `{source.get('resolved_type')}`")
    if source.get("metadata"):
      lines.append(f"  - metadata: `{json.dumps(source.get('metadata'), sort_keys=True)}`")
  for inventory in data.get("inventories") or []:
    lines.append(f"- artifacts: {len(inventory.get('artifacts') or [])}; generated outputs: {len(inventory.get('generated_outputs') or [])}")
    lines.extend(inventory_artifact_lines(inventory))
  if len(lines) == 2:
    lines.append("- No inventory attached.")
  lines.append("")
  return lines


def inventory_artifact_lines(inventory: JsonDict) -> list[str]:
  lines: list[str] = []
  key_artifacts = inventory_key_artifacts(inventory)
  if key_artifacts:
    lines.append(f"  - bounded artifact list (first {MAX_INVENTORY_GROUP_ITEMS} per group):")
    for group in ordered_inventory_groups(key_artifacts):
      lines.extend(inventory_group_lines(group, key_artifacts[group], inventory, "    "))
  generated_outputs = inventory.get("generated_outputs") or []
  if generated_outputs:
    if not key_artifacts:
      lines.append(f"  - bounded artifact list (first {MAX_INVENTORY_GROUP_ITEMS} per group):")
    lines.append(f"    - generated outputs ({len(generated_outputs)}):")
    lines.extend(inventory_item_lines(generated_outputs, inventory, "      "))
  return lines


def inventory_key_artifacts(inventory: JsonDict) -> JsonDict:
  key_artifacts = inventory.get("key_artifacts") or {}
  if key_artifacts:
    return key_artifacts
  grouped: JsonDict = {}
  for artifact in inventory.get("artifacts") or []:
    if not isinstance(artifact, dict):
      continue
    artifact_type = artifact.get("artifact_type")
    if artifact_type and artifact_type != "other":
      grouped.setdefault(artifact_type, []).append(artifact)
  return grouped


def ordered_inventory_groups(groups: JsonDict) -> list[str]:
  preferred = [name for name in INVENTORY_GROUP_ORDER if name in groups]
  remaining = sorted(name for name in groups if name not in INVENTORY_GROUP_ORDER)
  return preferred + remaining


def inventory_group_lines(group: str, items: object, inventory: JsonDict, indent: str) -> list[str]:
  normalized = list(items) if isinstance(items, list) else []
  return [f"{indent}- {inline_code(group)} ({len(normalized)})", *inventory_item_lines(normalized, inventory, indent + "  ")]


def inventory_item_lines(items: list[object], inventory: JsonDict, indent: str) -> list[str]:
  lines = [f"{indent}- {inline_code(inventory_item_text(item, inventory))}" for item in items[:MAX_INVENTORY_GROUP_ITEMS]]
  remaining = len(items) - MAX_INVENTORY_GROUP_ITEMS
  if remaining > 0:
    lines.append(f"{indent}- ... {remaining} more")
  return lines


def inventory_item_text(item: object, inventory: JsonDict) -> str:
  if isinstance(item, dict):
    path = item.get("path") or item.get("uri") or item.get("url") or item.get("name")
    if path:
      return inventory_display_path(str(path), inventory)
    return json.dumps(item, sort_keys=True)
  return str(item)


def inventory_display_path(path: str, inventory: JsonDict) -> str:
  if "://" in path or "!/" in path:
    return path
  source = inventory.get("source") or {}
  if source.get("resolved_type") != "local_log_dir":
    return path
  root = source.get("root")
  if not root or "://" in str(root):
    return path
  artifact_path = Path(path)
  if not artifact_path.is_absolute():
    return path
  try:
    return str(artifact_path.relative_to(Path(str(root))))
  except ValueError:
    return path


def is_plain_inventory_report(data: JsonDict) -> bool:
  return data.get("title") == "Phoenix Source Inventory" and not data.get("signal_results") and not data.get("check_results")


def is_hil_legacy_report(data: JsonDict) -> bool:
  return bool((data.get("extra") or {}).get("legacy_packet")) and data.get("title") in {"HIL/GHA Inventory", "Recent HIL Sources"}


def section_hil_gha_inventory(data: JsonDict) -> list[str]:
  packet = (data.get("extra") or {}).get("legacy_packet") or {}
  lines = ["## Remote Evidence Inventory", ""]
  start = len(lines)
  append_packet_source(lines, packet)
  append_github_run(lines, packet.get("github") or {})
  append_candidates(lines, packet.get("candidates") or [])
  append_jobs(lines, packet.get("jobs") or [])
  append_s3_evidence(lines, packet.get("s3") or {}, "### Top-level S3 evidence")
  append_test_records(lines, packet.get("test_records") or [], "### Top-level test_record.json")
  append_log_summary(lines, packet.get("log_summary") or {}, "### Top-level log summary")
  append_packet_notes(lines, "Ambiguity", packet.get("ambiguity") or [])
  append_packet_notes(lines, "Confidence", packet.get("confidence") or [])
  if len(lines) == start:
    lines.append("- HIL packet did not include concrete jobs, S3 artifacts, test records, Baraza links, or log summaries.")
    lines.append("")
  return lines


def append_packet_source(lines: list[str], packet: JsonDict) -> None:
  source = packet.get("source") or {}
  if not source:
    return
  fields = ["kind", "repo", "run_id", "job_id", "s3_uri", "local_path", "input"]
  rows = [{"field": key, "value": source.get(key)} for key in fields if source.get(key) not in (None, "")]
  append_table(lines, "### Packet source", ["field", "value"], rows)


def append_github_run(lines: list[str], github: JsonDict) -> None:
  run = github.get("run") or {}
  if not run:
    return
  rows = [{"field": key, "value": run.get(key)} for key in ("run_id", "title", "workflow", "branch", "status", "conclusion", "url", "html_url") if run.get(key) not in (None, "")]
  append_table(lines, "### GitHub run", ["field", "value"], rows)


def append_candidates(lines: list[str], candidates: list[JsonDict]) -> None:
  rows = []
  for candidate in candidates[:MAX_REMOTE_TABLE_ROWS]:
    rows.append({
      "job": candidate.get("job_name") or candidate.get("name"),
      "run_id": candidate.get("run_id"),
      "job_id": candidate.get("job_id"),
      "status": candidate.get("job_status") or candidate.get("status"),
      "conclusion": candidate.get("job_conclusion") or candidate.get("conclusion"),
      "url": candidate.get("job_url") or candidate.get("url"),
      "test_record": ((candidate.get("test_record_confirmation") or {}).get("status")),
    })
  append_table(lines, "### Candidate HIL jobs", ["job", "run_id", "job_id", "status", "conclusion", "url", "test_record"], rows, total_count=len(candidates))


def append_jobs(lines: list[str], jobs: list[JsonDict]) -> None:
  for index, job in enumerate(jobs[:MAX_REMOTE_JOBS], start=1):
    candidate = job.get("candidate") or {}
    meta = (job.get("github") or {}).get("job") or {}
    name = meta.get("name") or candidate.get("job_name") or f"job {index}"
    lines.extend([f"### Job: {name}", ""])
    rows = [{"field": key, "value": value} for key, value in job_fields(candidate, meta) if value not in (None, "")]
    append_table_rows(lines, ["field", "value"], rows)
    confirmation = job.get("test_record_confirmation") or {}
    if confirmation:
      lines.append(f"- test_record confirmation: `{confirmation.get('status')}` for `{confirmation.get('query')}` ({confirmation.get('reason')})")
      lines.append("")
    append_log_summary(lines, job.get("log_summary") or {}, "#### Lightweight log summary")
    append_s3_evidence(lines, job.get("s3") or {}, "#### Links and artifacts")
    append_test_records(lines, job.get("test_records") or [], "#### test_record.json")
  if len(jobs) > MAX_REMOTE_JOBS:
    lines.append(f"- ... {len(jobs) - MAX_REMOTE_JOBS} more job(s) omitted")
    lines.append("")


def job_fields(candidate: JsonDict, meta: JsonDict) -> list[tuple[str, object]]:
  return [
    ("run_id", meta.get("run_id") or candidate.get("run_id")),
    ("job_id", meta.get("id") or meta.get("job_id") or candidate.get("job_id")),
    ("status", meta.get("status") or candidate.get("job_status") or candidate.get("status")),
    ("conclusion", meta.get("conclusion") or candidate.get("job_conclusion") or candidate.get("conclusion")),
    ("runner_name", meta.get("runner_name") or candidate.get("runner_name")),
    ("started_at", meta.get("started_at") or candidate.get("started_at")),
    ("completed_at", meta.get("completed_at") or candidate.get("completed_at")),
    ("url", meta.get("url") or meta.get("html_url") or candidate.get("job_url") or candidate.get("url")),
  ]


def append_s3_evidence(lines: list[str], s3: JsonDict, heading: str) -> None:
  if not s3_has_evidence(s3):
    return
  lines.extend([heading, ""])
  for label, values in (("S3 roots", s3.get("roots") or []), ("S3 links", s3.get("s3_links") or []), ("Baraza links", s3.get("baraza_links") or []), ("test_record.json", s3.get("test_record_uris") or [])):
    append_bounded_values(lines, label, values)
  inventories = s3.get("inventories") or []
  rows = [{
    "s3_uri": inventory.get("s3_uri"),
    "objects": inventory.get("count"),
    "total_size": inventory.get("total_size"),
    "truncated": inventory.get("truncated"),
    "key_hints": len(inventory.get("key_artifact_hints") or []),
    "test_records": len(inventory.get("test_record_artifacts") or []),
  } for inventory in inventories[:MAX_REMOTE_TABLE_ROWS]]
  append_table(lines, "##### S3 inventory rows", ["s3_uri", "objects", "total_size", "truncated", "key_hints", "test_records"], rows, total_count=len(inventories))
  append_key_artifacts(lines, s3)
  append_baraza_context(lines, s3, [], "##### Baraza / mission context")


def s3_has_evidence(s3: JsonDict) -> bool:
  return any(s3.get(key) for key in ("roots", "s3_links", "baraza_links", "test_record_uris", "inventories", "baraza"))


def append_key_artifacts(lines: list[str], s3: JsonDict) -> None:
  rows = []
  for inventory in s3.get("inventories") or []:
    for artifact in inventory.get("test_record_artifacts") or []:
      rows.append(key_artifact_row("test_record", artifact))
    for hint in inventory.get("key_artifact_hints") or []:
      rows.append(key_artifact_row(hint.get("category") or "artifact", hint))
  append_table(lines, "##### Key artifact hints", ["category", "type", "uri", "size", "note"], rows[:MAX_REMOTE_TABLE_ROWS], total_count=len(rows))


def key_artifact_row(category: str, item: JsonDict) -> JsonDict:
  return {"category": category, "type": item.get("type"), "uri": item.get("uri") or item.get("path") or item.get("key"), "size": item.get("size"), "note": item.get("note")}


def append_test_records(lines: list[str], records: list[JsonDict], heading: str) -> None:
  rows = []
  for record in records[:MAX_REMOTE_TABLE_ROWS]:
    matches = record.get("query_matches")
    rows.append({
      "uri": record.get("s3_uri") or record.get("uri") or record.get("path"),
      "test": record.get("test_name") or record.get("name") or record.get("test"),
      "result": record.get("result") or record.get("status"),
      "matches": len(matches) if isinstance(matches, list) else matches,
    })
  append_table(lines, heading, ["uri", "test", "result", "matches"], rows, total_count=len(records))
  if records:
    append_baraza_context(lines, {}, records, heading.replace("test_record.json", "Baraza / mission context"))


def append_baraza_context(lines: list[str], s3: JsonDict, records: list[JsonDict], heading: str) -> None:
  context = collect_baraza_context(s3, records)
  if not any(context.values()):
    return
  lines.extend([heading, ""])
  append_bounded_values(lines, "Baraza links", context["links"])
  append_bounded_values(lines, "Mission IDs", context["mission_ids"])
  append_bounded_values(lines, "Flight IDs", context["flight_ids"])
  lines.append("")


def collect_baraza_context(s3: JsonDict, records: list[JsonDict]) -> JsonDict:
  context = {"links": [], "mission_ids": [], "flight_ids": []}
  merge_baraza(context, s3.get("baraza") or {})
  context["links"].extend(str(link) for link in s3.get("baraza_links") or [] if link)
  for inventory in s3.get("inventories") or []:
    merge_baraza(context, inventory.get("baraza") or {})
  for record in records:
    context["links"].extend(str(item.get("url")) for item in record.get("baraza_urls") or [] if item.get("url"))
    for item in record.get("mission_info_identifiers") or []:
      if item.get("kind") == "mission" and item.get("value"):
        context["mission_ids"].append(str(item["value"]))
      if item.get("kind") == "flight" and item.get("value"):
        context["flight_ids"].append(str(item["value"]))
  return {key: unique_strings(values) for key, values in context.items()}


def merge_baraza(context: JsonDict, baraza: JsonDict) -> None:
  context["links"].extend(str(link) for link in baraza.get("links") or [] if link)
  context["mission_ids"].extend(str(value) for value in baraza.get("mission_ids") or [] if value)
  context["flight_ids"].extend(str(value) for value in baraza.get("flight_ids") or [] if value)
  for candidate in baraza.get("candidates") or []:
    if candidate.get("link"):
      context["links"].append(str(candidate["link"]))
    if candidate.get("mission_id"):
      context["mission_ids"].append(str(candidate["mission_id"]))
    if candidate.get("flight_id"):
      context["flight_ids"].append(str(candidate["flight_id"]))


def append_log_summary(lines: list[str], summary: JsonDict, heading: str) -> None:
  if not summary:
    return
  lines.extend([heading, ""])
  counts = [f"{label}: {len(summary.get(key) or [])}" for key, label in REMOTE_LOG_SUMMARY_KEYS]
  lines.append("- counts: " + "; ".join(counts))
  for key, label in REMOTE_LOG_SUMMARY_KEYS:
    values = summary.get(key) or []
    if values:
      lines.append(f"- {label}:")
      for item in values[:MAX_REMOTE_LIST_ITEMS]:
        if isinstance(item, dict):
          prefix = f"L{item.get('line')}: " if item.get("line") is not None else ""
          lines.append(f"  - {prefix}{item.get('text') or json.dumps(item, sort_keys=True)}")
        else:
          lines.append(f"  - {item}")
  lines.append("")


def append_packet_notes(lines: list[str], label: str, notes: list[str]) -> None:
  if not notes:
    return
  lines.extend([f"### {label}", ""])
  lines.extend(f"- {note}" for note in notes[:MAX_REMOTE_LIST_ITEMS])
  if len(notes) > MAX_REMOTE_LIST_ITEMS:
    lines.append(f"- ... {len(notes) - MAX_REMOTE_LIST_ITEMS} more")
  lines.append("")


def append_bounded_values(lines: list[str], label: str, values: list[object]) -> None:
  values = [value for value in values if value not in (None, "")]
  if not values:
    return
  lines.append(f"- {label}:")
  for value in values[:MAX_REMOTE_LIST_ITEMS]:
    lines.append(f"  - {value}")
  if len(values) > MAX_REMOTE_LIST_ITEMS:
    lines.append(f"  - ... {len(values) - MAX_REMOTE_LIST_ITEMS} more")


def append_table(lines: list[str], title: str, headers: list[str], rows: list[JsonDict], total_count: int | None = None) -> None:
  rows = [row for row in rows if any(row.get(header) not in (None, "") for header in headers)]
  if not rows:
    return
  lines.extend([title, ""])
  append_table_rows(lines, headers, rows)
  if total_count is not None and total_count > len(rows):
    lines.append(f"_Showing {len(rows)} of {total_count}._")
    lines.append("")


def append_table_rows(lines: list[str], headers: list[str], rows: list[JsonDict]) -> None:
  if not rows:
    return
  lines.append("| " + " | ".join(headers) + " |")
  lines.append("| " + " | ".join("---" for _ in headers) + " |")
  for row in rows:
    lines.append("| " + " | ".join(cell(row.get(header)) for header in headers) + " |")
  lines.append("")


def unique_strings(values: list[str]) -> list[str]:
  result = []
  seen: set[str] = set()
  for value in values:
    if value and value not in seen:
      seen.add(value)
      result.append(value)
  return result

def section_evidence(data: JsonDict) -> list[str]:
  lines = ["## Evidence Table", ""]
  rows = data.get("evidence_table") or []
  if not rows:
    return lines + ["No evidence rows recorded.", ""]
  lines.append("| Finding | Source | Supports | Does not prove |")
  lines.append("|---|---|---|---|")
  for row in rows:
    lines.append(f"| {cell(row.get('finding') or row.get('claim'))} | {cell(row.get('source_ref'))} | {cell(row.get('supports'))} | {cell(row.get('does_not_prove'))} |")
  lines.append("")
  return lines


def section_findings(data: JsonDict) -> list[str]:
  lines = ["## Signal and Check Findings", ""]
  for signal in data.get("signal_results") or []:
    request = signal.get("request") or {}
    lines.append(f"- signal topics={request.get('topics')} fields={request.get('fields')} backend=`{signal.get('backend')}`")
    matches = (signal.get("stats") or {}).get("topic_matches") or []
    for match in matches[:5]:
      lines.append(f"  - fuzzy match `{match.get('topic')}` score=`{match.get('score')}` reason=`{match.get('reason')}`")
    field_matches = (signal.get("stats") or {}).get("field_matches") or []
    for match in field_matches[:5]:
      lines.append(f"  - field match `{match.get('topic')}` `{match.get('field_path')}` score=`{match.get('score')}` source=`{match.get('source')}` topic_presence=`{match.get('topic_presence')}` extractable=`{match.get('extractable')}` reason=`{match.get('reason')}`")
  for check in data.get("check_results") or []:
    lines.append(f"- check `{check.get('name')}`: `{check.get('status')}` — {check.get('summary')}")
  if len(lines) == 2:
    lines.append("No signal or check findings recorded.")
  lines.append("")
  return lines


def section_text_search(data: JsonDict) -> list[str]:
  search = (data.get("extra") or {}).get("text_search") or {}
  if not search:
    return []
  lines = ["## Text Artifact Matches", ""]
  lines.append(f"- preset: `{search.get('preset')}`; query: `{search.get('query')}`; matches: {len(search.get('matches') or [])}")
  truncation = search.get("truncation") or {}
  if truncation.get("truncated"):
    lines.append(f"- truncation: `max_matches_reached={bool(truncation.get('max_matches_reached'))}`; max bytes/file: `{truncation.get('max_bytes_per_file')}`")
  grouped: dict[tuple[str, str], list[JsonDict]] = {}
  for match in search.get("matches") or []:
    grouped.setdefault((match.get("artifact_type") or "unknown", match.get("path") or ""), []).append(match)
  if not grouped:
    lines.append("No text matches recorded.")
    lines.append("")
    return lines
  for (artifact_type, path), matches in sorted(grouped.items()):
    lines.append(f"### `{artifact_type}` — `{path}`")
    lines.append("")
    for match in matches:
      for before in match.get("before") or []:
        lines.append(f"- L{before.get('line_number')} context: {inline_code(before.get('text'))}")
      lines.append(f"- L{match.get('line_number')}: {inline_code(match.get('text'))}")
      for after in match.get("after") or []:
        lines.append(f"- L{after.get('line_number')} context: {inline_code(after.get('text'))}")
    lines.append("")
  return lines


def section_summary_metrics(data: JsonDict) -> list[str]:
  summary = (data.get("extra") or {}).get("summary_metrics") or {}
  if not summary:
    return []
  rows = summary.get("rows") or []
  lines = ["## Summary Metrics", ""]
  lines.append(f"- csv: `{summary.get('csv')}`; metrics: `{', '.join(summary.get('metrics') or [])}`; rows: {len(rows)}")
  if not rows:
    lines.append("No summary metric rows recorded.")
    lines.append("")
    return lines
  lines.append("| Path | Topic | Field | Metric | Samples | Result |")
  lines.append("|---|---|---|---|---|---|")
  for row in rows[:50]:
    lines.append(f"| {cell(row.get('path'))} | {cell(row.get('topic'))} | {cell(row.get('field'))} | {cell(row.get('metric'))} | {cell(row.get('sample_count'))} | {cell(summary_metric_result(row))} |")
  if len(rows) > 50:
    lines.append(f"|  |  |  | truncated |  | showing 50 of {len(rows)} rows |")
  lines.append("")
  return lines


def summary_metric_result(row: JsonDict) -> str:
  metric = row.get("metric")
  if metric == "transitions":
    return f"changes={row.get('transition_count')} first={row.get('first_value')} last={row.get('last_value')}"
  if metric == "minmax":
    return f"min={row.get('min')} max={row.get('max')} numeric_count={row.get('numeric_count')}"
  if metric == "delta":
    return f"delta={row.get('delta')} first={row.get('first_value')} last={row.get('last_value')}"
  return json.dumps(row, sort_keys=True)


def section_timebase(data: JsonDict) -> list[str]:
  lines = ["## Timebase and Alignment", ""]
  timebases = []
  for signal in data.get("signal_results") or []:
    if signal.get("timebase"):
      timebases.append(signal["timebase"])
  if not timebases:
    return lines + ["No aligned timebase was required or established.", ""]
  for item in timebases:
    lines.append(f"- `{item.get('time_kind', 'unknown')}` `{item.get('units', 'unknown')}` origin=`{item.get('origin', 'unknown')}` alignment=`{item.get('alignment_method', 'not_aligned')}` confidence=`{item.get('alignment_confidence', 'blocked')}`")
  lines.append("")
  return lines


def section_proves(data: JsonDict) -> list[str]:
  return ["## Proves / Does Not Prove", "", "Proves:", *bullets(data.get("proves") or ["No diagnostic proof claimed."]), "", "Does not prove:", *bullets(data.get("does_not_prove") or ["Does not prove root cause without corroborating evidence."]), ""]


def section_blockers(data: JsonDict) -> list[str]:
  lines = ["## Blockers and Missing Evidence", ""]
  blockers = data.get("blockers") or []
  for inventory in data.get("inventories") or []:
    blockers.extend(inventory.get("blockers") or [])
  for source in data.get("sources") or []:
    blockers.extend(source.get("blockers") or [])
  if not blockers:
    return lines + ["No blockers recorded.", ""]
  lines.append("| Code | Category | Severity | Message | Needed action |")
  lines.append("|---|---|---|---|---|")
  seen = set()
  for blocker in blockers:
    key = json.dumps(blocker, sort_keys=True)
    if key in seen:
      continue
    seen.add(key)
    lines.append(f"| {cell(blocker.get('code'))} | {cell(blocker.get('category'))} | {cell(blocker.get('severity'))} | {cell(blocker.get('message'))} | {cell(blocker.get('needed_action'))} |")
  lines.append("")
  return lines


def section_outputs(data: JsonDict) -> list[str]:
  return ["## Output Paths", "", *bullets(data.get("output_paths") or ["stdout only"]), ""]


def section_next(data: JsonDict) -> list[str]:
  return ["## Next Commands", "", *bullets(data.get("next_commands") or ["Run `phoenix_inspector inventory <source>` first for a new source."]), ""]


def write_report(report: EvidenceReport, output_format: str, out_dir: str | None, label: str) -> tuple[list[str], str]:
  if not out_dir:
    return [], render_json(report) if output_format == "json" else render_markdown(report)

  directory = Path(out_dir)
  directory.mkdir(parents=True, exist_ok=True)
  outputs = []
  if output_format in {"json", "both"}:
    outputs.append(str(directory / f"{slug(label)}.json"))
  if output_format in {"markdown", "both"}:
    outputs.append(str(directory / f"{slug(label)}.md"))
  report.output_paths.extend(path for path in outputs if path not in report.output_paths)

  json_output = render_json(report) if output_format in {"json", "both"} else None
  markdown_output = render_markdown(report) if output_format in {"markdown", "both"} else None
  if json_output is not None:
    Path(outputs[0]).write_text(json_output, encoding="utf-8")
  if markdown_output is not None:
    Path(outputs[-1]).write_text(markdown_output, encoding="utf-8")
  return outputs, json_output if output_format == "json" else (markdown_output or "")


def bullets(items: list[str]) -> list[str]:
  return [f"- {item}" for item in items]


def cell(value: object) -> str:
  return str(value or "").replace("|", "\\|").replace("\n", " ")


def inline_code(value: object) -> str:
  return "`" + str(value or "").replace("`", "\\`").replace("\n", " ") + "`"


def slug(value: str) -> str:
  value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
  return value[:120] or "phoenix-inspector"
