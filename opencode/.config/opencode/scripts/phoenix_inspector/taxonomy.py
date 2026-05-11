from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from hil_evidence.packet import build_summary_packet

from .hil import recent_hil_report
from .models import BatchTaxonomyRow, Blocker, EvidenceReport

CLI = 'python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py"'


def taxonomy_recent_hil(args: Any) -> EvidenceReport:
  rows: list[BatchTaxonomyRow] = []
  for report_path in getattr(args, "report", None) or []:
    rows.append(row_from_report(report_path))
  if rows:
    return taxonomy_report(rows, [], args, "Loaded taxonomy rows from existing evidence report(s).")
  recent = recent_hil_report(args)
  legacy = recent.extra.get("legacy_packet") or {}
  candidates = legacy.get("candidates") or []
  for index, candidate in enumerate(candidates, start=1):
    rows.append(row_from_recent_candidate(candidate, recent.blockers, args, index))
  if not rows:
    blockers = [blocker.message for blocker in recent.blockers] or ["recent-hil returned no matching candidates for the requested filters"]
    rows.append(BatchTaxonomyRow(failure_reason="inconclusive", confidence="blocked" if recent.blockers else "low", blockers=blockers, evidence_status="not_loaded"))
  return taxonomy_report(rows, recent.blockers, args, f"Built taxonomy rows from {len(candidates)} recent HIL candidate(s).")


def row_from_recent_candidate(candidate: dict, recent_blockers: list[Blocker], args: Any, index: int) -> BatchTaxonomyRow:
  evidence_packet = None
  evidence_path = None
  evidence_status = "not_loaded"
  row_blockers = [blocker.message for blocker in recent_blockers]
  if getattr(args, "load_evidence", False):
    evidence_packet, evidence_status, evidence_path, evidence_blockers = load_candidate_evidence(candidate, args, index)
    row_blockers.extend(evidence_blockers)
  else:
    row_blockers.append("no per-run evidence report loaded for taxonomy label")

  failure_reason, confidence, evidence_summary = classify_evidence(candidate, evidence_packet, evidence_status)
  return BatchTaxonomyRow(
    gha_url=candidate.get("gha_url"),
    conclusion=candidate_conclusion(candidate),
    failure_reason=failure_reason,
    confidence=confidence,
    blockers=row_blockers,
    evidence_status=evidence_status,
    evidence_path=evidence_path,
    evidence_summary=evidence_summary,
    next_command=f"{CLI} inventory {candidate.get('gha_url')}" if candidate.get("gha_url") else None,
  )


def load_candidate_evidence(candidate: dict, args: Any, index: int) -> tuple[dict | None, str, str | None, list[str]]:
  source = candidate.get("gha_url")
  if not source:
    return None, "blocked", None, ["candidate has no gha_url for bounded evidence loading"]
  try:
    packet = build_summary_packet(source, preset=getattr(args, "preset", None), passing=getattr(args, "passing", False))
  except Exception as exc:
    return None, "blocked", None, [f"bounded evidence load failed for {source}: {exc}"]
  evidence_path = write_evidence_packet(packet, args, candidate, index)
  return packet, evidence_status(packet), evidence_path, packet_blocker_messages(packet)


def write_evidence_packet(packet: dict, args: Any, candidate: dict, index: int) -> str | None:
  out_dir = getattr(args, "out_dir", None)
  if not out_dir:
    return None
  Path(out_dir).mkdir(parents=True, exist_ok=True)
  job_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(candidate.get("job_id") or index)).strip("-") or str(index)
  path = Path(out_dir) / f"taxonomy-evidence-{job_id}.json"
  path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
  return str(path)


def evidence_status(packet: dict) -> str:
  if has_loaded_evidence(packet):
    return "partial" if packet.get("blockers") or packet.get("errors") or packet.get("status") in {"partial", "error", "blocked"} else "loaded"
  return "blocked" if packet.get("blockers") or packet.get("errors") or packet.get("status") in {"error", "blocked"} else "loaded"


def has_loaded_evidence(packet: dict | None) -> bool:
  if not packet:
    return False
  if packet.get("log_summary") or packet.get("test_records"):
    return True
  return any((job.get("log_summary") or job.get("test_records") or job.get("s3")) for job in packet.get("jobs") or [] if isinstance(job, dict))


def packet_blocker_messages(packet: dict) -> list[str]:
  messages = []
  for item in (packet.get("blockers") or []) + (packet.get("errors") or []):
    if isinstance(item, dict):
      messages.append(item.get("message") or item.get("tool") or str(item))
    else:
      messages.append(str(item))
  return messages


