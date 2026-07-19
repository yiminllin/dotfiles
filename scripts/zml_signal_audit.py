#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from zml_audit.backends import BACKEND_CHOICES, BackendResult, resolve_systems_root, select_backend
from zml_audit.compare import compare_runs
from zml_audit.extract import MAX_EXPANDED_FIELDS_PER_SAMPLE, filter_samples, parse_samples, parse_time_arg
from zml_audit.fields import FieldDiscoveryOptions, discover_fields_for_file
from zml_audit.models import Blocker, FieldStats, JsonDict, Sample, SourceResolution, TimeWindow, TopicSpec, TopicSummary, utc_now
from zml_audit.presets import PRESETS, expand_specs
from zml_audit.render import render_csv, render_json, render_markdown
from zml_audit.sources import resolve_source
from zml_audit.stats import summarize_topic
from zml_audit.topics import fuzzy_topic_matches


def main() -> int:
  args = parse_args()
  if getattr(args, "format", None) == "both" and not args.out_dir:
    print("ERROR: --format both requires --out-dir so JSON and markdown have separate stable paths", file=sys.stderr)
    return 2
  if args.command in {"topics", "list-topics"}:
    try:
      packet = build_topics_packet(args.path, args.contains or [], args.regex or [], fuzzy=args.fuzzy, limit=args.limit, backend_name=args.backend, timeout_seconds=args.timeout, systems_root=args.systems_root)
    except ValueError as exc:
      print(f"ERROR: {exc}", file=sys.stderr)
      return 2
    label = slug("zml-topics")
  elif args.command == "fields":
    try:
      packet = build_fields_packet(
        args.path,
        fuzzy=args.fuzzy,
        topic=args.topic or [],
        topic_contains=args.topic_contains or [],
        topic_regex=args.topic_regex or [],
        topic_fuzzy=args.topic_fuzzy,
        sample_limit=args.sample_limit,
        limit=args.limit,
        max_topics_sampled=args.max_topics_sampled,
        max_topics=args.max_topics,
        sample_top=args.sample_top,
        no_sample=args.no_sample,
        max_fields_per_topic=args.max_fields_per_topic,
        max_zmls=args.max_zmls,
        max_workers=args.workers,
        backend_name=args.backend,
        timeout_seconds=args.timeout,
        systems_root=args.systems_root,
      )
    except ValueError as exc:
      print(f"ERROR: {exc}", file=sys.stderr)
      return 2
    label = slug("zml-fields")
  else:
    try:
      window = build_window(args)
    except ValueError as exc:
      print(f"ERROR: {exc}", file=sys.stderr)
      return 2
    specs = expand_specs(args.topic or [], args.field or [], args.preset)
    if not specs:
      print("ERROR: provide at least one --topic or --preset", file=sys.stderr)
      return 2

    if args.command == "compare":
      packet = build_compare_packet(
        args.fail,
        args.pass_path,
        specs,
        window,
        time_tolerance=args.time_tolerance,
        numeric_tolerance=args.numeric_tolerance,
        transition_limit=args.transition_limit,
        include_samples=bool(args.csv),
        csv_sample_limit=args.csv_sample_limit,
        backend_name=args.backend,
        timeout_seconds=args.timeout,
        systems_root=args.systems_root,
      )
    else:
      packet = build_audit_packet(
        args.path,
        specs,
        window,
        transition_limit=args.transition_limit,
        include_samples=bool(args.csv),
        csv_sample_limit=args.csv_sample_limit,
        backend_name=args.backend,
        timeout_seconds=args.timeout,
        systems_root=args.systems_root,
        direct_known_extract=bool(args.topic and args.field and not args.preset and is_single_exact_topic_with_fields(specs)),
      )
    label = slug(f"zml-{args.command}-{args.preset or specs[0].name}")
  report_packet = packet_without_samples(packet)
  outputs = write_outputs(report_packet, args.out_dir, args.format, label)
  csv_path = None
  if getattr(args, "csv", None):
    write_csv(packet, args.csv)
    csv_path = args.csv
  if outputs:
    for path in outputs:
      print(path)
    if csv_path:
      print(csv_path)
  else:
    print(render_markdown(report_packet) if args.format == "markdown" else render_json(report_packet), end="")
    if csv_path:
      print(csv_path, file=sys.stderr)
  return 1 if packet.get("status") in {"blocked", "error"} else 0


