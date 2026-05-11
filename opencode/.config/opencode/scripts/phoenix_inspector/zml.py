from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path
from typing import Any

from zml_audit.extract import parse_samples
from zml_audit.models import TimeWindow, TopicSpec
from zml_audit.presets import PRESETS as LEGACY_PRESETS
from zml_audit.presets import expand_specs
from zml_audit.topics import fuzzy_topic_matches
from zml_signal_audit import build_audit_packet, build_compare_packet, build_fields_packet, build_topics_packet
from zml_audit.backends import resolve_systems_root

from .models import Blocker, EvidenceReport, SignalRequest, SignalResult, TimebaseRef
from .sources import resolve_source


BACKEND_CHOICES = ("auto", "zml-conv", "zml-cli", "local-text")
CLI = 'python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py"'
REFUSED_ZML_DIRS = {Path("/"), Path("/Systems"), Path.home(), Path("/home"), Path("/tmp")}
MAX_ZML_DISCOVERY_DEPTH = 12
MAX_ZML_DISCOVERY_DIRS = 1000
MAX_ZML_DISCOVERY_FILES = 5000
MAX_ZML_DISCOVERY_ENTRIES_PER_DIR = 2000


def window_from_args(args: Any) -> TimeWindow:
  from zml_signal_audit import build_window

  return build_window(args)


def specs_from_args(topic: list[str] | None, field: list[str] | None, preset: str | None) -> list[TopicSpec]:
  if preset and preset not in LEGACY_PRESETS:
    raise ValueError(f"unknown preset: {preset}")
  return expand_specs(topic or [], field or [], preset)


def default_systems_root() -> str | None:
  return resolve_systems_root()


def topics_report(source: str, pattern: str | None, backend: str, systems_root: str | None, output_format: str, fuzzy: str | None = None, limit: int = 20) -> EvidenceReport:
  systems_root = resolve_systems_root(systems_root)
  resolved = resolve_source(source, "topics", {"pattern": pattern, "fuzzy": fuzzy, "limit": limit if fuzzy else None, "backend": backend, "systems_root": systems_root})
  if blocker := guard_zml_source(source):
    return zml_packet_report("ZML Topics", blocked_zml_packet("topics", source, blocker), [resolved], output_format)
  if backend == "local-text" or should_use_local_text(source, backend, systems_root, "topics"):
    packet = local_text_topics_packet(source, pattern, fuzzy, limit)
  else:
    packet = build_topics_packet(source, [pattern] if pattern else [], [], zml=backend_adapter(backend, systems_root), fuzzy=fuzzy, limit=limit, backend_name=backend, systems_root=systems_root)
  return zml_packet_report("ZML Topics", packet, [resolved], output_format)


def fields_report(args: Any) -> EvidenceReport:
  args.systems_root = resolve_systems_root(args.systems_root)
  resolved = resolve_source(args.source, "fields", {"fuzzy": args.fuzzy, "topic": args.topic, "topic_fuzzy": args.topic_fuzzy, "backend": args.backend, "systems_root": args.systems_root})
  if blocker := guard_zml_source(args.source):
    return zml_packet_report("ZML Field Discovery", blocked_zml_packet("fields", args.source, blocker), [resolved], args.format)
  if args.backend == "local-text" or should_use_local_text(args.source, args.backend, args.systems_root, "fields"):
    selected_backend = "local-text"
  else:
    selected_backend = args.backend
  packet = build_fields_packet(
    args.source,
    fuzzy=args.fuzzy,
    topic=args.topic or [],
    topic_contains=args.topic_contains or [],
    topic_regex=args.topic_regex or [],
    topic_fuzzy=args.topic_fuzzy,
    sample_limit=args.sample_limit,
    limit=args.limit,
    max_topics_sampled=args.max_topics_sampled,
    max_topics=getattr(args, "max_topics", 500),
    sample_top=getattr(args, "sample_top", 0),
    no_sample=getattr(args, "no_sample", False),
    max_fields_per_topic=args.max_fields_per_topic,
    max_zmls=getattr(args, "max_zmls", 200),
    max_workers=getattr(args, "workers", 1),
    zml=backend_adapter(selected_backend, args.systems_root),
    backend_name=selected_backend,
    systems_root=args.systems_root,
  )
  return zml_packet_report("ZML Field Discovery", packet, [resolved], args.format)


