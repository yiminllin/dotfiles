from __future__ import annotations

from typing import Any

from hil_evidence.packet import build_recent_packet, build_summary_packet
from hil_evidence.sync import build_sync_check

from .inventory import build_inventory
from .models import Blocker, CheckResult, EvidenceReport
from .sources import resolve_source

CLI = 'python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py"'


def inventory_remote_report(source: str, args: Any) -> EvidenceReport:
  resolved = resolve_source(source, "inventory", {"preset": getattr(args, "preset", None), "passing": getattr(args, "passing", False)})
  if any(blocker.category == "safety_boundary" for blocker in resolved.blockers):
    return EvidenceReport(title="HIL/GHA Inventory", status="blocked", sources=[resolved], blockers=resolved.blockers, summary="Remote inventory blocked by source safety boundary before any external listing.", confidence="blocked")
  try:
    packet = build_summary_packet(source, preset=getattr(args, "preset", None), passing=getattr(args, "passing", False), max_inventory_items=getattr(args, "max_inventory_items", 500), max_test_records=getattr(args, "max_test_records", 20))
  except Exception as exc:
    blocker = Blocker("hil_evidence_failed", "error", "backend_failure", f"HIL evidence wrapper failed: {exc}", source, "Run read-only auth/tool checks, then retry the exact same source.")
    return EvidenceReport(title="HIL/GHA Inventory", status="blocked", sources=[resolved], blockers=[blocker], summary="HIL/GHA inventory blocked before exact source resolution completed.", confidence="blocked")
  return packet_report("HIL/GHA Inventory", packet, [resolved])


def recent_hil_report(args: Any) -> EvidenceReport:
  try:
    packet = build_recent_packet(preset=args.preset, passing=args.passing, max_matches=args.max_matches, limit=args.limit, lookback_hours=args.lookback_hours, job_name=args.job_name, title=args.title, branch=args.branch, status=args.status or [], conclusion=args.conclusion or [], test_record_query=args.test_record_query)
  except Exception as exc:
    blocker = Blocker("recent_hil_failed", "error", "backend_failure", f"Recent HIL wrapper failed: {exc}", needed_action="Ensure gh/aws credentials already exist; do not run interactive auth from phoenix_inspector.")
    return EvidenceReport(title="Recent HIL Sources", status="blocked", blockers=[blocker], summary="Recent HIL discovery blocked.", confidence="blocked")
  report = packet_report("Recent HIL Sources", packet, [])
  report.next_commands.extend([f"{CLI} inventory {candidate.get('gha_url')}" for candidate in packet.get("candidates") or [] if candidate.get("gha_url")][:5])
  return report


def sync_check_report(args: Any) -> EvidenceReport:
  systems_root = getattr(args, "systems_root", None) or getattr(args, "source", None) or "/Systems"
  packet = build_sync_check(systems_root)
  blockers = [Blocker("hil_sync_blocker", "warning", "missing_artifact", item.get("message", str(item)), item.get("path"), item.get("guidance")) for item in packet.get("blockers") or []]
  status = "ok" if packet.get("status") == "ok" else "blocked"
  check = CheckResult("hil-preset-sync", "pass" if status == "ok" else "blocked", f"sync-check status: {packet.get('status')}", observed=packet.get("counts") or {}, blockers=blockers)
  return EvidenceReport(title="HIL Sync Check", status=status, check_results=[check], blockers=blockers, summary=f"HIL sync-check status `{packet.get('status')}` for systems root `{systems_root}`.", confidence="medium" if status == "ok" else "blocked", extra={"legacy_packet": packet})


def packet_report(title: str, packet: dict, sources: list) -> EvidenceReport:
  blockers = [canonical_blocker(item) for item in (packet.get("blockers") or []) + (packet.get("errors") or [])]
  if packet.get("status") in {"no_matches", "no_hil_jobs"}:
    blockers.append(no_hil_evidence_blocker(packet))
  status = "blocked" if packet.get("status") in {"error", "blocked", "no_matches", "no_hil_jobs"} or blockers else "partial" if packet.get("status") == "partial" else "ok"
  report = EvidenceReport(title=title, status=status, sources=sources, blockers=blockers, summary=f"{title}: legacy wrapper status `{packet.get('status')}`.", confidence="medium" if status == "ok" else "blocked", extra={"legacy_packet": packet})
  report.evidence_table.append({"finding": title, "source_ref": (packet.get("source") or {}).get("input"), "supports": "Existing HIL evidence behavior was normalized into a canonical report.", "does_not_prove": "Does not independently prove root cause."})
  report.proves.append("Exact source was passed to the HIL wrapper; no recent-run substitution is performed by this command.")
  report.does_not_prove.append("Missing auth/artifacts can block the report without implying source absence.")
  return report


def canonical_blocker(item: dict) -> Blocker:
  return Blocker(code=item.get("tool") or item.get("code") or "hil_blocker", category="backend_failure", severity="error", message=item.get("message") or str(item), source_ref=item.get("command") or item.get("source"), needed_action=item.get("guidance"))


def no_hil_evidence_blocker(packet: dict) -> Blocker:
  status = packet.get("status") or "no_hil_evidence"
  return Blocker(code=status, category="missing_artifact", severity="warning", message=f"HIL evidence wrapper returned `{status}` without usable job evidence.", source_ref=(packet.get("source") or {}).get("input"), needed_action="Broaden filters, provide an exact HIL job URL, or verify the expected HIL run exists before retrying.")