def build_topics_packet(path: str, contains: list[str], regexes: list[str], zml: Any | None = None, fuzzy: str | None = None, limit: int = 20, backend_name: str = "auto", timeout_seconds: float = 60.0, systems_root: str | None = None) -> JsonDict:
  resolved_systems_root = resolve_systems_root(systems_root)
  zml = zml or select_backend(backend_name, timeout_seconds, resolved_systems_root)
  source = resolve_source(path)
  blockers = [blocker.to_dict() for blocker in source.blockers]
  files = []
  for candidate in source.candidates:
    topic_result = list_topics(zml, candidate)
    if topic_result.blocker:
      blockers.append(topic_result.blocker.to_dict())
      topics: list[str] = []
    else:
      topics = filter_topic_names(parse_topic_list(topic_result.stdout), contains, regexes)
    row: JsonDict = {"path": candidate, "topics": topics, "topic_count": len(topics)}
    if fuzzy:
      matches = fuzzy_topic_matches(topics, fuzzy, limit)
      row["topics"] = [match.topic for match in matches]
      row["topic_count"] = len(matches)
      row["topic_matches"] = [match.to_dict() for match in matches]
    files.append(compact_backend_metadata(row, topic_result.metadata))
  return {
    "schema_version": 1,
    "generated_at": utc_now(),
    "mode": "topics",
    "status": status_for(blockers, files),
    "query": {"contains": contains, "regex": regexes, "fuzzy": fuzzy, "limit": limit if fuzzy else None, "backend": backend_query_metadata(backend_name, timeout_seconds, resolved_systems_root)},
    "source": source.to_dict(),
    "files": files,
    "blockers": blockers,
  }


def build_fields_packet(
  path: str,
  fuzzy: str,
  topic: list[str] | None = None,
  topic_contains: list[str] | None = None,
  topic_regex: list[str] | None = None,
  topic_fuzzy: str | None = None,
  sample_limit: int = 5,
  limit: int = 20,
  max_topics_sampled: int = 25,
  max_topics: int = 500,
  sample_top: int = 0,
  no_sample: bool = False,
  max_fields_per_topic: int = 1000,
  max_zmls: int = 200,
  max_workers: int = 1,
  zml: Any | None = None,
  backend_name: str = "auto",
  timeout_seconds: float = 60.0,
  systems_root: str | None = None,
) -> JsonDict:
  resolved_systems_root = resolve_systems_root(systems_root)
  zml = zml or select_backend(backend_name, timeout_seconds, resolved_systems_root)
  source = resolve_source(path, max_candidates=max_zmls)
  blockers = [blocker.to_dict() for blocker in source.blockers]
  options = FieldDiscoveryOptions(
    fuzzy=fuzzy,
    topic=tuple(topic or ()),
    topic_contains=tuple(topic_contains or ()),
    topic_regex=tuple(topic_regex or ()),
    topic_fuzzy=topic_fuzzy,
    sample_limit=sample_limit,
    limit=limit,
    max_topics_sampled=max_topics_sampled,
    max_topics=max_topics,
    sample_top=sample_top,
    no_sample=no_sample,
    max_fields_per_topic=max_fields_per_topic,
    systems_root=resolved_systems_root,
  )
  candidates = list(source.candidates)
  files = []
  worker_count = min(max(1, max_workers), len(candidates)) if candidates else 1
  discovered = discover_fields_for_candidates(candidates, zml, options, worker_count)
  for file_result, file_blockers in discovered:
    files.append(file_result)
    blockers.extend(blocker.to_dict() for blocker in file_blockers)
  files.sort(key=field_discovery_file_sort_key)
  return {
    "schema_version": 1,
    "generated_at": utc_now(),
    "mode": "fields",
    "status": status_for(blockers, files),
    "query": {
      "fuzzy": fuzzy,
      "topic": topic or [],
      "topic_contains": topic_contains or [],
      "topic_regex": topic_regex or [],
      "topic_fuzzy": topic_fuzzy,
      "sample_limit": sample_limit,
      "limit": limit,
      "max_topics_sampled": max_topics_sampled,
      "max_topics": max_topics,
      "sample_top": sample_top,
      "no_sample": no_sample,
      "max_fields_per_topic": max_fields_per_topic,
      "max_zmls": max_zmls,
      "max_workers": worker_count,
      "backend": backend_query_metadata(backend_name, timeout_seconds, resolved_systems_root),
    },
    "source": source.to_dict(),
    "files": files,
    "blockers": blockers,
  }