def extract_report(args: Any) -> EvidenceReport:
  args.systems_root = resolve_systems_root(args.systems_root)
  resolved = resolve_source(args.source, "extract", {"topic": args.topic, "field": args.field, "backend": args.backend, "systems_root": args.systems_root})
  if blocker := guard_zml_source(args.source):
    return zml_packet_report("ZML Extract", blocked_zml_packet("audit", args.source, blocker), [resolved], args.format)
  specs = specs_from_args([args.topic], args.field or [], None)
  window = window_from_args(args)
  if args.backend == "local-text" or should_use_local_text(args.source, args.backend, args.systems_root, "extract"):
    packet = local_text_audit_packet(args.source, specs, window, include_samples=True)
  else:
    packet = build_audit_packet(args.source, specs, window, zml=backend_adapter(args.backend, args.systems_root), include_samples=bool(args.csv), backend_name=args.backend, direct_known_extract=True, systems_root=args.systems_root)
  output_paths = []
  if args.csv:
    write_csv_from_packet(packet, args.csv)
    output_paths.append(args.csv)
  report = zml_packet_report("ZML Extract", packet, [resolved], args.format)
  report.output_paths.extend(output_paths)
  if args.plot or args.plot_dir:
    blocker = Blocker("plot_backend_unavailable", "warning", "backend_failure", "Static plot generation is not backed by an available dependency in this environment; CSV extraction is preserved.", args.plot or args.plot_dir, "Use the CSV output for plotting or add a reviewed optional plot backend.")
    report.blockers.append(blocker)
    report.status = "partial" if report.status == "ok" else report.status
  report.next_commands.append(f"{CLI} compare --fail FAIL --pass PASS --topic {args.topic} --field {','.join(args.field or [])}")
  return report


def compare_report(args: Any) -> EvidenceReport:
  args.systems_root = resolve_systems_root(args.systems_root)
  topic_values = [args.topic] if args.topic else []
  field_values = args.field or []
  specs = specs_from_args(topic_values, field_values, args.preset)
  if not specs and args.spec:
    specs = specs_from_spec(args.spec)
  if not specs:
    sources = [resolve_source(args.fail, "compare", {"side": "fail"}), resolve_source(args.pass_source, "compare", {"side": "pass"})]
    blocker = Blocker("compare_has_no_signal_selection", "warning", "validation_gap", "Compare needs executable topic/field, preset, or spec operations.", needed_action="Use --topic with --field, --preset, or a --spec containing compare/extract operations.")
    return EvidenceReport(title="Pass/Fail ZML Compare", status="blocked", sources=sources, blockers=[blocker], summary="Compare is blocked because no executable signal selection was declared.", confidence="blocked", does_not_prove=["An empty compare request does not prove absence or presence of the fault."])
  window = window_from_args(args)
  for path in (args.fail, args.pass_source):
    if blocker := guard_zml_source(path):
      sources = [resolve_source(args.fail, "compare", {"side": "fail"}), resolve_source(args.pass_source, "compare", {"side": "pass"})]
      return zml_packet_report("Pass/Fail ZML Compare", {"schema_version": 1, "mode": "compare", "status": "blocked", "sources": [{"input": args.fail}, {"input": args.pass_source}], "comparison": {}, "blockers": [blocker]}, sources, args.format)
  use_text = args.backend == "local-text" or should_use_local_text(args.fail, args.backend, args.systems_root, "compare") or should_use_local_text(args.pass_source, args.backend, args.systems_root, "compare")
  if use_text:
    packet = local_text_compare_packet(args.fail, args.pass_source, specs, window, args.time_tolerance, args.numeric_tolerance)
  else:
    packet = build_compare_packet(args.fail, args.pass_source, specs, window, zml=backend_adapter(args.backend, args.systems_root), time_tolerance=args.time_tolerance, numeric_tolerance=args.numeric_tolerance, include_samples=bool(args.csv), backend_name=args.backend, systems_root=args.systems_root)
  sources = [resolve_source(args.fail, "compare", {"side": "fail"}), resolve_source(args.pass_source, "compare", {"side": "pass"})]
  report = zml_packet_report("Pass/Fail ZML Compare", packet, sources, args.format)
  if args.csv:
    write_compare_csv(packet, args.csv)
    report.output_paths.append(args.csv)
  report.confidence = "medium" if packet.get("status") == "ok" else "blocked"
  report.does_not_prove.append("A signal delta is not causal proof without source, timebase, and log corroboration.")
  report.next_commands.append(f"{CLI} fields <source> --fuzzy FIELD_OR_SIGNAL_NAME")
  report.next_commands.append(f"{CLI} spec init --name my-question --from-last-run")
  return report


