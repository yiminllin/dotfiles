from __future__ import annotations

import json
import os
from pathlib import Path

from .models import ArtifactInventory, ArtifactRecord, Blocker, ProvenanceRef, ResolvedSource
from .sources import safe_archive_members


GENERATED_MARKERS = ("phoenix_inspector", "inspector-report", "evidence-report")
REFUSED_DIRECTORY_ROOTS = {Path("/"), Path("/Systems"), Path.home()}
MAX_INVENTORY_FILES = 5000
MAX_INVENTORY_DIRS = 1000
MAX_INVENTORY_DEPTH = 12
MAX_INVENTORY_ENTRIES_PER_DIR = 2000


def build_inventory(source: ResolvedSource) -> ArtifactInventory:
  blockers = list(source.blockers)
  if source.resolved_type == "local_log_dir":
    return inventory_directory(source)
  if source.resolved_type in {"zml_file", "local_text_file"}:
    return inventory_file(source)
  if source.resolved_type == "hil_packet_json":
    return inventory_packet_json(source)
  if source.resolved_type == "archive":
    return inventory_archive(source)
  if source.resolved_type in {"gha_url", "s3_root", "unsupported_flight_id", "unknown"}:
    return ArtifactInventory(source=source, blockers=blockers)
  return ArtifactInventory(source=source, blockers=blockers)


def inventory_directory(source: ResolvedSource) -> ArtifactInventory:
  root = Path(source.root)
  blockers = []
  if not root.is_dir():
    blockers.append(Blocker("missing_path", "error", "missing_artifact", "Local source directory is not readable.", str(root), "Provide an existing directory."))
    return ArtifactInventory(source=source, blockers=blockers)
  if is_refused_directory(root):
    blockers.append(Blocker("broad_directory_refused", "error", "safety_boundary", "Refusing to recursively inventory a broad filesystem root.", str(root), "Provide a specific Phoenix log directory, bundle directory, or exact artifact path."))
    return ArtifactInventory(source=source, blockers=blockers)
  artifacts: list[ArtifactRecord] = []
  generated: list[dict] = []
  for path, walk_blocker in iter_files_bounded(root):
    if walk_blocker:
      blockers.append(walk_blocker)
      break
    relative = str(path.relative_to(root))
    record = artifact_record(path, classify_path(path, relative))
    if is_generated_output(relative):
      generated.append(record.to_dict())
    else:
      artifacts.append(record)
  artifacts.sort(key=lambda item: item.path)
  generated.sort(key=lambda item: item.get("path", ""))
  return inventory_from_artifacts(source, artifacts, generated, blockers)


def is_refused_directory(root: Path) -> bool:
  try:
    resolved = root.resolve()
  except OSError:
    resolved = root.absolute()
  return resolved in REFUSED_DIRECTORY_ROOTS


def iter_files_bounded(root: Path):
  seen_files = 0
  seen_dirs = 0
  stack: list[tuple[Path, int]] = [(root, 0)]
  while stack:
    directory, depth = stack.pop()
    seen_dirs += 1
    if seen_dirs > MAX_INVENTORY_DIRS:
      yield directory, Blocker("inventory_directory_limit", "warning", "safety_boundary", f"Inventory stopped after {MAX_INVENTORY_DIRS} directories to avoid broad scans.", str(root), "Provide a narrower source directory if the missing artifact is outside this report.")
      return
    try:
      entries = []
      with os.scandir(directory) as iterator:
        for index, entry in enumerate(iterator, start=1):
          if index > MAX_INVENTORY_ENTRIES_PER_DIR:
            yield directory, Blocker("inventory_directory_entry_limit", "warning", "safety_boundary", f"Inventory stopped after {MAX_INVENTORY_ENTRIES_PER_DIR} entries in one directory to avoid broad scans.", str(directory), "Provide a narrower source directory if the missing artifact is outside this report.")
            return
          entries.append(entry)
    except OSError as exc:
      yield directory, Blocker("inventory_walk_failed", "warning", "permission", f"Directory walk stopped: {exc}", str(directory), "Provide a readable, narrower Phoenix log directory if artifacts are missing.")
      continue
    child_dirs = []
    files = []
    for entry in entries:
      try:
        if entry.is_dir(follow_symlinks=False):
          child_dirs.append(Path(entry.path))
        elif entry.is_file(follow_symlinks=False):
          files.append(Path(entry.path))
      except OSError:
        continue
    for path in sorted(files):
      if seen_files >= MAX_INVENTORY_FILES:
        yield path, Blocker("inventory_item_limit", "warning", "safety_boundary", f"Inventory stopped after {MAX_INVENTORY_FILES} files to avoid broad scans.", str(root), "Provide a narrower source directory if the missing artifact is outside this report.")
        return
      seen_files += 1
      yield path, None
    if depth < MAX_INVENTORY_DEPTH:
      stack.extend((path, depth + 1) for path in sorted(child_dirs, reverse=True))


def inventory_file(source: ResolvedSource) -> ArtifactInventory:
  path = Path(source.root)
  blockers = [] if path.is_file() else [Blocker("missing_path", "error", "missing_artifact", "Local ZML file is not readable.", str(path), "Provide an existing .zml or .zml.zst file.")]
  artifacts = [artifact_record(path, classify_path(path, path.name))] if path.is_file() else []
  return inventory_from_artifacts(source, artifacts, [], blockers)