def discover_fields_for_candidates(candidates: list[str], zml: Any, options: FieldDiscoveryOptions, max_workers: int) -> list[tuple[JsonDict, list[Blocker]]]:
  if max_workers <= 1 or len(candidates) <= 1:
    return [discover_fields_for_file(candidate, zml, options) for candidate in candidates]
  with ThreadPoolExecutor(max_workers=max_workers) as executor:
    return list(executor.map(lambda candidate: discover_fields_for_file(candidate, zml, options), candidates))


def field_discovery_file_sort_key(file_result: JsonDict) -> tuple[float, float, float, int, str]:
  matches = file_result.get("field_matches") or []
  if not matches:
    return (1.0, 1.0, 0.0, 0, str(file_result.get("path") or ""))
  best = min(matches, key=field_discovery_match_sort_key)
  extractable, presence, score, samples, _topic, _field = field_discovery_match_sort_key(best)
  return (extractable, presence, score, samples, str(file_result.get("path") or ""))


def field_discovery_match_sort_key(match: JsonDict) -> tuple[float, float, float, int, str, str]:
  presence = {"present": 0.0, "unknown": 1.0, "not_present": 2.0}.get(str(match.get("topic_presence") or "unknown"), 1.0)
  extractable = 0.0 if match.get("extractable") else 1.0
  return (extractable, presence, -float(match.get("score") or 0), -int(match.get("sample_count") or 0), str(match.get("topic") or ""), str(match.get("field_path") or ""))


def build_audit_packet(
  path: str,
  specs: list[TopicSpec],
  window: TimeWindow,
  zml: Any | None = None,
  transition_limit: int = 5,
  include_samples: bool = False,
  csv_sample_limit: int = 10000,
  backend_name: str = "auto",
  timeout_seconds: float = 60.0,
  direct_known_extract: bool = False,
  systems_root: str | None = None,
) -> JsonDict:
  resolved_systems_root = resolve_systems_root(systems_root)
  zml = zml or select_backend(backend_name, timeout_seconds, resolved_systems_root)
  source = resolve_source(path)
  blockers = [blocker.to_dict() for blocker in source.blockers]
  selection_metadata: JsonDict = {}
  candidates = list(source.candidates)
  skip_topic_listing = False
  if direct_known_extract and is_single_exact_topic_with_fields(specs):
    candidates, selection_metadata, selection_blockers = select_direct_known_extract_candidates(source, zml, specs[0].name)
    blockers.extend(blocker.to_dict() for blocker in selection_blockers)
    skip_topic_listing = True
  files = []
  for candidate in candidates:
    file_result, file_blockers = audit_file(candidate, specs, window, zml, transition_limit=transition_limit, include_sample_rows=include_samples, sample_row_limit=csv_sample_limit, skip_topic_listing=skip_topic_listing, selection_metadata=selection_metadata)
    files.append(file_result)
    blockers.extend(blocker.to_dict() for blocker in file_blockers)
  query = {"topics": [spec.to_dict() for spec in specs], "window": window.to_dict(), "backend": backend_query_metadata(backend_name, timeout_seconds, resolved_systems_root)}
  if direct_known_extract:
    query["direct_known_extract"] = True
  if include_samples:
    query["csv_sample_limit"] = csv_sample_limit
  return {
    "schema_version": 1,
    "generated_at": utc_now(),
    "mode": "audit",
    "status": status_for(blockers, files),
    "query": query,
    "source": source.to_dict(),
    "files": files,
    "blockers": blockers,
  }


