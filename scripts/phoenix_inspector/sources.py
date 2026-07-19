from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Blocker, ProvenanceRef, ResolvedSource, RunSource


GHA_RE = re.compile(r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/runs/(?P<run_id>\d+)(?:/job/(?P<job_id>\d+))?")
FLIGHT_ID_RE = re.compile(r"^(?:P2M|P2F)_[A-Za-z0-9]+$")
ARCHIVE_SUFFIXES = (".zip", ".tar", ".tgz", ".tar.gz", ".tar.zst")


def run_source(raw: str, intent: str, constraints: dict | None = None) -> RunSource:
  return RunSource(
    raw=raw,
    source_type=detect_source_type(raw),
    intent=intent,
    constraints=constraints or {},
    provenance=[ProvenanceRef(kind="command", uri_or_path="argv", selector=raw, supports="user-provided source")],
  )


def detect_source_type(raw: str) -> str:
  if GHA_RE.match(raw):
    return "gha_url"
  if raw.startswith("s3://"):
    return "s3_root"
  if FLIGHT_ID_RE.match(raw):
    return "unsupported_flight_id"
  path = Path(raw).expanduser()
  if path.exists():
    if path.is_dir():
      return "local_log_dir"
    if raw.endswith((".zml", ".zml.zst")):
      return "zml_file"
    if is_archive_path(raw):
      return "unsupported_archive"
    if path.name == "test_record.json" or (path.suffix == ".json" and looks_like_packet(path)):
      return "unsupported_packet_json"
    return "local_text_file"
  if raw.endswith((".zml", ".zml.zst")):
    return "zml_file"
  if is_archive_path(raw):
    return "unsupported_archive"
  if path.name == "test_record.json":
    return "unsupported_packet_json"
  return "unknown"


def is_archive_path(raw: str) -> bool:
  return raw.endswith(ARCHIVE_SUFFIXES)


def looks_like_packet(path: Path) -> bool:
  try:
    value = json.loads(path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError):
    return False
  if not isinstance(value, dict):
    return False
  return any(key in value for key in ("mode", "github", "jobs", "s3", "test_records", "test_info"))


def resolve_source(raw: str, intent: str, constraints: dict | None = None) -> ResolvedSource:
  source = run_source(raw, intent, constraints)
  provenance = [ProvenanceRef(kind="note", uri_or_path=raw, supports=f"detected {source.source_type}")]
  if source.source_type == "gha_url":
    match = GHA_RE.match(raw)
    metadata = {"repo": f"{match.group('owner')}/{match.group('repo')}", "run_id": match.group("run_id")} if match else {}
    if match and match.group("job_id"):
      metadata["job_id"] = match.group("job_id")
    return ResolvedSource(source, "gha_url", raw, remote_root=raw, metadata=metadata, provenance=provenance)
  if source.source_type == "s3_root":
    bucket_prefix = raw[5:].split("/", 1)
    metadata = {"bucket": bucket_prefix[0], "prefix": bucket_prefix[1] if len(bucket_prefix) > 1 else ""}
    blockers = []
    if not metadata["prefix"].strip("/"):
      blockers.append(Blocker("s3_bucket_root_refused", "error", "safety_boundary", "Refusing to recursively inventory an S3 bucket root without an explicit prefix.", raw, "Provide a narrow s3://bucket/prefix/ source or a GHA run/job URL that can identify selected artifact roots."))
    return ResolvedSource(source, "s3_root", raw, remote_root=raw, metadata=metadata, blockers=blockers, provenance=provenance)
  if source.source_type == "unsupported_flight_id":
    blocker = Blocker(
      code="future_source_adapter",
      category="unsupported_source",
      message="Flight IDs are not default v1 sources; provide an explicit supported source.",
      source_ref=raw,
      needed_action="Use a local Phoenix log/extracted bundle directory, local ZML/ZST file, GHA run/job URL, or non-root S3 prefix.",
    )
    return ResolvedSource(source, "unsupported_flight_id", raw, metadata={"flight_or_mission_id": raw}, blockers=[blocker], provenance=provenance)
  path = Path(raw).expanduser()
  if source.source_type == "unsupported_packet_json":
    blocker = Blocker(
      code="unsupported_packet_json_source",
      category="unsupported_source",
      message="Packet/test_record JSON files are no longer supported as standalone inventory sources.",
      source_ref=raw,
      needed_action="Provide the containing extracted Phoenix log/bundle directory, a local ZML/ZST file, GHA run/job URL, or non-root S3 prefix.",
    )
    return ResolvedSource(source, "unsupported_packet_json", raw, local_root=str(path), blockers=[blocker], provenance=provenance)
  if source.source_type == "unsupported_archive":
    blocker = Blocker(
      code="unsupported_archive_source",
      category="unsupported_source",
      message="Archive files are no longer supported as standalone inventory sources.",
      source_ref=raw,
      needed_action="Extract the archive first and provide the resulting Phoenix log/bundle directory, or provide a local ZML/ZST file, GHA run/job URL, or non-root S3 prefix.",
    )
    return ResolvedSource(source, "unsupported_archive", raw, local_root=str(path), blockers=[blocker], provenance=provenance)
  if source.source_type in {"local_log_dir", "local_text_file", "zml_file"}:
    return ResolvedSource(source, source.source_type, str(path), local_root=str(path), provenance=provenance)
  blocker = Blocker(
    code="unsupported_source",
    category="unsupported_source",
    message="Source is not a supported Phoenix inspector source.",
    source_ref=raw,
    needed_action="Provide a GHA run/job URL, non-root s3:// prefix, local Phoenix log/extracted bundle directory, or local .zml/.zml.zst file.",
  )
  return ResolvedSource(source, "unknown", raw, blockers=[blocker], provenance=provenance)