class AutoBackend:
  name = "auto"

  def __init__(self, systems_root: str | None) -> None:
    from zml_audit.backends import ZmlCliBackend

    self.systems_root = resolve_systems_root(systems_root)
    self.backends = [SafeZmlConvBackend(self.systems_root, prefer_bazel=bool(self.systems_root)), ZmlCliBackend()]
    self._availability_cache: dict[str, object | None] = {}
    self._field_metadata_blocker = None

  def list_topics(self, path: str):
    return self._first(path, "list_topics", lambda backend: getattr(backend, "name") != "zml-conv")

  def field_metadata(self, path: str):
    if self._field_metadata_blocker is not None:
      from zml_audit.backends import BackendResult

      metadata = {**self._field_metadata_blocker.metadata, "cached_unavailable": True}
      return BackendResult(blocker=self._field_metadata_blocker.blocker, backend=self._field_metadata_blocker.backend, metadata=metadata)
    result = self._first(path, "field_metadata", lambda backend: callable(getattr(backend, "field_metadata", None)))
    if result.blocker and result.metadata.get("unsupported_operation"):
      self._field_metadata_blocker = result
    return result

  def read_topic(self, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...] = ()):
    return self._first(path, "read_topic", lambda backend: True, topic, window, tuple(fields))

  def _first(self, path: str, method: str, supports, *args):
    from zml_audit.backends import BackendResult

    blockers = []
    raw_backend = None
    for backend in self.backends:
      name = getattr(backend, "name", backend.__class__.__name__)
      if not supports(backend):
        blockers.append({"backend": name, "reason": "unsupported_operation"})
        continue
      if blocker := self._unavailable_backend_blocker(name, backend):
        blockers.append({"backend": name, "reason": blocker.message})
        continue
      if method == "read_topic" and hasattr(backend, "read_topic_raw_decoded"):
        raw_backend = backend
      result = getattr(backend, method)(path, *args)
      if result.blocker:
        blockers.append({"backend": name, "reason": result.blocker.message})
        continue
      result.metadata["requested"] = "auto"
      result.metadata["fallbacks"] = blockers
      return result
    if method == "read_topic" and raw_backend is not None and len(args) >= 3 and args[2]:
      topic, window, fields = args[0], args[1], args[2]
      result = raw_backend.read_topic_raw_decoded(path, topic, window, fields)
      result.metadata["requested"] = "auto"
      result.metadata["decoded_failures"] = blockers
      return result
    return BackendResult(blocker=legacy_blocker("auto", "No ZML backend succeeded in order zml-conv -> zml-cli", json.dumps(blockers)), backend="auto", metadata={"requested": "auto", "fallbacks": blockers})

  def _unavailable_backend_blocker(self, name: str, backend: object):
    if name in self._availability_cache:
      return self._availability_cache[name]
    blocker = None
    available_blocker = getattr(backend, "available_blocker", None)
    if callable(available_blocker):
      blocker = available_blocker()
    else:
      available_command = getattr(backend, "available_command", None)
      if callable(available_command):
        result = available_command()
        blocker = result[-1] if isinstance(result, tuple) else None
    self._availability_cache[name] = blocker
    return blocker


def backend_adapter(name: str, systems_root: str | None):
  from zml_audit.backends import ZmlCliBackend

  systems_root = resolve_systems_root(systems_root)
  if name == "auto":
    return AutoBackend(systems_root)
  if name == "zml-cli":
    return ZmlCliBackend()
  if name == "zml-conv":
    return SafeZmlConvBackend(systems_root)
  if name == "local-text":
    return LocalTextBackend()
  raise ValueError(f"unsupported backend: {name}")