def build_compare_packet(
  fail_path: str,
  pass_path: str,
  specs: list[TopicSpec],
  window: TimeWindow,
  zml: Any | None = None,
  time_tolerance: float = 0.0,
  numeric_tolerance: float = 0.0,
  transition_limit: int = 5,
  include_samples: bool = False,
  csv_sample_limit: int = 10000,
  backend_name: str = "auto",
  timeout_seconds: float = 60.0,
  systems_root: str | None = None,
) -> JsonDict:
  resolved_systems_root = resolve_systems_root(systems_root)
  zml = zml or select_backend(backend_name, timeout_seconds, resolved_systems_root)
  fail_source = resolve_source(fail_path)
  pass_source = resolve_source(pass_path)
  blockers = [blocker.to_dict() for source in (fail_source, pass_source) for blocker in source.blockers]
  fail_file, fail_selection_blockers = single_compare_candidate(fail_source, "fail")
  pass_file, pass_selection_blockers = single_compare_candidate(pass_source, "pass")
  blockers.extend(blocker.to_dict() for blocker in fail_selection_blockers + pass_selection_blockers)
  comparison: JsonDict = {}
  fail_result: JsonDict = {}
  pass_result: JsonDict = {}
  if not blockers and fail_file and pass_file:
    fail_result, fail_blockers, fail_samples = audit_file(fail_file, specs, window, zml, collect_samples=True, transition_limit=transition_limit, include_sample_rows=include_samples, sample_row_limit=csv_sample_limit)
    pass_result, pass_blockers, pass_samples = audit_file(pass_file, specs, window, zml, collect_samples=True, transition_limit=transition_limit, include_sample_rows=include_samples, sample_row_limit=csv_sample_limit)
    blockers.extend(blocker.to_dict() for blocker in fail_blockers + pass_blockers)
    fail_summaries = {topic["topic"]: summary_from_dict(topic) for topic in fail_result.get("topics", [])}
    pass_summaries = {topic["topic"]: summary_from_dict(topic) for topic in pass_result.get("topics", [])}
    comparison = compare_runs(fail_summaries, pass_summaries, fail_samples, pass_samples, time_tolerance=time_tolerance, numeric_tolerance=numeric_tolerance)
  query = {"topics": [spec.to_dict() for spec in specs], "window": window.to_dict(), "tolerances": {"time": time_tolerance, "numeric": numeric_tolerance}, "backend": backend_query_metadata(backend_name, timeout_seconds, resolved_systems_root)}
  if include_samples:
    query["csv_sample_limit"] = csv_sample_limit
  return {
    "schema_version": 1,
    "generated_at": utc_now(),
    "mode": "compare",
    "status": "blocked" if blockers else "ok",
    "query": query,
    "sources": [fail_source.to_dict(), pass_source.to_dict()],
    "fail": fail_result,
    "pass": pass_result,
    "comparison": comparison,
    "blockers": blockers,
  }


def single_compare_candidate(source: SourceResolution, label: str) -> tuple[str | None, list[Blocker]]:
  if len(source.candidates) == 1:
    return source.candidates[0], []
  if len(source.candidates) > 1:
    return None, [
      Blocker(
        tool="source",
        message=f"{label} input resolved to {len(source.candidates)} ZML candidates; compare requires exactly one candidate per side",
        guidance="pass an exact .zml/.zml.zst file or a narrower directory",
      )
    ]
  return None, []


def audit_file(
  path: str,
  specs: list[TopicSpec],
  window: TimeWindow,
  zml: Any,
  collect_samples: bool = False,
  transition_limit: int = 5,
  include_sample_rows: bool = False,
  sample_row_limit: int = 10000,
  skip_topic_listing: bool = False,
  selection_metadata: JsonDict | None = None,
):
  blockers = []
  if skip_topic_listing:
    topic_result = BackendResult(metadata={"skipped": True, "reason": "direct_known_extract_exact_topic_field"})
    discovered_topics: list[str] = []
  else:
    topic_result = list_topics(zml, path)
    if topic_result.blocker and not topic_result.metadata.get("unsupported_operation"):
      blockers.append(topic_result.blocker)
    discovered_topics = parse_topic_list(topic_result.stdout)
  topics = []
  backend_reads = []
  sample_map: dict[str, list] = {}
  for spec in specs:
    result = read_topic(zml, path, spec.name, window, spec.fields)
    if result.metadata:
      backend_reads.append(read_backend_metadata(spec.name, result.metadata, spec.fields))
    if result.blocker:
      blockers.append(result.blocker)
      topics.append(summarize_topic(spec, [], transition_limit=transition_limit).to_dict())
      sample_map[spec.name] = []
      continue
    parsed_samples = parse_samples(result.stdout, default_topic=spec.name, fields=spec.fields)
    if result.stdout.strip() and not parsed_samples:
      blockers.append(
        Blocker(
          tool="parser",
          message=f"zml print output for {spec.name} was non-empty but no samples could be parsed",
          guidance="capture a small zml print fixture and extend zml_audit.extract parsing for this output shape",
        )
      )
    samples = filter_samples(parsed_samples, spec, window)
    sample_map[spec.name] = samples
    topic_summary = summarize_topic(spec, samples, transition_limit=transition_limit).to_dict()
    if field_expansion := field_expansion_metadata(samples):
      topic_summary["field_expansion"] = field_expansion
    if include_sample_rows:
      sample_row_limit = max(0, sample_row_limit)
      topic_summary["samples"], topic_summary["sample_export"] = export_sample_rows(samples, sample_row_limit)
    topics.append(topic_summary)
  file_result = compact_backend_metadata({"path": path, "discovered_topics": discovered_topics, "topics": topics}, {"selection": selection_metadata or {}, "list_topics": topic_result.metadata, "reads": backend_reads})
  if collect_samples:
    return file_result, blockers, sample_map
  return file_result, blockers