def classify_evidence(candidate: dict, packet: dict | None, status: str) -> tuple[str, str, str]:
  if candidate_is_passing(candidate, packet):
    return "pass", "medium", "GitHub/test-record evidence reports a passing job."
  if status == "not_loaded":
    return "inconclusive", "low", "Evidence was not loaded; candidate metadata alone is insufficient for a failure label."

  markers = evidence_markers(packet)
  validator_markers = actionable_validator_markers(markers["validator"])
  if marker_contains(validator_markers, r"validator"):
    return "validator_failure", "medium", summarize_marker("validator marker", validator_markers)
  if marker_contains(markers["alarm"], r"alarm"):
    return "alarm_failure", "medium", summarize_marker("alarm marker", markers["alarm"])
  if marker_contains(markers["all"], r"timed? out|timeout"):
    return "timeout", "medium", summarize_marker("timeout marker", markers["all"])
  if marker_contains(markers["all"], r"dashboard|reporting|report upload|push.*report|report.*push"):
    return "dashboard_push_or_reporting_issue", "medium", summarize_marker("dashboard/reporting marker", markers["all"])
  if markers["failed_tests"] or failed_test_records(packet):
    return "test_harness_failure", "medium", summarize_marker("test harness marker", markers["failed_tests"] or test_record_failure_summaries(packet))
  if status == "blocked" or infra_blocked(packet):
    return "infra_or_artifact_failure", "medium", summarize_marker("infrastructure/artifact blocker", markers["blockers"])
  return "unknown_after_evidence", "low", "Bounded evidence was loaded, but no supported failure marker was detected."


def evidence_markers(packet: dict | None) -> dict[str, list[str]]:
  validator: list[str] = []
  alarm: list[str] = []
  failed_tests_list: list[str] = []
  blockers = packet_blocker_messages(packet or {})
  for summary in log_summaries(packet):
    validator.extend(match.get("text", str(match)) for match in summary.get("validator_failures") or [])
    alarm.extend(match.get("text", str(match)) for match in summary.get("alarm_error_lines") or [])
    failed_tests_list.extend(str(item) for item in summary.get("failed_scenarios_or_tests") or [])
  all_markers = validator + alarm + failed_tests_list + blockers + test_record_failure_summaries(packet)
  return {"validator": validator, "alarm": alarm, "failed_tests": failed_tests_list, "blockers": blockers, "all": all_markers}


def log_summaries(packet: dict | None) -> list[dict]:
  if not packet:
    return []
  summaries = []
  if isinstance(packet.get("log_summary"), dict):
    summaries.append(packet["log_summary"])
  for job in packet.get("jobs") or []:
    if isinstance(job, dict) and isinstance(job.get("log_summary"), dict):
      summaries.append(job["log_summary"])
  return summaries


def marker_contains(values: list[str], pattern: str) -> bool:
  regex = re.compile(pattern, re.IGNORECASE)
  return any(regex.search(value) for value in values)


def actionable_validator_markers(values: list[str]) -> list[str]:
  return [value for value in values if not is_validator_table_header(value)]


def is_validator_table_header(value: str) -> bool:
  lowered = value.lower()
  return "validator name" in lowered and "passed" in lowered and "failed checks" in lowered


def summarize_marker(prefix: str, values: list[str]) -> str:
  return f"{prefix}: {values[0]}" if values else prefix


def candidate_is_passing(candidate: dict, packet: dict | None) -> bool:
  if str(candidate_conclusion(candidate) or "").lower() == "success":
    return True
  records = test_records(packet)
  results = [str(record.get("result") or "").lower() for record in records if record.get("result")]
  return bool(results) and all(result in {"pass", "passed", "success", "succeeded"} for result in results)


def failed_test_records(packet: dict | None) -> bool:
  return bool(test_record_failure_summaries(packet))


def test_record_failure_summaries(packet: dict | None) -> list[str]:
  failures = []
  for record in test_records(packet):
    result = str(record.get("result") or "").lower()
    if result in {"fail", "failed", "failure", "error"}:
      failures.append(str(record.get("test_name") or record.get("s3_uri") or result))
    for phase in record.get("phase_results") or []:
      phase_result = str(phase.get("result") or "").lower() if isinstance(phase, dict) else ""
      if phase_result in {"fail", "failed", "failure", "error"}:
        failures.append(str(phase.get("name") or phase_result))
  return failures


def test_records(packet: dict | None) -> list[dict]:
  if not packet:
    return []
  records = list(packet.get("test_records") or [])
  for job in packet.get("jobs") or []:
    if isinstance(job, dict):
      records.extend(job.get("test_records") or [])
  return [record for record in records if isinstance(record, dict)]


def infra_blocked(packet: dict | None) -> bool:
  blocker_text = "\n".join(packet_blocker_messages(packet or {})).lower()
  return any(token in blocker_text for token in ("gh ", "github", "aws", "s3", "artifact", "not found", "missing", "permission", "credential", "auth"))