class SafeZmlConvBackend:
  name = "zml-conv"

  def __init__(self, systems_root: str | None = None, timeout_seconds: float = 60.0, prefer_bazel: bool = False) -> None:
    from zml_audit.backends import ZmlConvBackend

    self.backend = ZmlConvBackend(timeout_seconds=timeout_seconds, systems_root=systems_root, prefer_bazel=prefer_bazel)

  def available_command(self):
    return self.backend.available_command()

  def list_topics(self, path: str):
    return self.backend.list_topics(path)

  def read_topic(self, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...] = ()):
    return self.backend.read_topic(path, topic, window, fields)


class LocalTextBackend:
  name = "local-text"

  def list_topics(self, path: str):
    from zml_audit.backends import BackendResult

    topics = sorted({sample.topic for sample in parse_samples(Path(path).read_text(encoding="utf-8"))})
    return BackendResult(stdout="\n".join(topics) + ("\n" if topics else ""), backend=self.name, metadata={"selected": self.name, "operation": "list topics"})

  def read_topic(self, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...] = ()):
    from zml_audit.backends import BackendResult

    samples = [sample.to_dict() for sample in parse_samples(Path(path).read_text(encoding="utf-8")) if sample.topic == topic and window.normalized().contains(sample.timestamp)]
    return BackendResult(stdout="\n".join(json.dumps(sample) for sample in samples), backend=self.name, metadata={"selected": self.name, "operation": "read topic"})


def should_use_local_text(path: str, backend: str, systems_root: str | None, operation: str) -> bool:
  if backend != "auto":
    return False
  if shutil.which("zml_conv") or shutil.which("zml-conv") or shutil.which("zml"):
    return False
  try:
    return bool(parse_samples(Path(path).read_text(encoding="utf-8")))
  except (OSError, UnicodeDecodeError):
    return False


def guard_zml_source(raw: str) -> dict | None:
  if raw.startswith(("s3://", "http://", "https://")):
    return None
  path = Path(raw).expanduser()
  if not path.exists() or path.is_file():
    return None
  if not path.is_dir():
    return {"tool": "source", "message": f"unsupported ZML source path type: {path}", "guidance": "Pass an exact .zml/.zml.zst file or a bounded log directory."}
  resolved = safe_resolve(path)
  if resolved in REFUSED_ZML_DIRS:
    return {"tool": "source", "message": f"refusing broad ZML directory source: {resolved}", "guidance": "Pass an exact .zml/.zml.zst file or a narrower Phoenix log directory."}
  blocker = bounded_zml_directory_blocker(path)
  if blocker:
    return blocker
  return None


def bounded_zml_directory_blocker(root: Path) -> dict | None:
  seen_dirs = 0
  seen_files = 0
  stack: list[tuple[Path, int]] = [(root, 0)]
  while stack:
    directory, depth = stack.pop()
    seen_dirs += 1
    if seen_dirs > MAX_ZML_DISCOVERY_DIRS:
      return {"tool": "source", "message": f"refusing ZML directory after {MAX_ZML_DISCOVERY_DIRS} directories", "guidance": "Pass a narrower log directory or exact ZML file."}
    try:
      entries = []
      with os.scandir(directory) as iterator:
        for index, entry in enumerate(iterator, start=1):
          if index > MAX_ZML_DISCOVERY_ENTRIES_PER_DIR:
            return {"tool": "source", "message": f"refusing ZML directory with more than {MAX_ZML_DISCOVERY_ENTRIES_PER_DIR} entries in {directory}", "guidance": "Pass a narrower log directory or exact ZML file."}
          entries.append(entry)
    except OSError as exc:
      return {"tool": "source", "message": f"could not safely scan ZML directory {directory}: {exc}", "guidance": "Pass a readable narrower log directory or exact ZML file."}
    child_dirs: list[Path] = []
    for entry in entries:
      try:
        if entry.is_dir(follow_symlinks=False):
          child_dirs.append(Path(entry.path))
        elif entry.is_file(follow_symlinks=False):
          seen_files += 1
          if seen_files > MAX_ZML_DISCOVERY_FILES:
            return {"tool": "source", "message": f"refusing ZML directory after {MAX_ZML_DISCOVERY_FILES} files", "guidance": "Pass a narrower log directory or exact ZML file."}
      except OSError:
        continue
    if depth < MAX_ZML_DISCOVERY_DEPTH:
      stack.extend((path, depth + 1) for path in child_dirs)
  return None


def safe_resolve(path: Path) -> Path:
  try:
    return path.resolve()
  except OSError:
    return path.absolute()