def is_single_exact_topic_with_fields(specs: list[TopicSpec]) -> bool:
  return len(specs) == 1 and bool(specs[0].name and specs[0].fields)


def select_direct_known_extract_candidates(source: SourceResolution, zml: Any, topic: str) -> tuple[list[str], JsonDict, list[Blocker]]:
  if source.kind == "file":
    return list(source.candidates), {"mode": "exact_file", "topic_listing": "skipped"}, []
  if source.kind != "directory":
    return list(source.candidates), {}, []

  listing_blockers: list[Blocker] = []
  matches: list[JsonDict] = []
  inspected: list[JsonDict] = []
  ranked_candidates = rank_direct_extract_candidates(source.candidates, topic)
  for candidate in ranked_candidates:
    result = list_topics(zml, candidate)
    if result.blocker:
      listing_blockers.append(result.blocker)
      inspected.append(compact_backend_metadata({"path": candidate, "contains_requested_topic": False, "topic_listing_error": result.blocker.to_dict()}, {"list_topics": result.metadata}))
      continue
    topics = parse_topic_list(result.stdout)
    contains = topic in topics
    row = compact_backend_metadata({"path": candidate, "contains_requested_topic": contains, "topic_count": len(topics)}, {"list_topics": result.metadata})
    inspected.append(row)
    if contains:
      matches.append(row)
      break

  inspected_paths = {str(row.get("path")) for row in inspected}
  uninspected = [candidate for candidate in ranked_candidates if candidate not in inspected_paths]

  selection = {
    "mode": "directory_exact_topic",
    "strategy": "ranked_first_topic_match",
    "requested_topic": topic,
    "candidate_count": len(source.candidates),
    "inspected_candidate_count": len(inspected),
    "uninspected_candidate_count": len(uninspected),
    "matching_candidate_count": len(matches),
    "matching_candidate_count_is_exhaustive": not uninspected,
    "selected_path": matches[0]["path"] if matches else None,
    "ambiguous": len(matches) > 1 or bool(uninspected),
    "ambiguity_reason": "uninspected_candidates_not_ruled_out" if uninspected else None,
    "matching_candidates": matches[:10],
    "inspected_candidates": inspected[:10],
    "uninspected_candidates": uninspected[:10],
  }
  blockers = listing_blockers if not matches else []
  if not matches and not blockers:
    blockers.append(Blocker(tool="source", message=f"no ZML candidate under directory listed requested topic {topic}", guidance="pass an exact ZML file or verify the topic spelling with topics/list-topics"))
  return [str(matches[0]["path"])] if matches else [], compact_backend_metadata(selection, {}), blockers


def rank_direct_extract_candidates(candidates: tuple[str, ...], topic: str) -> list[str]:
  head = topic.lstrip("/").split(".", 1)[0].lower()
  return sorted(candidates, key=lambda candidate: (direct_extract_candidate_score(candidate, head), candidate))


def direct_extract_candidate_score(candidate: str, topic_head: str) -> int:
  path = candidate.lower()
  score = 100
  if topic_head and (f"/{topic_head}/" in path or f"/{topic_head}.zml" in path):
    score -= 30
  if topic_head == "compute_a" and "/compute_b/" in path:
    score += 40
  if topic_head == "compute_b" and "/compute_a/" in path:
    score += 40
  if "/droid-" in path and topic_head != "droid":
    score += 30
  if "/validators/" in path:
    score += 20
  if path.endswith("/world.zml") and topic_head not in {"sil", "world"}:
    score += 20
  return score


def read_backend_metadata(topic: str, metadata: JsonDict, fields: tuple[str, ...]) -> JsonDict:
  row = {"topic": topic, **metadata}
  if fields and "field_filtering" not in row:
    row["field_filtering"] = "local"
  return row


