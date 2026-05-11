from __future__ import annotations

import re
from pathlib import Path

from .inventory import build_inventory
from .models import ArtifactInventory, ArtifactRecord, Blocker, EvidenceReport
from .sources import resolve_source


DEFAULT_MAX_MATCHES = 100
DEFAULT_CONTEXT = 0
DEFAULT_MAX_BYTES_PER_FILE = 5 * 1024 * 1024
TEXT_PREVIEW_CHARS = 500
SEARCHABLE_TEXT_TYPES = {"phoenix_log", "journal", "test_log", "test_record", "validator_output", "alarm_output", "other"}
NON_SEARCHABLE_TYPES = {"zml", "zml_zst", "archive", "hil_packet_json"}
VALIDATOR_QUERY = r"FAIL|FAIL_VALIDATORS|FAIL_TEST|validator|Error Code|Traceback|Exception|unexpected-alarms"
JOURNAL_QUERY = r"error|failed|fault|watchdog|alarm|service|restart|Traceback|Exception|C2_STATUS|process_status"


def search_logs_report(args) -> EvidenceReport:
  return text_search_report(args, preset="search-logs", query=args.query, default_artifact_types=None, case_insensitive=False)


def validators_report(args) -> EvidenceReport:
  return text_search_report(args, preset="validators", query=args.query or VALIDATOR_QUERY, default_artifact_types=["validator_output", "alarm_output"], case_insensitive=False)


def journal_report(args) -> EvidenceReport:
  return text_search_report(args, preset="journal", query=args.query or JOURNAL_QUERY, default_artifact_types=["journal"], case_insensitive=True)


def text_search_report(args, preset: str, query: str, default_artifact_types: list[str] | None, case_insensitive: bool) -> EvidenceReport:
  resolved = resolve_source(args.source, preset, {"artifact_type": args.artifact_type or default_artifact_types, "max_matches": args.max_matches, "context": args.context})
  inventory = build_inventory(resolved)
  blockers = [*resolved.blockers, *inventory.blockers]

  if resolved.resolved_type in {"gha_url", "s3_root", "hil_packet_json", "unsupported_flight_id", "unknown"}:
    blockers.append(local_artifacts_blocker(args.source, resolved.resolved_type))
    return blocked_search_report(preset, args.source, query, resolved, inventory, blockers)

  selected_types = args.artifact_type or default_artifact_types
  artifacts = searchable_artifacts(inventory, selected_types)
  if not artifacts:
    blockers.append(Blocker("no_searchable_text_artifacts", "warning", "missing_artifact", "Inventory found no local non-ZML text artifacts matching the search scope.", args.source, "Provide an extracted local Phoenix log bundle or use --artifact-type with an inventoried text artifact type."))
    return blocked_search_report(preset, args.source, query, resolved, inventory, blockers)

  try:
    pattern = re.compile(query, re.IGNORECASE if case_insensitive else 0)
  except re.error as exc:
    blockers.append(Blocker("invalid_text_search_regex", "error", "validation_gap", f"Search regex could not be compiled: {exc}", query, "Provide a valid Python regular expression."))
    return blocked_search_report(preset, args.source, query, resolved, inventory, blockers)

  search = run_bounded_search(artifacts, pattern, args.max_matches, args.context, DEFAULT_MAX_BYTES_PER_FILE)
  search.update({"preset": preset, "query": query, "artifact_types": selected_types or "all_text", "case_insensitive": case_insensitive, "context": args.context, "max_matches": args.max_matches})
  status = "partial" if blockers else "ok"
  if search["truncation"]["max_matches_reached"] or search["truncation"]["files_truncated"] or search["truncation"]["files_skipped"]:
    status = "partial" if not blockers else "blocked"
  report = EvidenceReport(title=f"Phoenix Text Artifact Search: {preset}", status=status, sources=[resolved], inventories=[inventory], blockers=blockers, summary=f"Searched {search['stats']['files_searched']} local text artifact(s) for `{query}`; found {len(search['matches'])} match(es).", confidence="medium" if status in {"ok", "partial"} else "blocked", extra={"text_search": search})
  report.evidence_table.append({"finding": "bounded text artifact search", "source_ref": args.source, "supports": "Line-level regex matches in inventoried local non-ZML text artifacts.", "does_not_prove": "Text matches alone do not prove root cause or absence of matching evidence outside the bounded local source."})
  report.proves.append("Only inventoried local non-ZML text artifacts were searched.")
  report.does_not_prove.append("Search does not inspect binary/ZML signal content or remote artifacts that were not provided locally.")
  return report