def local_text_topics_packet(path: str, pattern: str | None, fuzzy: str | None = None, limit: int = 20) -> dict:
  text, blocker = read_text_source(path)
  if blocker:
    return blocked_zml_packet("topics", path, blocker)
  samples = parse_samples(text)
  topics = sorted({sample.topic for sample in samples if not pattern or pattern in sample.topic})
  file_result: dict = {"path": path, "topics": topics, "topic_count": len(topics), "backend": {"selected": "local-text"}}
  if fuzzy:
    matches = fuzzy_topic_matches(topics, fuzzy, limit)
    file_result["topics"] = [match.topic for match in matches]
    file_result["topic_count"] = len(matches)
    file_result["topic_matches"] = [match.to_dict() for match in matches]
  return {"schema_version": 1, "generated_at": None, "mode": "topics", "status": "ok", "query": {"pattern": pattern, "fuzzy": fuzzy, "limit": limit if fuzzy else None, "backend": {"selected": "local-text"}}, "source": {"input": path, "kind": "file", "candidates": [path]}, "files": [file_result], "blockers": []}


def local_text_audit_packet(path: str, specs: list[TopicSpec], window: TimeWindow, include_samples: bool = False) -> dict:
  from zml_audit.stats import summarize_topic

  wanted_fields = tuple(sorted({field for spec in specs for field in spec.fields}))
  text, blocker = read_text_source(path)
  if blocker:
    return blocked_zml_packet("audit", path, blocker)
  samples = parse_samples(text, fields=wanted_fields)
  topics = []
  for spec in specs:
    selected = [sample for sample in samples if sample.topic == spec.name and window.normalized().contains(sample.timestamp)]
    summary = summarize_topic(spec, selected).to_dict()
    if include_samples:
      summary["samples"] = [sample.to_dict() for sample in selected[:1000]]
    topics.append(summary)
  return {"schema_version": 1, "generated_at": None, "mode": "audit", "status": "ok", "query": {"topics": [spec.to_dict() for spec in specs], "backend": {"selected": "local-text"}}, "source": {"input": path, "kind": "file", "candidates": [path]}, "files": [{"path": path, "discovered_topics": sorted({sample.topic for sample in samples}), "topics": topics, "backend": {"selected": "local-text"}}], "blockers": []}


def local_text_compare_packet(fail: str, pass_source: str, specs: list[TopicSpec], window: TimeWindow, time_tolerance: float, numeric_tolerance: float) -> dict:
  from zml_audit.compare import compare_runs
  from zml_audit.stats import summarize_topic

  wanted_fields = tuple(sorted({field for spec in specs for field in spec.fields}))
  fail_text, fail_blocker = read_text_source(fail)
  pass_text, pass_blocker = read_text_source(pass_source)
  if fail_blocker or pass_blocker:
    return {"schema_version": 1, "generated_at": None, "mode": "compare", "status": "blocked", "sources": [{"input": fail}, {"input": pass_source}], "comparison": {}, "blockers": [item for item in (fail_blocker, pass_blocker) if item]}
  fail_samples_all = parse_samples(fail_text, fields=wanted_fields)
  pass_samples_all = parse_samples(pass_text, fields=wanted_fields)
  fail_map = {}
  pass_map = {}
  fail_summary = {}
  pass_summary = {}
  for spec in specs:
    fail_map[spec.name] = [sample for sample in fail_samples_all if sample.topic == spec.name and window.normalized().contains(sample.timestamp)]
    pass_map[spec.name] = [sample for sample in pass_samples_all if sample.topic == spec.name and window.normalized().contains(sample.timestamp)]
    fail_summary[spec.name] = summarize_topic(spec, fail_map[spec.name])
    pass_summary[spec.name] = summarize_topic(spec, pass_map[spec.name])
  comparison = compare_runs(fail_summary, pass_summary, fail_map, pass_map, time_tolerance=time_tolerance, numeric_tolerance=numeric_tolerance)
  return {"schema_version": 1, "generated_at": None, "mode": "compare", "status": "ok", "query": {"topics": [spec.to_dict() for spec in specs], "window": window.to_dict(), "tolerances": {"time": time_tolerance, "numeric": numeric_tolerance}, "backend": {"selected": "local-text"}}, "sources": [{"input": fail}, {"input": pass_source}], "comparison": comparison, "blockers": []}