def export_sample_rows(samples: list[Sample], row_limit: int) -> tuple[list[JsonDict], JsonDict]:
  exported: list[JsonDict] = []
  included_rows = 0
  partial_sample_count = 0
  limit = max(0, row_limit)

  for sample in samples:
    if included_rows >= limit:
      break
    sample_row_count = csv_row_count_for_sample(sample)
    if not sample.fields:
      exported.append(sample.to_dict())
      included_rows += 1
      continue
    remaining = limit - included_rows
    selected_fields = dict(sorted(sample.fields.items())[:remaining])
    sample_dict = sample.to_dict()
    sample_dict["fields"] = selected_fields
    if len(selected_fields) < len(sample.fields):
      metadata = dict(sample_dict.get("metadata") or {})
      metadata["sample_export_truncated_field_count"] = len(sample.fields) - len(selected_fields)
      sample_dict["metadata"] = metadata
      partial_sample_count += 1
    exported.append(sample_dict)
    included_rows += min(sample_row_count, remaining)

  return exported, sample_export_metadata(samples, exported, included_rows, limit, partial_sample_count)


def sample_export_metadata(samples: list[Sample], exported: list[JsonDict], included_rows: int, limit: int, partial_sample_count: int = 0) -> JsonDict:
  total_rows = sum(csv_row_count_for_sample(sample) for sample in samples)
  return {
    "total_count": len(samples),
    "included_count": len(exported),
    "omitted_count": len(samples) - len(exported),
    "limit": limit,
    "total_sample_row_count": total_rows,
    "included_sample_row_count": included_rows,
    "omitted_sample_row_count": total_rows - included_rows,
    "partial_sample_count": partial_sample_count,
  }


def csv_row_count_for_sample(sample: Sample) -> int:
  return max(1, len(sample.fields))


def field_expansion_metadata(samples: list[Sample]) -> JsonDict:
  truncated_count = sum(1 for sample in samples if sample.metadata.get("field_expansion_truncated"))
  if not truncated_count:
    return {}
  return {
    "truncated_sample_count": truncated_count,
    "expanded_field_limit_per_sample": MAX_EXPANDED_FIELDS_PER_SAMPLE,
  }


def list_topics(zml: Any, path: str) -> BackendResult:
  return zml.list_topics(path)


def read_topic(zml: Any, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...] = ()) -> BackendResult:
  if hasattr(zml, "read_topic"):
    try:
      return zml.read_topic(path, topic, window, fields=tuple(fields))
    except TypeError:
      return zml.read_topic(path, topic, window)
  return zml.print_topic(path, topic)


def backend_query_metadata(requested: str, timeout_seconds: float, systems_root: str | None = None) -> JsonDict:
  return {"requested": requested, "timeout_seconds": timeout_seconds, "systems_root": systems_root}


def compact_backend_metadata(row: JsonDict, metadata: JsonDict) -> JsonDict:
  compact_metadata = {key: value for key, value in metadata.items() if value not in (None, [], {}, ())}
  if compact_metadata:
    row["backend"] = compact_metadata
  return row


def summary_from_dict(value: JsonDict) -> TopicSummary:
  return TopicSummary(
    topic=value.get("topic", ""),
    present=bool(value.get("present")),
    sample_count=int(value.get("sample_count") or 0),
    first_timestamp=value.get("first_timestamp"),
    last_timestamp=value.get("last_timestamp"),
    approximate_rate_hz=value.get("approximate_rate_hz"),
    fields={name: FieldStats(name=name, **stats) for name, stats in (value.get("fields") or {}).items()},
  )


def parse_topic_list(text: str) -> list[str]:
  topics = []
  for line in text.splitlines():
    stripped = line.strip()
    if stripped and not stripped.startswith("#"):
      topics.append(stripped.split()[0])
  return topics


def filter_topic_names(topics: list[str], contains: list[str], regexes: list[str]) -> list[str]:
  patterns = []
  for raw in regexes:
    try:
      patterns.append(re.compile(raw))
    except re.error as exc:
      raise ValueError(f"invalid --regex {raw!r}: {exc}") from exc
  filtered = []
  for topic in topics:
    if contains and not all(value in topic for value in contains):
      continue
    if patterns and not all(pattern.search(topic) for pattern in patterns):
      continue
    filtered.append(topic)
  return filtered