def blocked_search_report(preset: str, source: str, query: str, resolved, inventory: ArtifactInventory, blockers: list[Blocker]) -> EvidenceReport:
  return EvidenceReport(title=f"Phoenix Text Artifact Search: {preset}", status="blocked", sources=[resolved], inventories=[inventory], blockers=blockers, summary=f"Text artifact search for `{query}` is blocked for `{source}`.", confidence="blocked", extra={"text_search": {"preset": preset, "query": query, "matches": [], "stats": {"matches": 0}, "truncation": {}}}, does_not_prove=["No remote downloads or broad filesystem searches were attempted."])


def local_artifacts_blocker(source: str, resolved_type: str) -> Blocker:
  return Blocker("text_search_requires_local_artifacts", "warning", "missing_artifact", f"Text artifact search requires an inventoried local log bundle; `{resolved_type}` has no local searchable artifacts.", source, "Run inventory to identify exact evidence paths, then provide a bounded fetched/extracted local bundle or selected local log artifact. Phoenix Inspector will not download remote artifacts for this command.")


def searchable_artifacts(inventory: ArtifactInventory, selected_types: list[str] | None) -> list[ArtifactRecord]:
  wanted = set(selected_types or SEARCHABLE_TEXT_TYPES)
  records = []
  for record in inventory.artifacts:
    if record.artifact_type in NON_SEARCHABLE_TYPES or record.artifact_type not in wanted:
      continue
    if "!/" in record.path:
      continue
    records.append(record)
  return records


def run_bounded_search(artifacts: list[ArtifactRecord], pattern: re.Pattern[str], max_matches: int, context: int, max_bytes_per_file: int) -> dict:
  matches = []
  file_summaries = []
  files_skipped = []
  files_truncated = []

  for index, record in enumerate(artifacts):
    if len(matches) >= max_matches:
      break
    file_result = search_file(record, pattern, max_matches - len(matches), context, max_bytes_per_file)
    if file_result["skipped"]:
      files_skipped.append({"path": record.path, "artifact_type": record.artifact_type, "reason": file_result["skip_reason"]})
    if file_result["truncated"]:
      files_truncated.append({"path": record.path, "artifact_type": record.artifact_type, "max_bytes": max_bytes_per_file})
    file_summaries.append({key: file_result[key] for key in ("path", "artifact_type", "matches", "truncated", "skipped", "limit_reached")})
    matches.extend(file_result["matches"])
    if len(matches) >= max_matches and index + 1 < len(artifacts):
      file_summaries[-1]["limit_reached"] = True

  max_matches_reached = any(item.get("limit_reached") for item in file_summaries)
  return {
    "matches": matches,
    "files": file_summaries,
    "stats": {"files_considered": len(artifacts), "files_searched": sum(1 for item in file_summaries if not item["skipped"]), "files_skipped": len(files_skipped), "matches": len(matches)},
    "truncation": {"truncated": bool(max_matches_reached or files_truncated or files_skipped), "max_matches_reached": max_matches_reached, "max_bytes_per_file": max_bytes_per_file, "files_truncated": files_truncated, "files_skipped": files_skipped},
  }


def search_file(record: ArtifactRecord, pattern: re.Pattern[str], remaining_matches: int, context: int, max_bytes_per_file: int) -> dict:
  path = Path(record.path)
  try:
    with path.open("rb") as handle:
      data = handle.read(max_bytes_per_file + 1)
  except OSError as exc:
    return skipped_file(record, f"read failed: {exc}")
  if b"\x00" in data[:4096]:
    return skipped_file(record, "binary content detected")
  truncated = len(data) > max_bytes_per_file
  data = data[:max_bytes_per_file]
  try:
    lines = data.decode("utf-8").splitlines()
  except UnicodeDecodeError:
    return skipped_file(record, "not UTF-8 text")

  matches = []
  limit_reached = False
  for index, line in enumerate(lines):
    if len(matches) >= remaining_matches:
      limit_reached = any(pattern.search(remaining_line) for remaining_line in lines[index:])
      break
    if not pattern.search(line):
      continue
    start = max(0, index - context)
    end = min(len(lines), index + context + 1)
    matches.append({
      "path": record.path,
      "artifact_type": record.artifact_type,
      "line_number": index + 1,
      "text": preview(line),
      "before": [{"line_number": before_index + 1, "text": preview(lines[before_index])} for before_index in range(start, index)],
      "after": [{"line_number": after_index + 1, "text": preview(lines[after_index])} for after_index in range(index + 1, end)],
    })
  return {"path": record.path, "artifact_type": record.artifact_type, "matches": matches, "truncated": truncated, "skipped": False, "skip_reason": None, "limit_reached": limit_reached}


def skipped_file(record: ArtifactRecord, reason: str) -> dict:
  return {"path": record.path, "artifact_type": record.artifact_type, "matches": [], "truncated": False, "skipped": True, "skip_reason": reason, "limit_reached": False}


def preview(text: str) -> str:
  return text if len(text) <= TEXT_PREVIEW_CHARS else text[:TEXT_PREVIEW_CHARS] + "…"