def read_text_source(path: str) -> tuple[str, dict | None]:
  try:
    return Path(path).read_text(encoding="utf-8"), None
  except UnicodeDecodeError as exc:
    return "", {"tool": "local-text", "message": f"input is not UTF-8 text and no binary ZML backend decoded it: {exc}", "guidance": "Use zml-conv or zml-cli for binary .zml/.zml.zst files."}
  except OSError as exc:
    return "", {"tool": "local-text", "message": f"input could not be read: {exc}", "guidance": "Provide an existing local ZML/ZST path."}


def blocked_zml_packet(mode: str, path: str, blocker: dict) -> dict:
  return {"schema_version": 1, "generated_at": None, "mode": mode, "status": "blocked", "source": {"input": path, "kind": "file", "candidates": [path]}, "files": [], "blockers": [blocker]}


def zml_packet_report(title: str, packet: dict, sources: list, output_format: str) -> EvidenceReport:
  blockers = [canonical_blocker(item) for item in packet.get("blockers") or []]
  query_backend = (packet.get("query") or {}).get("backend") or {}
  request = SignalRequest(source=packet.get("source") or {}, topics=request_topics(packet), fields=request_fields(packet), backend_hint=query_backend.get("requested") or query_backend.get("selected"))
  signal = SignalResult(request=request, backend=packet_backend(packet), topics_found=packet_topics(packet), stats=packet_stats(packet), timebase=packet_timebase(packet), blockers=blockers)
  report = EvidenceReport(title=title, status=status_from_packet(packet), sources=sources, signal_results=[signal], blockers=blockers, confidence="medium" if not blockers else "blocked", extra={"legacy_packet": packet})
  report.summary = f"{title}: `{packet.get('status')}` using backend `{signal.backend}`."
  report.evidence_table.append({"finding": title, "source_ref": source_label(packet), "supports": "Canonical wrapper produced structured signal metadata.", "does_not_prove": "Does not prove root cause."})
  report.proves.append("The requested source was parsed into a canonical report shape.")
  report.does_not_prove.append("Signal presence or deltas alone do not prove causality.")
  return report


def write_csv_from_packet(packet: dict, path: str) -> None:
  rows = []
  for file_result in packet.get("files") or []:
    for topic in file_result.get("topics") or []:
      for sample in topic.get("samples") or []:
        base = {"path": file_result.get("path"), "topic": sample.get("topic"), "timestamp": sample.get("timestamp")}
        fields = sample.get("fields") or {}
        if fields:
          for name, value in fields.items():
            rows.append({**base, "field": name, "value": value})
        else:
          rows.append(base)
  Path(path).parent.mkdir(parents=True, exist_ok=True)
  with Path(path).open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["path", "topic", "timestamp", "field", "value"])
    writer.writeheader()
    writer.writerows(rows)


def write_compare_csv(packet: dict, path: str) -> None:
  rows = []
  comparison = packet.get("comparison") or {}
  for item in comparison.get("first_divergences") or []:
    rows.append({"section": "first_divergence", "topic": item.get("topic"), "field": item.get("field"), "metric": item.get("reason") or "value", "fail_value": item.get("fail_value"), "pass_value": item.get("pass_value"), "delta": item.get("delta")})
  for topic in comparison.get("topics") or []:
    for field in topic.get("fields") or []:
      rows.append({"section": "field_delta", "topic": topic.get("topic"), "field": field.get("field"), "metric": "mean_delta", "fail_value": field.get("fail_mean"), "pass_value": field.get("pass_mean"), "delta": field.get("mean_delta")})
  Path(path).parent.mkdir(parents=True, exist_ok=True)
  with Path(path).open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["section", "topic", "field", "metric", "fail_value", "pass_value", "delta"])
    writer.writeheader()
    writer.writerows(rows)


def specs_from_spec(path: str) -> list[TopicSpec]:
  from .specs import load_spec

  spec = load_spec(path)
  specs: list[TopicSpec] = []
  for item in spec.get("compare") or []:
    preset = item.get("preset")
    if preset:
      specs.extend(expand_specs([], [], preset))
    if item.get("topic"):
      specs.append(TopicSpec(item["topic"], tuple(zml_field_list(item))))
  if specs:
    return specs
  return [TopicSpec(item.get("topic"), tuple(item.get("fields") or [])) for item in spec.get("extract") or [] if item.get("topic")]