def status_for(blockers: list[JsonDict], files: list[JsonDict]) -> str:
  if blockers:
    return "blocked"
  return "ok" if files else "error"


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Audit ZML signals and compare pass/fail runs without discovering or downloading artifacts.")
  subparsers = parser.add_subparsers(dest="command", required=True)

  audit = subparsers.add_parser("audit", help="Audit topics in a local ZML/ZST file or bounded log root.")
  audit.add_argument("path", help="Local .zml/.zml.zst file or directory containing ZML logs")
  add_common_args(audit)

  compare = subparsers.add_parser("compare", help="Compare topics between failing and passing local ZML/ZST inputs.")
  compare.add_argument("--fail", required=True, help="Failing local .zml/.zml.zst file or directory resolving to one candidate")
  compare.add_argument("--pass", dest="pass_path", required=True, help="Passing local .zml/.zml.zst file or directory resolving to one candidate")
  add_common_args(compare)
  compare.add_argument("--time-tolerance", type=nonnegative_float, default=0.0, help="Timestamp alignment tolerance in seconds (default: 0, exact matching)")
  compare.add_argument("--numeric-tolerance", type=nonnegative_float, default=0.0, help="Numeric value equality tolerance (default: 0, exact equality)")

  topics = subparsers.add_parser("topics", help="List topics in a local ZML/ZST file or bounded log root.")
  topics.add_argument("path", help="Local .zml/.zml.zst file or directory containing ZML logs")
  add_topic_args(topics)

  fields = subparsers.add_parser("fields", help="Discover field paths across bounded topic samples when the exact topic is unknown.")
  fields.add_argument("path", help="Local .zml/.zml.zst file or directory containing ZML logs")
  add_field_args(fields)

  list_topics = subparsers.add_parser("list-topics", help="Alias for topics.")
  list_topics.add_argument("path", help="Local .zml/.zml.zst file or directory containing ZML logs")
  add_topic_args(list_topics)
  return parser.parse_args()


def add_common_args(parser: argparse.ArgumentParser) -> None:
  parser.add_argument("--topic", action="append", help="Topic to extract; repeatable")
  parser.add_argument("--field", action="append", help="Field to summarize for explicitly listed topics; repeatable")
  parser.add_argument("--preset", choices=sorted(PRESETS), help="Expand a data-driven topic/field preset before extraction")
  parser.add_argument("--start", help="Inclusive numeric or ISO timestamp")
  parser.add_argument("--end", help="Inclusive numeric or ISO timestamp")
  parser.add_argument("--center", help="Center numeric or ISO timestamp; use with --duration")
  parser.add_argument("--duration", type=positive_float, help="Window duration in seconds; use with --center")
  parser.add_argument("--format", choices=("json", "markdown", "both"), default="markdown")
  parser.add_argument("--out-dir", help="Directory for report outputs; stdout is used when omitted")
  parser.add_argument("--csv", help="Write bounded audit/compare sample and stats rows to CSV")
  parser.add_argument("--csv-sample-limit", type=nonnegative_int, default=10000, help="Maximum sample rows per topic exported to CSV (default: 10000)")
  parser.add_argument("--transition-limit", type=nonnegative_int, default=5, help="Maximum transition detail rows per field (default: 5)")
  add_backend_args(parser)


def add_topic_args(parser: argparse.ArgumentParser) -> None:
  parser.add_argument("--contains", action="append", help="Keep topics containing this substring; repeatable")
  parser.add_argument("--regex", action="append", help="Keep topics matching this regular expression; repeatable")
  parser.add_argument("--fuzzy", help="Fuzzy-search topics by substring, tokens, and approximate matching")
  parser.add_argument("--limit", type=positive_int, default=20, help="Maximum fuzzy topic matches to show (default: 20)")
  parser.add_argument("--format", choices=("json", "markdown", "both"), default="markdown")
  parser.add_argument("--out-dir", help="Directory for report output; stdout is used when omitted")
  add_backend_args(parser)