def candidate_conclusion(candidate: dict) -> str | None:
  return candidate.get("job_conclusion") or candidate.get("run_conclusion")


def taxonomy_report(rows: list[BatchTaxonomyRow], blockers: list[Blocker], args: Any, summary: str) -> EvidenceReport:
  output_paths = []
  if args.csv:
    write_rows_csv(rows, args.csv)
    output_paths.append(args.csv)
  if args.out_dir:
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    md_path = Path(args.out_dir) / "taxonomy-recent-hil.md"
    md_path.write_text(render_rows_markdown(rows), encoding="utf-8")
    output_paths.append(str(md_path))
  report = EvidenceReport(title="Recent HIL Taxonomy", status="blocked" if blockers else "ok", blockers=blockers, output_paths=output_paths, summary=summary, confidence="low", extra={"rows": [row.to_dict() for row in rows]})
  report.proves.append("Batch taxonomy was derived from recent-HIL candidate evidence, not a separate database.")
  report.does_not_prove.append("Conservative taxonomy labels are not root-cause proof.")
  return report


def row_from_report(path: str) -> BatchTaxonomyRow:
  data = json.loads(Path(path).read_text(encoding="utf-8"))
  legacy = (data.get("extra") or {}).get("legacy_packet") or {}
  source = first_source_ref(data, legacy)
  blockers = [item.get("message") or item.get("code") or str(item) for item in data.get("blockers") or []]
  return BatchTaxonomyRow(
    gha_url=source.get("gha_url"),
    s3_root=source.get("s3_root"),
    baraza=source.get("baraza"),
    test=source.get("test"),
    subtest=source.get("subtest"),
    conclusion=source.get("conclusion") or data.get("status"),
    failure_reason=label_from_report(data),
    confidence=data.get("confidence") or "low",
    blockers=blockers,
    evidence_status="loaded",
    evidence_summary=data.get("summary"),
    report_path=path,
    next_command=f"{CLI} inspect {source.get('gha_url') or source.get('s3_root') or path}" if source else None,
  )


def first_source_ref(data: dict, legacy: dict) -> dict:
  for candidate in legacy.get("candidates") or []:
    return {"gha_url": candidate.get("gha_url"), "conclusion": candidate.get("job_conclusion") or candidate.get("run_conclusion")}
  for source in data.get("sources") or []:
    raw = (source.get("run_source") or {}).get("raw")
    if raw and str(raw).startswith("s3://"):
      return {"s3_root": raw, "conclusion": data.get("status")}
    if raw and "github.com" in str(raw):
      return {"gha_url": raw, "conclusion": data.get("status")}
  return {"conclusion": data.get("status")}


def label_from_report(data: dict) -> str:
  blocker_categories = {item.get("category") for item in data.get("blockers") or [] if isinstance(item, dict)}
  if "missing_artifact" in blocker_categories:
    return "infra_or_artifact_failure"
  if "backend_failure" in blocker_categories or "decode_failure" in blocker_categories:
    return "infra_or_artifact_failure"
  comparison = ((data.get("extra") or {}).get("legacy_packet") or {}).get("comparison") or {}
  if comparison.get("first_divergences"):
    return "signal_delta_detected"
  return "inconclusive"


def write_rows_csv(rows: list[BatchTaxonomyRow], path: str) -> None:
  Path(path).parent.mkdir(parents=True, exist_ok=True)
  with Path(path).open("w", newline="", encoding="utf-8") as handle:
    fieldnames = ["gha_url", "s3_root", "baraza", "test", "subtest", "conclusion", "failure_reason", "confidence", "evidence_status", "evidence_path", "evidence_summary", "blockers", "report_path", "next_command"]
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
      data = row.to_dict()
      data["blockers"] = "; ".join(data.get("blockers") or [])
      writer.writerow({key: data.get(key) for key in fieldnames})


def render_rows_markdown(rows: list[BatchTaxonomyRow]) -> str:
  lines = ["# Recent HIL Taxonomy", "", "| GHA | Conclusion | Failure reason | Confidence | Evidence | Summary | Blockers | Next |", "|---|---|---|---|---|---|---|---|"]
  for row in rows:
    data = row.to_dict()
    evidence = data.get("evidence_status", "")
    if data.get("evidence_path"):
      evidence = f"{evidence} ({data.get('evidence_path')})"
    lines.append(f"| {data.get('gha_url', '')} | {data.get('conclusion', '')} | {data.get('failure_reason', '')} | {data.get('confidence', '')} | {evidence} | {data.get('evidence_summary', '')} | {'; '.join(data.get('blockers') or [])} | {data.get('next_command', '')} |")
  return "\n".join(lines) + "\n"
