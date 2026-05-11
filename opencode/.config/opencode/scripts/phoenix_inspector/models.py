from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION


JsonDict = dict[str, Any]


def utc_now() -> str:
  return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def compact(value: Any) -> Any:
  if dataclasses.is_dataclass(value):
    value = dataclasses.asdict(value)
  if isinstance(value, dict):
    return {key: compact(item) for key, item in value.items() if item not in (None, [], {}, ())}
  if isinstance(value, (list, tuple)):
    return [compact(item) for item in value if item not in (None, [], {}, ())]
  return value


@dataclass(frozen=True)
class ProvenanceRef:
  kind: str
  uri_or_path: str
  artifact_type: str | None = None
  selector: str | None = None
  time_window: str | None = None
  command: str | None = None
  supports: str | None = None
  does_not_prove: str | None = None

  def to_dict(self) -> JsonDict:
    return compact(self)


@dataclass(frozen=True)
class Blocker:
  code: str
  severity: str = "warning"
  category: str = "validation_gap"
  message: str = ""
  source_ref: str | None = None
  needed_action: str | None = None
  safe_to_retry: bool = True
  provenance: list[ProvenanceRef] = field(default_factory=list)

  def to_dict(self) -> JsonDict:
    return compact(self)


@dataclass(frozen=True)
class RunSource:
  raw: str
  source_type: str
  intent: str
  constraints: JsonDict = field(default_factory=dict)
  provenance: list[ProvenanceRef] = field(default_factory=list)

  def to_dict(self) -> JsonDict:
    return compact(self)


@dataclass(frozen=True)
class ResolvedSource:
  run_source: RunSource
  resolved_type: str
  root: str
  local_root: str | None = None
  remote_root: str | None = None
  metadata: JsonDict = field(default_factory=dict)
  preliminary_artifacts: list[ProvenanceRef] = field(default_factory=list)
  blockers: list[Blocker] = field(default_factory=list)
  provenance: list[ProvenanceRef] = field(default_factory=list)

  def to_dict(self) -> JsonDict:
    return compact(self)


@dataclass(frozen=True)
class ArtifactRecord:
  path: str
  artifact_type: str
  size: int | None = None
  mtime: str | None = None
  provenance: list[ProvenanceRef] = field(default_factory=list)

  def to_dict(self) -> JsonDict:
    return compact(self)


@dataclass(frozen=True)
class ArtifactInventory:
  source: ResolvedSource
  artifacts: list[ArtifactRecord] = field(default_factory=list)
  required_present: list[str] = field(default_factory=list)
  required_missing: list[str] = field(default_factory=list)
  optional_present: list[str] = field(default_factory=list)
  optional_missing: list[str] = field(default_factory=list)
  key_artifacts: JsonDict = field(default_factory=dict)
  zml_files: list[JsonDict] = field(default_factory=list)
  logs: list[JsonDict] = field(default_factory=list)
  test_record: JsonDict = field(default_factory=dict)
  baraza_context: JsonDict = field(default_factory=dict)
  generated_outputs: list[JsonDict] = field(default_factory=list)
  blockers: list[Blocker] = field(default_factory=list)

  def to_dict(self) -> JsonDict:
    return compact(self)


@dataclass(frozen=True)
class TimebaseRef:
  time_kind: str = "unknown"
  units: str = "unknown"
  origin: str = "unknown"
  observed_range: JsonDict = field(default_factory=dict)
  alignment_method: str = "not_aligned"
  alignment_confidence: str = "blocked"
  blockers: list[Blocker] = field(default_factory=list)

  def to_dict(self) -> JsonDict:
    return compact(self)


@dataclass(frozen=True)
class SignalRequest:
  source: JsonDict
  topics: list[str] = field(default_factory=list)
  fields: list[str] = field(default_factory=list)
  time_window: JsonDict = field(default_factory=dict)
  sample_limit: int | None = None
  backend_hint: str | None = None
  outputs: JsonDict = field(default_factory=dict)
  provenance: list[ProvenanceRef] = field(default_factory=list)

  def to_dict(self) -> JsonDict:
    return compact(self)


@dataclass(frozen=True)
class SignalResult:
  request: SignalRequest
  backend: str
  backend_capabilities: JsonDict = field(default_factory=dict)
  topics_found: list[str] = field(default_factory=list)
  fields_found: list[str] = field(default_factory=list)
  missing: list[JsonDict] = field(default_factory=list)
  records: list[JsonDict] = field(default_factory=list)
  timebase: TimebaseRef = field(default_factory=TimebaseRef)
  stats: JsonDict = field(default_factory=dict)
  output_paths: list[str] = field(default_factory=list)
  blockers: list[Blocker] = field(default_factory=list)
  provenance: list[ProvenanceRef] = field(default_factory=list)

  def to_dict(self) -> JsonDict:
    return compact(self)


@dataclass(frozen=True)
class CheckResult:
  name: str
  status: str
  summary: str
  details: JsonDict = field(default_factory=dict)
  thresholds: JsonDict = field(default_factory=dict)
  observed: JsonDict = field(default_factory=dict)
  provenance: list[ProvenanceRef] = field(default_factory=list)
  blockers: list[Blocker] = field(default_factory=list)

  def to_dict(self) -> JsonDict:
    return compact(self)


@dataclass(frozen=True)
class BatchTaxonomyRow:
  gha_url: str | None = None
  s3_root: str | None = None
  baraza: str | None = None
  test: str | None = None
  subtest: str | None = None
  conclusion: str | None = None
  failure_reason: str = "inconclusive"
  confidence: str = "low"
  blockers: list[str] = field(default_factory=list)
  evidence_status: str | None = None
  evidence_path: str | None = None
  evidence_summary: str | None = None
  report_path: str | None = None
  next_command: str | None = None

  def to_dict(self) -> JsonDict:
    return compact(self)


@dataclass
class EvidenceReport:
  title: str
  status: str = "ok"
  command: str | None = None
  exit_code: int | None = None
  schema_version: str = SCHEMA_VERSION
  generated_at: str = field(default_factory=utc_now)
  sources: list[ResolvedSource] = field(default_factory=list)
  inventories: list[ArtifactInventory] = field(default_factory=list)
  signal_results: list[SignalResult] = field(default_factory=list)
  check_results: list[CheckResult] = field(default_factory=list)
  evidence_table: list[JsonDict] = field(default_factory=list)
  summary: str = ""
  confidence: str = "low"
  proves: list[str] = field(default_factory=list)
  does_not_prove: list[str] = field(default_factory=list)
  blockers: list[Blocker] = field(default_factory=list)
  output_paths: list[str] = field(default_factory=list)
  next_commands: list[str] = field(default_factory=list)
  extra: JsonDict = field(default_factory=dict)

  def to_dict(self) -> JsonDict:
    data = compact(self)
    if self.exit_code is None:
      data.pop("exit_code", None)
    return data

  def write_json(self, path: Path) -> None:
    import json

    path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
