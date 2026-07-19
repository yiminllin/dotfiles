from __future__ import annotations

import csv
import io
import json
from typing import Any

from .models import JsonDict


def render_json(packet: JsonDict) -> str:
  return json.dumps(packet, indent=2, sort_keys=True) + "\n"


def render_markdown(packet: JsonDict) -> str:
  title = "ZML Pass/Fail Comparison" if packet.get("mode") == "compare" else "ZML Topic List" if packet.get("mode") == "topics" else "ZML Field Discovery" if packet.get("mode") == "fields" else "ZML Signal Audit"
  lines = [f"# {title}", ""]
  lines.append(f"- Status: `{packet.get('status', 'unknown')}`")
  lines.append(f"- Mode: `{packet.get('mode', 'unknown')}`")
  if packet.get("query", {}).get("window"):
    lines.append(f"- Window: `{packet['query']['window']}`")
  lines.append("")

  append_blockers(lines, packet.get("blockers") or [])
  append_sources(lines, packet)
  if packet.get("mode") == "topics":
    append_topic_listing(lines, packet.get("files") or [])
  elif packet.get("mode") == "fields":
    append_field_discovery(lines, packet.get("files") or [])
  elif packet.get("mode") == "compare":
    append_comparison(lines, packet.get("comparison") or {})
  else:
    append_files(lines, packet.get("files") or [])
  return "\n".join(lines).rstrip() + "\n"


CSV_COLUMNS = [
  "row_type",
  "source",
  "file",
  "topic",
  "timestamp",
  "field",
  "value",
  "stat",
  "count",
  "missing_count",
  "first",
  "last",
  "min",
  "max",
  "mean",
  "transition_count",
]


def render_csv(packet: JsonDict) -> str:
  output = io.StringIO()
  writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
  writer.writeheader()
  for row in csv_rows(packet):
    writer.writerow({column: csv_cell(row.get(column)) for column in CSV_COLUMNS})
  return output.getvalue()


def csv_rows(packet: JsonDict) -> list[JsonDict]:
  rows: list[JsonDict] = []
  if packet.get("mode") == "compare":
    rows.extend(file_csv_rows(packet.get("fail") or {}, "fail"))
    rows.extend(file_csv_rows(packet.get("pass") or {}, "pass"))
    return rows
  source = (packet.get("source") or {}).get("input", "")
  for file_result in packet.get("files") or []:
    rows.extend(file_csv_rows(file_result, source))
  return rows


def append_sources(lines: list[str], packet: JsonDict) -> None:
  sources = packet.get("sources") or []
  source = packet.get("source")
  if source:
    sources = [source]
  if not sources:
    return
  lines.extend(["## Sources", ""])
  for item in sources:
    lines.append(f"- `{item.get('input')}` ({item.get('kind')})")
    for candidate in item.get("candidates") or []:
      lines.append(f"  - `{candidate}`")
  lines.append("")


def append_topic_listing(lines: list[str], files: list[JsonDict]) -> None:
  for file_result in files:
    lines.extend([f"## File: `{file_result.get('path')}`", ""])
    if file_result.get("topic_matches"):
      append_table(lines, ["topic", "score", "reason"], file_result.get("topic_matches") or [])
    else:
      append_table(lines, ["topic"], [{"topic": topic} for topic in file_result.get("topics") or []])


def append_field_discovery(lines: list[str], files: list[JsonDict]) -> None:
  for file_result in files:
    lines.extend([f"## File: `{file_result.get('path')}`", ""])
    discovery = file_result.get("field_discovery") or {}
    bounds = discovery.get("bounds") or {}
    if bounds:
      lines.append(
        f"_Bounds: sampled {discovery.get('sampled_topic_count', 0)} of {discovery.get('candidate_topic_count', 0)} candidate topic(s); "
        f"max topics `{bounds.get('max_topics_sampled')}`, samples/topic `{bounds.get('sample_limit_per_topic')}`, fields/topic `{bounds.get('max_fields_per_topic')}`._"
      )
      lines.append("")
    backend_source = discovery.get("backend_source")
    if backend_source or discovery.get("needs_sampling"):
      sampling_hint = "; needs `--sample-top` or a topic filter" if discovery.get("needs_sampling") else ""
      lines.append(f"_Discovery backend: `{backend_source or 'unknown'}`{sampling_hint}._")
      lines.append("")
    append_table(lines, ["zml_path", "topic", "field_path", "score", "reason", "source", "topic_presence", "extractable", "confidence", "needs_sampling", "sample_count", "example_value"], file_result.get("field_matches") or [])
    topic_rows = discovery.get("sampled_topics") or []
    append_table(lines, ["topic", "sample_count", "parsed_sample_count", "omitted_sample_count", "field_count", "omitted_field_count", "field_scan_truncated_sample_count"], topic_rows, title="### Bounds / truncation")


