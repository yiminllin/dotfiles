from __future__ import annotations

import json
import re
from pathlib import Path

from .models import EvidenceReport, JsonDict


def render_json(report: EvidenceReport | JsonDict) -> str:
  data = report.to_dict() if isinstance(report, EvidenceReport) else report
  return json.dumps(data, indent=2, sort_keys=True) + "\n"


def render_markdown(report: EvidenceReport | JsonDict) -> str:
  data = report.to_dict() if isinstance(report, EvidenceReport) else report
  lines = [f"# {data.get('title', 'Phoenix Inspector Report')}", ""]
  lines.extend(["## Summary", "", data.get("summary") or f"Status: `{data.get('status')}`; confidence: `{data.get('confidence', 'low')}`.", ""])
  lines.extend(section_source_inventory(data))
  lines.extend(section_evidence(data))
  lines.extend(section_text_search(data))
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
    key_artifacts = inventory.get("key_artifacts") or {}
    if key_artifacts:
      lines.append(f"  - key artifact groups: {', '.join(sorted(key_artifacts))}")
  if len(lines) == 2:
    lines.append("- No inventory attached.")
  lines.append("")
  return lines


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
  if output_format in {"json", "both"}:
    path = Path(outputs[0])
    path.write_text(render_json(report), encoding="utf-8")
  if output_format in {"markdown", "both"}:
    path = Path(outputs[-1])
    path.write_text(render_markdown(report), encoding="utf-8")
  return outputs, "\n".join(outputs) + ("\n" if outputs else "")


def bullets(items: list[str]) -> list[str]:
  return [f"- {item}" for item in items]


def cell(value: object) -> str:
  return str(value or "").replace("|", "\\|").replace("\n", " ")


def inline_code(value: object) -> str:
  return "`" + str(value or "").replace("`", "\\`").replace("\n", " ") + "`"


def slug(value: str) -> str:
  value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
  return value[:120] or "phoenix-inspector"