def inventory_packet_json(source: ResolvedSource) -> ArtifactInventory:
  path = Path(source.root)
  artifacts = [artifact_record(path, "hil_packet_json")] if path.is_file() else []
  blockers = []
  packet: dict = {}
  try:
    packet = json.loads(path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError) as exc:
    blockers.append(Blocker("packet_parse_failed", "error", "decode_failure", f"Packet JSON could not be parsed: {exc}", str(path), "Provide a valid HIL evidence packet or test_record.json."))
  inventory = inventory_from_artifacts(source, artifacts, [], blockers)
  if packet:
    inventory = ArtifactInventory(
      source=inventory.source,
      artifacts=inventory.artifacts,
      required_present=inventory.required_present,
      required_missing=inventory.required_missing,
      optional_present=inventory.optional_present,
      optional_missing=inventory.optional_missing,
      key_artifacts=embedded_key_artifacts(packet),
      zml_files=inventory.zml_files,
      logs=inventory.logs,
      test_record=summarize_test_record(packet),
      baraza_context=embedded_baraza(packet),
      generated_outputs=inventory.generated_outputs,
      blockers=inventory.blockers,
    )
  return inventory


def inventory_archive(source: ResolvedSource) -> ArtifactInventory:
  path = Path(source.root)
  blockers = []
  artifacts = [artifact_record(path, "archive")] if path.is_file() else []
  members, archive_blockers = safe_archive_members(path)
  blockers.extend(archive_blockers)
  for member in members:
    artifacts.append(ArtifactRecord(path=f"{path}!/{member}", artifact_type=classify_name(member), provenance=[ProvenanceRef("file", str(path), "archive_member", selector=member)]))
  return inventory_from_artifacts(source, artifacts, [], blockers)


def inventory_from_artifacts(source: ResolvedSource, artifacts: list[ArtifactRecord], generated: list[dict], blockers: list[Blocker]) -> ArtifactInventory:
  zml_files = [zml_metadata(record) for record in artifacts if record.artifact_type in {"zml", "zml_zst"}]
  logs = [record.to_dict() for record in artifacts if record.artifact_type in {"phoenix_log", "journal", "test_log", "validator_output", "alarm_output"}]
  present = sorted({record.artifact_type for record in artifacts})
  required_missing = [] if artifacts else ["source_artifacts"]
  return ArtifactInventory(
    source=source,
    artifacts=artifacts,
    required_present=[name for name in ("test_record", "zml", "zml_zst", "phoenix_log") if name in present],
    required_missing=required_missing,
    optional_present=present,
    key_artifacts=group_key_artifacts(artifacts),
    zml_files=zml_files,
    logs=logs,
    generated_outputs=generated,
    blockers=blockers,
  )


def artifact_record(path: Path, artifact_type: str) -> ArtifactRecord:
  stat = path.stat()
  return ArtifactRecord(path=str(path), artifact_type=artifact_type, size=stat.st_size, mtime=str(int(stat.st_mtime)), provenance=[ProvenanceRef("file", str(path), artifact_type=safe_name(artifact_type))])


def classify_path(path: Path, relative: str) -> str:
  if path.name == "test_record.json":
    return "test_record"
  return classify_name(relative)


def classify_name(name: str) -> str:
  lower = name.lower()
  base = Path(lower).name
  if lower.endswith(".zml.zst"):
    return "zml_zst"
  if lower.endswith(".zml"):
    return "zml"
  if lower.endswith("phoenix.log") or lower == "phoenix.log":
    return "phoenix_log"
  if "validator" in lower:
    return "validator_output"
  if "journal" in lower or "journalctl" in lower or "process_status" in lower or base in {"system.log", "syslog"}:
    return "journal"
  if base.startswith("test_log_") and lower.endswith(".log"):
    return "test_log"
  if "alarm" in lower:
    return "alarm_output"
  if lower.endswith((".zip", ".tar", ".tgz", ".tar.gz", ".tar.zst")):
    return "archive"
  return "other"


def is_generated_output(relative: str) -> bool:
  lower = relative.lower()
  return any(marker in lower for marker in GENERATED_MARKERS) or lower.startswith("reports/")


def group_key_artifacts(artifacts: list[ArtifactRecord]) -> dict[str, list[dict]]:
  grouped: dict[str, list[dict]] = {}
  for record in artifacts:
    if record.artifact_type == "other":
      continue
    grouped.setdefault(record.artifact_type, []).append(record.to_dict())
  return grouped


def zml_metadata(record: ArtifactRecord) -> dict:
  return {"path": record.path, "compression": "zst" if record.artifact_type == "zml_zst" else "none", "size": record.size}


def summarize_test_record(packet: dict) -> dict:
  test_info = packet.get("test_info") if isinstance(packet.get("test_info"), dict) else {}
  records = packet.get("test_records") if isinstance(packet.get("test_records"), list) else []
  if test_info:
    return {"source": "embedded", "test_info": test_info}
  if records:
    first = records[0] if isinstance(records[0], dict) else {}
    return {"source": "embedded", "count": len(records), "first": first}
  return {}


def embedded_key_artifacts(packet: dict) -> dict:
  key_artifacts: dict[str, list[dict]] = {}
  for job in packet.get("jobs") or []:
    s3 = job.get("s3") if isinstance(job, dict) else None
    for inventory in (s3 or {}).get("inventories") or []:
      for hint in inventory.get("key_artifact_hints") or []:
        key_artifacts.setdefault(hint.get("category") or "artifact", []).append(hint)
  for uri in (packet.get("s3") or {}).get("test_record_uris") or []:
    key_artifacts.setdefault("test_record", []).append({"uri": uri, "source": "embedded"})
  return key_artifacts


def embedded_baraza(packet: dict) -> dict:
  for job in packet.get("jobs") or []:
    s3 = job.get("s3") if isinstance(job, dict) else None
    baraza = (s3 or {}).get("baraza")
    if baraza:
      return {"source": "embedded", **baraza}
  return {}


def safe_name(value: str) -> str:
  return value.replace("_", "-")