def add_field_args(parser: argparse.ArgumentParser) -> None:
  parser.add_argument("--fuzzy", required=True, help="Fuzzy/substring query for field names or paths")
  parser.add_argument("--topic", action="append", help="Restrict discovery to this exact topic; repeatable")
  parser.add_argument("--topic-contains", action="append", help="Restrict candidate topics to this substring; repeatable")
  parser.add_argument("--topic-regex", action="append", help="Restrict candidate topics to this regular expression; repeatable")
  parser.add_argument("--topic-fuzzy", help="Fuzzy-search candidate topics before bounded sampling")
  parser.add_argument("--sample-limit", type=nonnegative_int, default=5, help="Maximum parsed samples per sampled topic (default: 5)")
  parser.add_argument("--sample-top", type=nonnegative_int, default=0, help="Sample only the top N metadata/fallback candidates for examples or no-index discovery (default: 0)")
  parser.add_argument("--no-sample", action="store_true", help="Disable decoded sample fallback; report metadata/index matches only")
  parser.add_argument("--limit", type=nonnegative_int, default=20, help="Maximum field matches to show (default: 20)")
  parser.add_argument("--max-zmls", type=positive_int, default=200, help="Maximum candidate ZML files under a directory (default: 200)")
  parser.add_argument("--workers", type=positive_int, default=4, help="Maximum concurrent ZML metadata/list probes for field discovery (default: 4)")
  parser.add_argument("--max-topics", type=nonnegative_int, default=500, help="Maximum candidate topics considered per ZML before sampling (default: 500)")
  parser.add_argument("--max-topics-sampled", type=nonnegative_int, default=25, help="Hard cap on topics read for field discovery (default: 25)")
  parser.add_argument("--max-fields-per-topic", type=nonnegative_int, default=1000, help="Hard cap on flattened unique fields tracked per topic (default: 1000)")
  parser.add_argument("--format", choices=("json", "markdown", "both"), default="markdown")
  parser.add_argument("--out-dir", help="Directory for report output; stdout is used when omitted")
  add_backend_args(parser)


def add_backend_args(parser: argparse.ArgumentParser) -> None:
  parser.add_argument("--backend", choices=BACKEND_CHOICES, default="auto", help="ZML reader backend (default: auto)")
  parser.add_argument("--systems-root", default=resolve_systems_root(), help="Systems checkout root for Phoenix-aware backends (default: /Systems when present)")
  parser.add_argument("--timeout", type=positive_float, default=60.0, help="Per-backend command timeout in seconds (default: 60)")


def build_window(args: argparse.Namespace) -> TimeWindow:
  if (args.center is None) != (args.duration is None):
    raise ValueError("--center and --duration must be provided together")
  return TimeWindow(start=parse_time_arg(args.start), end=parse_time_arg(args.end), center=parse_time_arg(args.center), duration=args.duration).normalized()


def write_outputs(packet: JsonDict, out_dir: str | None, output_format: str, label: str) -> list[str]:
  if not out_dir:
    return []
  directory = Path(out_dir)
  directory.mkdir(parents=True, exist_ok=True)
  outputs = []
  if output_format in {"json", "both"}:
    path = directory / f"{label}.json"
    path.write_text(render_json(packet), encoding="utf-8")
    outputs.append(str(path))
  if output_format in {"markdown", "both"}:
    path = directory / f"{label}.md"
    path.write_text(render_markdown(packet), encoding="utf-8")
    outputs.append(str(path))
  return outputs


def write_csv(packet: JsonDict, path: str) -> None:
  Path(path).write_text(render_csv(packet), encoding="utf-8")


def packet_without_samples(packet: JsonDict) -> JsonDict:
  if packet.get("mode") not in {"audit", "compare"}:
    return packet
  cleaned = dict(packet)
  if "files" in cleaned:
    cleaned["files"] = [file_without_samples(file_result) for file_result in cleaned.get("files") or []]
  if "fail" in cleaned:
    cleaned["fail"] = file_without_samples(cleaned.get("fail") or {})
  if "pass" in cleaned:
    cleaned["pass"] = file_without_samples(cleaned.get("pass") or {})
  return cleaned


def file_without_samples(file_result: JsonDict) -> JsonDict:
  cleaned = dict(file_result)
  topics = []
  for topic in cleaned.get("topics") or []:
    if isinstance(topic, dict):
      topics.append({key: value for key, value in topic.items() if key != "samples"})
    else:
      topics.append(topic)
  cleaned["topics"] = topics
  return cleaned


def slug(value: str) -> str:
  value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
  return value[:120] or "zml-audit"


def positive_float(raw: str) -> float:
  value = float(raw)
  if value <= 0:
    raise argparse.ArgumentTypeError("must be greater than 0")
  return value


def nonnegative_float(raw: str) -> float:
  value = float(raw)
  if value < 0:
    raise argparse.ArgumentTypeError("must be greater than or equal to 0")
  return value


def positive_int(raw: str) -> int:
  value = int(raw)
  if value < 1:
    raise argparse.ArgumentTypeError("must be at least 1")
  return value


def nonnegative_int(raw: str) -> int:
  value = int(raw)
  if value < 0:
    raise argparse.ArgumentTypeError("must be greater than or equal to 0")
  return value


if __name__ == "__main__":
  sys.exit(main())