def zml_field_list(item: dict) -> list[str]:
  raw = item.get("fields") if "fields" in item else item.get("field")
  if raw is None:
    return []
  if isinstance(raw, str):
    return [raw]
  return list(raw)


def canonical_blocker(item: dict) -> Blocker:
  message = item.get("message") or str(item)
  category = "safety_boundary" if "refusing" in message else "backend_failure"
  return Blocker(code=item.get("tool") or "zml_backend_blocked", category=category, message=message, needed_action=item.get("guidance"), source_ref=item.get("command"))


def legacy_blocker(tool: str, message: str, guidance: str | None = None, command: str | None = None, returncode: int | None = None):
  from zml_audit.models import Blocker as LegacyBlocker

  return LegacyBlocker(tool=tool, message=message, guidance=guidance, command=command, returncode=returncode)


def status_from_packet(packet: dict) -> str:
  if packet.get("status") in {"blocked", "error"}:
    return "blocked"
  return "ok"


def packet_backend(packet: dict) -> str:
  for file_result in packet.get("files") or []:
    backend = file_result.get("backend") or {}
    if backend.get("selected"):
      return backend["selected"]
    for read in backend.get("reads") or []:
      if read.get("selected"):
        return read["selected"]
  query_backend = (packet.get("query") or {}).get("backend") or {}
  return query_backend.get("selected") or query_backend.get("requested") or "unknown"


def packet_topics(packet: dict) -> list[str]:
  topics = set()
  for file_result in packet.get("files") or []:
    if packet.get("mode") == "topics":
      topics.update(file_result.get("topics") or [])
    elif packet.get("mode") == "fields":
      topics.update(match.get("topic") for match in file_result.get("field_matches") or [] if isinstance(match, dict))
    else:
      topics.update(topic.get("topic") for topic in file_result.get("topics") or [] if isinstance(topic, dict))
  return sorted(topic for topic in topics if topic)


def request_topics(packet: dict) -> list[str]:
  return [item.get("name") for item in (packet.get("query") or {}).get("topics") or [] if item.get("name")]


def request_fields(packet: dict) -> list[str]:
  if packet.get("mode") == "fields":
    return [packet.get("query", {}).get("fuzzy")] if packet.get("query", {}).get("fuzzy") else []
  fields = []
  for item in (packet.get("query") or {}).get("topics") or []:
    fields.extend(item.get("fields") or [])
  return sorted(set(fields))


def packet_stats(packet: dict) -> dict:
  return {"mode": packet.get("mode"), "file_count": len(packet.get("files") or []), "topic_count": len(packet_topics(packet)), "topic_matches": packet_topic_matches(packet), "field_matches": packet_field_matches(packet), "comparison": packet.get("comparison")}


def packet_topic_matches(packet: dict) -> list[dict]:
  matches = []
  for file_result in packet.get("files") or []:
    matches.extend(file_result.get("topic_matches") or [])
  return matches


def packet_field_matches(packet: dict) -> list[dict]:
  matches = []
  for file_result in packet.get("files") or []:
    matches.extend(file_result.get("field_matches") or [])
  return sorted(matches, key=field_match_sort_key)


def field_match_sort_key(match: dict) -> tuple[float, float, float, int, str, str, str]:
  presence = {"present": 0.0, "unknown": 1.0, "not_present": 2.0}.get(str(match.get("topic_presence") or "unknown"), 1.0)
  extractable = 0.0 if match.get("extractable") else 1.0
  return (extractable, presence, -float(match.get("score") or 0), -int(match.get("sample_count") or 0), str(match.get("zml_path") or ""), str(match.get("topic") or ""), str(match.get("field_path") or ""))


def packet_timebase(packet: dict) -> TimebaseRef:
  return TimebaseRef(time_kind="message_stamp", units="seconds", origin="source-specific field", alignment_method="timestamp_tolerance" if packet.get("mode") == "compare" else "not_aligned", alignment_confidence="medium" if packet.get("status") == "ok" else "blocked")


def source_label(packet: dict) -> str:
  source = packet.get("source") or {}
  return source.get("input") or ", ".join(item.get("input", "") for item in packet.get("sources") or [])
