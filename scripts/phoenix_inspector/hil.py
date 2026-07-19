from __future__ import annotations

from typing import Any

from hil_evidence.packet import build_recent_packet, build_summary_packet

from .models import Blocker, EvidenceReport
from .sources import resolve_source

CLI = 'python3 "$HOME/dotfiles/scripts/phoenix_inspector.py"'


def inventory_remote_report(source: str, _args: Any) -> EvidenceReport:
  resolved = resolve_source(source, "inventory")
  if any(blocker.category == "safety_boundary" for blocker in resolved.blockers):
    report = EvidenceReport(title="HIL/GHA Inventory", status="blocked", sources=[resolved], blockers=resolved.blockers, summary="Remote inventory blocked by source safety boundary before any external listing.", confidence="blocked")
    report.next_commands.extend(remote_inventory_next_commands({}, source))
    return report
  try:
    packet = build_summary_packet(source)
  except Exception as exc:
    blocker = Blocker("hil_evidence_failed", "error", "backend_failure", f"HIL evidence wrapper failed: {exc}", source, "Run read-only auth/tool checks, then retry the exact same source.")
    report = EvidenceReport(title="HIL/GHA Inventory", status="blocked", sources=[resolved], blockers=[blocker], summary="HIL/GHA inventory blocked before exact source resolution completed.", confidence="blocked")
    report.next_commands.extend(remote_inventory_next_commands({}, source))
    return report
  report = packet_report("HIL/GHA Inventory", packet, [resolved])
  report.next_commands.extend(remote_inventory_next_commands(packet, source))
  return report


def recent_hil_report(args: Any) -> EvidenceReport:
  try:
    packet = build_recent_packet(preset=args.preset, passing=args.passing, max_matches=args.max_matches, limit=args.limit, lookback_hours=args.lookback_hours, job_name=args.job_name, title=args.title, branch=args.branch, status=args.status or [], conclusion=args.conclusion or [], test_record_query=args.test_record_query)
  except Exception as exc:
    blocker = Blocker("recent_hil_failed", "error", "backend_failure", f"Recent HIL wrapper failed: {exc}", needed_action="Ensure gh/aws credentials already exist; do not run interactive auth from phoenix_inspector.")
    return EvidenceReport(title="Recent HIL Sources", status="blocked", blockers=[blocker], summary="Recent HIL discovery blocked.", confidence="blocked")
  report = packet_report("Recent HIL Sources", packet, [])
  report.next_commands.extend([f"{CLI} inventory {candidate.get('gha_url')}" for candidate in packet.get("candidates") or [] if candidate.get("gha_url")][:5])
  return report


def packet_report(title: str, packet: dict, sources: list) -> EvidenceReport:
  blockers = [canonical_blocker(item) for item in (packet.get("blockers") or []) + (packet.get("errors") or [])]
  if packet.get("status") in {"no_matches", "no_hil_jobs"}:
    blockers.append(no_hil_evidence_blocker(packet))
  status = "blocked" if packet.get("status") in {"error", "blocked", "no_matches", "no_hil_jobs"} or blockers else "partial" if packet.get("status") == "partial" else "ok"
  report = EvidenceReport(title=title, status=status, sources=sources, blockers=blockers, summary=packet_summary(title, packet), confidence="medium" if status == "ok" else "blocked", extra={"legacy_packet": packet})
  report.evidence_table.append({"finding": title, "source_ref": (packet.get("source") or {}).get("input"), "supports": "Existing HIL evidence behavior was normalized into a canonical report.", "does_not_prove": "Does not independently prove root cause."})
  report.proves.append("Exact source was passed to the HIL wrapper; no recent-run substitution is performed by this command.")
  report.does_not_prove.append("Missing auth/artifacts can block the report without implying source absence.")
  return report


def packet_summary(title: str, packet: dict) -> str:
  jobs = packet.get("jobs") or []
  candidates = packet.get("candidates") or []
  s3_roots = packet_s3_roots(packet)
  test_records = packet_test_record_uris(packet)
  parts = [f"status `{packet.get('status')}`", f"jobs={len(jobs)}"]
  if candidates:
    parts.append(f"candidates={len(candidates)}")
  if s3_roots:
    parts.append(f"s3_roots={len(s3_roots)}")
  if test_records:
    parts.append(f"test_records={len(test_records)}")
  return f"{title}: " + "; ".join(parts) + "."