def append_files(lines: list[str], files: list[JsonDict]) -> None:
  for file_result in files:
    lines.extend([f"## File: `{file_result.get('path')}`", ""])
    topics = file_result.get("topics") or []
    append_table(lines, ["topic", "present", "samples", "first", "last", "rate_hz"], [topic_row(topic) for topic in topics])
    for topic in topics:
      append_field_table(lines, topic)


def append_comparison(lines: list[str], comparison: JsonDict) -> None:
  tolerances = comparison.get("tolerances") or {}
  if tolerances:
    lines.extend(["## Tolerances", ""])
    lines.append(f"- Time: `{tolerances.get('time')}`")
    lines.append(f"- Numeric: `{tolerances.get('numeric')}`")
    lines.append("")
  lines.extend(["## Missing topics", ""])
  lines.append(f"- Missing in fail: {code_list(comparison.get('missing_in_fail') or [])}")
  lines.append(f"- Missing in pass: {code_list(comparison.get('missing_in_pass') or [])}")
  lines.append("")
  rows = []
  for topic in comparison.get("topics") or []:
    rows.append(
      {
        "topic": topic.get("topic"),
        "count_delta": topic.get("sample_count_delta"),
        "rate_delta_hz": topic.get("rate_delta_hz"),
        "first_ts_delta": topic.get("first_timestamp_delta"),
        "last_ts_delta": topic.get("last_timestamp_delta"),
      }
    )
  append_table(lines, ["topic", "count_delta", "rate_delta_hz", "first_ts_delta", "last_ts_delta"], rows, title="## Topic deltas")
  append_table(lines, ["topic", "field", "fail_count", "pass_count", "mean_delta", "min_delta", "max_delta", "first_delta", "last_delta", "transition_delta"], field_delta_rows(comparison), title="## Field deltas")
  append_table(lines, ["topic", "matched_sample_count", "unmatched_fail_sample_count", "unmatched_pass_sample_count", "unmatched_fail_timestamps", "unmatched_pass_timestamps"], comparison.get("timestamp_alignment") or [], title="## Timestamp alignment")
  divergences = comparison.get("first_divergences") or []
  append_table(lines, ["topic", "timestamp", "pass_timestamp", "time_delta", "sample_index", "field", "fail_value", "pass_value", "reason"], divergences, title="## First divergences")


def field_delta_rows(comparison: JsonDict) -> list[JsonDict]:
  rows = []
  for topic in comparison.get("topics") or []:
    for field in topic.get("fields") or []:
      rows.append(
        {
          "topic": topic.get("topic"),
          "field": field.get("field"),
          "fail_count": field.get("fail_present_count"),
          "pass_count": field.get("pass_present_count"),
          "mean_delta": field.get("mean_delta"),
          "min_delta": field.get("min_delta"),
          "max_delta": field.get("max_delta"),
          "first_delta": field.get("first_delta"),
          "last_delta": field.get("last_delta"),
          "transition_delta": field.get("transition_count_delta"),
        }
      )
  return rows


def append_field_table(lines: list[str], topic: JsonDict) -> None:
  field_expansion = topic.get("field_expansion") or {}
  if field_expansion.get("truncated_sample_count", 0) > 0:
    lines.append(
      f"_Field expansion truncated for {field_expansion.get('truncated_sample_count')} sample(s) at {field_expansion.get('expanded_field_limit_per_sample')} fields per sample._"
    )
    lines.append("")
  fields = topic.get("fields") or {}
  if not fields:
    return
  rows = []
  for name, stats in fields.items():
    row = {"field": name}
    row.update(stats)
    rows.append(row)
  append_table(lines, ["field", "count", "missing_count", "first", "last", "min", "max", "mean", "transition_count"], rows, title=f"### Fields: `{topic.get('topic')}`")
  transition_rows = []
  for name, stats in fields.items():
    for detail in stats.get("transition_details") or []:
      row = {"field": name}
      row.update(detail)
      transition_rows.append(row)
  if transition_rows:
    append_table(lines, ["field", "timestamp", "from_value", "to_value"], transition_rows, title=f"### Transitions: `{topic.get('topic')}`")