def remote_inventory_next_commands(packet: dict, original_source: str) -> list[str]:
  commands: list[str] = []
  for path in packet_local_zml_paths(packet)[:3]:
    commands.append(f"{CLI} fields {path} --fuzzy FIELD_OR_SIGNAL_NAME")
    commands.append(f"{CLI} extract {path} --topic TOPIC --field FIELD")

  original = original_source.rstrip("/")
  for root in packet_s3_roots(packet)[:3]:
    if root.rstrip("/") != original:
      commands.append(f"{CLI} inventory {root}")

  commands.append("Fetch/extract the selected GHA/S3 artifacts outside Phoenix Inspector, then run local-only log search; Phoenix Inspector has no remote download command.")
  commands.append(f"{CLI} search-logs /tmp/LOCAL_HIL_BUNDLE --query 'FAIL|Error|Traceback' --context 2")
  commands.append(f"{CLI} validators /tmp/LOCAL_HIL_BUNDLE")
  commands.append(f"{CLI} journal /tmp/LOCAL_HIL_BUNDLE")

  if packet_remote_zml_uris(packet) and not packet_local_zml_paths(packet):
    commands.append(f"{CLI} fields /tmp/LOCAL_RUN.zml.zst --fuzzy FIELD_OR_SIGNAL_NAME")

  if not packet_s3_roots(packet) and not (packet.get("jobs") or packet.get("candidates")):
    commands.append(f"{CLI} recent-hil --job-name HIL --conclusion failure --max-matches 5")

  for step in (packet.get("next_steps") or [])[:3]:
    commands.append(f"Packet next step: {step}")
  return unique(commands)


def packet_s3_roots(packet: dict) -> list[str]:
  roots: list[str] = []
  append_s3_roots(roots, packet.get("s3") or {})
  for job in packet.get("jobs") or []:
    append_s3_roots(roots, job.get("s3") or {})
  return unique(roots)


def append_s3_roots(roots: list[str], s3: dict) -> None:
  roots.extend(str(root) for root in s3.get("roots") or [] if root)
  for inventory in s3.get("inventories") or []:
    if inventory.get("s3_uri"):
      roots.append(str(inventory["s3_uri"]))


def packet_test_record_uris(packet: dict) -> list[str]:
  values: list[str] = []
  append_test_record_uris(values, packet.get("s3") or {}, packet.get("test_records") or [])
  for job in packet.get("jobs") or []:
    append_test_record_uris(values, job.get("s3") or {}, job.get("test_records") or [])
  return unique(values)


def append_test_record_uris(values: list[str], s3: dict, records: list[dict]) -> None:
  values.extend(str(uri) for uri in s3.get("test_record_uris") or [] if uri)
  for inventory in s3.get("inventories") or []:
    for artifact in inventory.get("test_record_artifacts") or []:
      if artifact.get("uri"):
        values.append(str(artifact["uri"]))
  for record in records:
    uri = record.get("s3_uri") or record.get("uri") or record.get("path")
    if uri:
      values.append(str(uri))


def packet_local_zml_paths(packet: dict) -> list[str]:
  return [value for value in packet_string_values(packet) if is_zml_path(value) and not is_remote_uri(value)]


def packet_remote_zml_uris(packet: dict) -> list[str]:
  return [value for value in packet_string_values(packet) if is_zml_path(value) and is_remote_uri(value)]


def packet_string_values(value: object) -> list[str]:
  if isinstance(value, dict):
    values: list[str] = []
    for item in value.values():
      values.extend(packet_string_values(item))
    return values
  if isinstance(value, list):
    values: list[str] = []
    for item in value:
      values.extend(packet_string_values(item))
    return values
  return [value] if isinstance(value, str) else []


def is_remote_uri(value: str) -> bool:
  return "://" in value


def is_zml_path(value: str) -> bool:
  lowered = value.lower().split("?", 1)[0]
  return lowered.endswith(".zml") or lowered.endswith(".zml.zst")


def unique(values: list[str]) -> list[str]:
  result = []
  seen: set[str] = set()
  for value in values:
    if value and value not in seen:
      seen.add(value)
      result.append(value)
  return result


def canonical_blocker(item: dict) -> Blocker:
  return Blocker(code=item.get("tool") or item.get("code") or "hil_blocker", category="backend_failure", severity="error", message=item.get("message") or str(item), source_ref=item.get("command") or item.get("source"), needed_action=item.get("guidance"))


def no_hil_evidence_blocker(packet: dict) -> Blocker:
  status = packet.get("status") or "no_hil_evidence"
  return Blocker(code=status, category="missing_artifact", severity="warning", message=f"HIL evidence wrapper returned `{status}` without usable job evidence.", source_ref=(packet.get("source") or {}).get("input"), needed_action="Broaden filters, provide an exact HIL job URL, or verify the expected HIL run exists before retrying.")