def file_csv_rows(file_result: JsonDict, source: str) -> list[JsonDict]:
  rows: list[JsonDict] = []
  path = file_result.get("path", "")
  for topic in file_result.get("topics") or []:
    topic_name = topic.get("topic")
    rows.append(
      {
        "row_type": "topic_stats",
        "source": source,
        "file": path,
        "topic": topic_name,
        "stat": "sample_count",
        "count": topic.get("sample_count"),
        "first": topic.get("first_timestamp"),
        "last": topic.get("last_timestamp"),
        "value": topic.get("approximate_rate_hz"),
      }
    )
    for field, stats in (topic.get("fields") or {}).items():
      row = {"row_type": "field_stats", "source": source, "file": path, "topic": topic_name, "field": field}
      row.update(stats)
      rows.append(row)
    field_expansion = topic.get("field_expansion") or {}
    if field_expansion.get("truncated_sample_count", 0) > 0:
      rows.append(
        {
          "row_type": "field_expansion_truncated",
          "source": source,
          "file": path,
          "topic": topic_name,
          "stat": "truncated_samples",
          "count": field_expansion.get("truncated_sample_count"),
          "value": f"field expansion capped at {field_expansion.get('expanded_field_limit_per_sample')} fields per sample",
        }
      )
    for sample in topic.get("samples") or []:
      fields = sample.get("fields") or {}
      if not fields:
        rows.append({"row_type": "sample", "source": source, "file": path, "topic": sample.get("topic", topic_name), "timestamp": sample.get("timestamp")})
      for field, value in sorted(fields.items()):
        rows.append(
          {
            "row_type": "sample",
            "source": source,
            "file": path,
            "topic": sample.get("topic", topic_name),
            "timestamp": sample.get("timestamp"),
            "field": field,
            "value": value,
          }
        )
    export = topic.get("sample_export") or {}
    omitted_rows = export.get("omitted_sample_row_count", export.get("omitted_count", 0))
    if omitted_rows > 0:
      rows.append(
        {
          "row_type": "sample_export_truncated",
          "source": source,
          "file": path,
          "topic": topic_name,
          "stat": "omitted_sample_rows",
          "count": omitted_rows,
          "value": f"included {export.get('included_sample_row_count', export.get('included_count'))} of {export.get('total_sample_row_count', export.get('total_count'))} sample rows (limit {export.get('limit')})",
        }
      )
  return rows


def topic_row(topic: JsonDict) -> JsonDict:
  return {
    "topic": topic.get("topic"),
    "present": topic.get("present"),
    "samples": topic.get("sample_count"),
    "first": topic.get("first_timestamp"),
    "last": topic.get("last_timestamp"),
    "rate_hz": topic.get("approximate_rate_hz"),
  }


def append_blockers(lines: list[str], blockers: list[JsonDict]) -> None:
  if not blockers:
    return
  lines.extend(["## Blockers", ""])
  for blocker in blockers:
    lines.append(f"- {blocker.get('tool', 'tool')}: {blocker.get('message')}")
    if blocker.get("command"):
      lines.append(f"  - command: `{blocker['command']}`")
    if blocker.get("guidance"):
      lines.append(f"  - guidance: {blocker['guidance']}")
    if blocker.get("stderr_excerpt"):
      lines.append(f"  - stderr: `{markdown_cell(blocker['stderr_excerpt'])}`")
  lines.append("")


def append_table(lines: list[str], headers: list[str], rows: list[JsonDict], title: str | None = None) -> None:
  if title:
    lines.extend([title, ""])
  if not rows:
    lines.extend(["_None._", ""])
    return
  lines.append("| " + " | ".join(headers) + " |")
  lines.append("| " + " | ".join("---" for _ in headers) + " |")
  for row in rows:
    lines.append("| " + " | ".join(markdown_cell(row.get(header)) for header in headers) + " |")
  lines.append("")


def markdown_cell(value: Any) -> str:
  if value is None:
    return ""
  return str(value).replace("\n", " ").replace("|", "\\|")


def csv_cell(value: Any) -> str:
  if value is None:
    return ""
  if isinstance(value, (dict, list, tuple)):
    return json.dumps(value, sort_keys=True)
  return str(value)


def code_list(values: list[str]) -> str:
  return ", ".join(f"`{value}`" for value in values) if values else "_none_"
