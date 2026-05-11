from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .backends import BackendResult
from .extract import parse_samples
from .models import Blocker, JsonDict, TimeWindow, compact_dict
from .topics import approximate_token_score, fuzzy_topic_matches, topic_tokens


DEFAULT_FIELD_MATCH_LIMIT = 20
DEFAULT_MAX_TOPICS_SAMPLED = 25
DEFAULT_SAMPLE_LIMIT = 5
DEFAULT_MAX_FIELDS_PER_TOPIC = 1000


@dataclass(frozen=True)
class FieldDiscoveryOptions:
  fuzzy: str
  topic: tuple[str, ...] = ()
  topic_contains: tuple[str, ...] = ()
  topic_regex: tuple[str, ...] = ()
  topic_fuzzy: str | None = None
  sample_limit: int = DEFAULT_SAMPLE_LIMIT
  limit: int = DEFAULT_FIELD_MATCH_LIMIT
  max_topics_sampled: int = DEFAULT_MAX_TOPICS_SAMPLED
  max_topics: int = 500
  sample_top: int = 0
  no_sample: bool = False
  max_fields_per_topic: int = DEFAULT_MAX_FIELDS_PER_TOPIC
  systems_root: str | None = None


@dataclass
class FieldObservation:
  sample_count: int = 0
  example_value: Any = None


@dataclass(frozen=True)
class FieldScore:
  score: float
  reason: str


@dataclass(frozen=True)
class FieldMetadataRecord:
  topic: str
  field_path: str
  example_value: Any = None
  source: str = ""
  topic_presence: str = "unknown"


def discover_fields_for_file(path: str, zml: Any, options: FieldDiscoveryOptions) -> tuple[JsonDict, list[Blocker]]:
  blockers: list[Blocker] = []
  metadata_result = read_field_metadata(zml, path)
  metadata_records = parse_field_metadata(metadata_result.stdout, options.max_fields_per_topic)
  topic_probe_result, present_topics = probe_present_topics(zml, path)
  schema_records = schema_metadata_records(path, present_topics)
  if metadata_records:
    records = merge_metadata_records(mark_records_topic_presence(metadata_records, present_topics), schema_records)
    return discover_fields_from_metadata(path, zml, options, metadata_result, records, topic_probe_result, present_topics)
  if schema_records and fallback_sample_topic_count(options) == 0:
    schema_result = BackendResult(backend="raw-schema", metadata=schema_metadata_probe(options.systems_root))
    return discover_fields_from_metadata(path, zml, options, schema_result, schema_records, topic_probe_result, present_topics)
  if fallback_sample_topic_count(options) == 0:
    discovery = bounds_metadata([], [], options)
    discovery["backend_source"] = "fallback"
    discovery["metadata_probe"] = probe_metadata(metadata_result)
    discovery["needs_sampling"] = True
    file_result = {"path": path, "field_matches": [], "match_count": 0, "field_discovery": discovery}
    return with_backend_metadata(file_result, metadata_result, []), blockers

  list_result = zml.list_topics(path)
  if list_result.blocker:
    blockers.append(list_result.blocker)
    discovery = bounds_metadata([], [], options)
    discovery["backend_source"] = "fallback"
    discovery["metadata_probe"] = probe_metadata(metadata_result)
    return with_backend_metadata({"path": path, "field_matches": [], "field_discovery": discovery}, list_result, []), blockers

  topics = parse_topic_list(list_result.stdout)
  candidate_topics, topic_scores = filter_candidate_topics(topics, options)
  candidate_topics = candidate_topics[: max(0, options.max_topics)]
  max_sampled_topics = fallback_sample_topic_count(options)
  sampled_topics = candidate_topics[:max_sampled_topics]
  backend_reads: list[JsonDict] = []
  topic_metadata: list[JsonDict] = []
  matches: list[JsonDict] = []

  for topic in sampled_topics:
    result = read_topic(zml, path, topic)
    if result.metadata:
      backend_reads.append({"topic": topic, **result.metadata})
    if result.blocker:
      blockers.append(result.blocker)
      topic_metadata.append({"topic": topic, "sample_count": 0, "parsed_sample_count": 0, "omitted_sample_count": 0, "field_count": 0, "omitted_field_count": 0})
      break

    parsed_samples = parse_samples(result.stdout, default_topic=topic)
    if result.stdout.strip() and not parsed_samples:
      blockers.append(Blocker(tool="parser", message=f"zml print output for {topic} was non-empty but no samples could be parsed", guidance="capture a small zml print fixture and extend zml_audit.extract parsing for this output shape"))
    sample_limit = max(0, options.sample_limit)
    samples = parsed_samples[:sample_limit]
    observations, field_meta = observe_topic_fields(samples, options.max_fields_per_topic)
    topic_metadata.append(
      {
        "topic": topic,
        "sample_count": len(samples),
        "parsed_sample_count": len(parsed_samples),
        "omitted_sample_count": max(0, len(parsed_samples) - len(samples)),
        **field_meta,
      }
    )
    matches.extend(ranked_field_matches(path, topic, observations, options.fuzzy, topic_scores.get(topic), source="sample"))

  matches.sort(key=field_match_sort_key)
  limit = max(0, options.limit)
  visible_matches = [compact_match(match) for match in matches[:limit]]
  actual_sampled_topics = [str(row.get("topic")) for row in topic_metadata if row.get("topic")]
  discovery = bounds_metadata(candidate_topics, actual_sampled_topics, options)
  discovery["backend_source"] = "sample" if sampled_topics else "fallback"
  discovery["metadata_probe"] = probe_metadata(metadata_result)
  discovery["needs_sampling"] = bool(candidate_topics and not sampled_topics)
  discovery["sampled_topics"] = topic_metadata
  discovery["omitted_match_count"] = max(0, len(matches) - len(visible_matches))
  file_result = {"path": path, "field_matches": visible_matches, "match_count": len(visible_matches), "field_discovery": discovery}
  return with_backend_metadata(file_result, list_result, backend_reads), blockers


def discover_fields_from_metadata(path: str, zml: Any, options: FieldDiscoveryOptions, metadata_result: BackendResult, records: list[FieldMetadataRecord], topic_probe_result: BackendResult | None = None, present_topics: list[str] | None = None) -> tuple[JsonDict, list[Blocker]]:
  blockers: list[Blocker] = []
  topics = sorted({record.topic for record in records})
  candidate_topics, topic_scores = filter_candidate_topics(topics, options)
  candidate_topics = candidate_topics[: max(0, options.max_topics)]
  candidate_set = set(candidate_topics)
  source = str(metadata_result.metadata.get("source") or metadata_result.metadata.get("selected") or "metadata")
  matches = ranked_metadata_field_matches(path, [record for record in records if record.topic in candidate_set], options.fuzzy, topic_scores, source)
  matches.sort(key=field_match_sort_key)

  backend_reads: list[JsonDict] = []
  sampled_topics: list[str] = []
  topic_metadata: list[JsonDict] = []
  if not options.no_sample and options.sample_top > 0 and matches:
    sampled_topics = unique_topics_from_matches(matches, max(0, options.sample_top))
    sample_observations, sample_metadata, read_blockers, backend_reads = sample_topic_fields(path, zml, sampled_topics, options)
    blockers.extend(read_blockers)
    topic_metadata.extend(sample_metadata)
    apply_sample_observations(matches, sample_observations)
    matches.sort(key=field_match_sort_key)

  limit = max(0, options.limit)
  visible_matches = [compact_match(match) for match in matches[:limit]]
  actual_sampled_topics = [str(row.get("topic")) for row in topic_metadata if row.get("topic")]
  discovery = bounds_metadata(candidate_topics, actual_sampled_topics, options)
  discovery["backend_source"] = metadata_result.metadata.get("source") or metadata_result.metadata.get("selected") or metadata_result.backend or "metadata"
  discovery["metadata_field_count"] = len(records)
  discovery["metadata_probe"] = probe_metadata(metadata_result)
  if topic_probe_result is not None:
    discovery["topic_probe"] = probe_metadata(topic_probe_result)
  if present_topics is not None:
    discovery["present_topic_count"] = len(present_topics)
  discovery["needs_sampling"] = False
  if topic_metadata:
    discovery["sampled_topics"] = topic_metadata
  discovery["omitted_match_count"] = max(0, len(matches) - len(visible_matches))
  file_result = {"path": path, "field_matches": visible_matches, "match_count": len(visible_matches), "field_discovery": discovery}
  return with_backend_metadata(file_result, metadata_result, backend_reads), blockers


def observe_topic_fields(samples: list[Any], max_fields_per_topic: int) -> tuple[dict[str, FieldObservation], JsonDict]:
  observations: dict[str, FieldObservation] = {}
  omitted_field_count = 0
  truncated_sample_count = 0
  field_limit = max(0, max_fields_per_topic)

  for sample in samples:
    flattened, metadata = flatten_field_paths(sample.fields, limit=field_limit + 1)
    if metadata.get("truncated"):
      truncated_sample_count += 1
    for field_path, value in sorted(flattened.items()):
      if field_path not in observations and len(observations) >= field_limit:
        omitted_field_count += 1
        continue
      observation = observations.setdefault(field_path, FieldObservation())
      observation.sample_count += 1
      if observation.example_value is None:
        observation.example_value = safe_example_value(value)

  return observations, compact_dict({"field_count": len(observations), "omitted_field_count": omitted_field_count, "field_scan_truncated_sample_count": truncated_sample_count})


def sample_topic_fields(path: str, zml: Any, topics: list[str], options: FieldDiscoveryOptions) -> tuple[dict[tuple[str, str], FieldObservation], list[JsonDict], list[Blocker], list[JsonDict]]:
  observations_by_key: dict[tuple[str, str], FieldObservation] = {}
  topic_metadata: list[JsonDict] = []
  blockers: list[Blocker] = []
  backend_reads: list[JsonDict] = []

  for topic in topics:
    result = read_topic(zml, path, topic)
    if result.metadata:
      backend_reads.append({"topic": topic, **result.metadata})
    if result.blocker:
      blockers.append(result.blocker)
      topic_metadata.append({"topic": topic, "sample_count": 0, "parsed_sample_count": 0, "omitted_sample_count": 0, "field_count": 0, "omitted_field_count": 0})
      break
    parsed_samples = parse_samples(result.stdout, default_topic=topic)
    if result.stdout.strip() and not parsed_samples:
      blockers.append(Blocker(tool="parser", message=f"zml print output for {topic} was non-empty but no samples could be parsed", guidance="capture a small zml print fixture and extend zml_audit.extract parsing for this output shape"))
    sample_limit = max(0, options.sample_limit)
    samples = parsed_samples[:sample_limit]
    observations, field_meta = observe_topic_fields(samples, options.max_fields_per_topic)
    for field_path, observation in observations.items():
      observations_by_key[(topic, field_path)] = observation
    topic_metadata.append(
      {
        "topic": topic,
        "sample_count": len(samples),
        "parsed_sample_count": len(parsed_samples),
        "omitted_sample_count": max(0, len(parsed_samples) - len(samples)),
        **field_meta,
      }
    )

  return observations_by_key, topic_metadata, blockers, backend_reads


def flatten_field_paths(payload: Any, limit: int = DEFAULT_MAX_FIELDS_PER_TOPIC) -> tuple[JsonDict, JsonDict]:
  fields: JsonDict = {}
  max_fields = max(0, limit)
  truncated = False

  def add(path: str, value: Any) -> None:
    nonlocal truncated
    if not path or path in fields:
      return
    if len(fields) >= max_fields:
      truncated = True
      return
    fields[path] = value

  def walk(value: Any, prefix: str) -> None:
    if truncated:
      return
    if isinstance(value, dict):
      for key in sorted(value):
        walk(value[key], append_component(prefix, str(key)))
        if truncated:
          return
      return
    if isinstance(value, list):
      for index, item in enumerate(value):
        walk(item, append_index(prefix, str(index)))
        if truncated:
          return
        walk(item, append_index(prefix, "*"))
        if truncated:
          return
      return
    add(prefix, value)

  walk(payload, "")
  return fields, {"truncated": True, "limit": max_fields} if truncated else {}


def ranked_metadata_field_matches(path: str, records: list[FieldMetadataRecord], field_query: str, topic_scores: dict[str, FieldScore], default_source: str) -> list[JsonDict]:
  matches: list[JsonDict] = []
  by_topic_source: dict[tuple[str, str, str], dict[str, FieldObservation]] = {}
  for record in records:
    source = record.source or default_source
    by_topic_source.setdefault((record.topic, source, record.topic_presence or "unknown"), {})[record.field_path] = FieldObservation(sample_count=0, example_value=record.example_value)
  for (topic, source, topic_presence), topic_observations in by_topic_source.items():
    matches.extend(ranked_field_matches(path, topic, topic_observations, field_query, topic_scores.get(topic), source=source, topic_presence=topic_presence))
  return matches


def ranked_field_matches(path: str, topic: str, observations: dict[str, FieldObservation], field_query: str, topic_match: FieldScore | None, source: str, topic_presence: str = "present") -> list[JsonDict]:
  matches = []
  normalized_query = field_query.strip().lower()
  for field_path, observation in observations.items():
    field_match = score_field_match(field_path, normalized_query)
    if field_match is None:
      continue
    topic_score = topic_match.score if topic_match else 0.0
    combined_score = min(1.0, field_match.score * (0.95 if topic_match else 1.0) + topic_score * (0.05 if topic_match else 0.0))
    reason = f"field:{field_match.reason}"
    if topic_match:
      reason = f"{reason}; topic:{topic_match.reason}"
    matches.append(
      compact_dict(
        {
          "zml_path": path,
          "topic": topic,
          "field_path": field_path,
          "score": round(combined_score, 3),
          "field_score": round(field_match.score, 3),
          "topic_score": round(topic_score, 3) if topic_match else None,
          "reason": reason,
          "source": source,
          "topic_presence": topic_presence,
          "extractable": topic_presence == "present" or observation.sample_count > 0,
          "confidence": confidence_for(field_match, source, topic_presence),
          "needs_sampling": topic_presence == "unknown" and source == "schema",
          "sample_count": observation.sample_count,
          "example_value": observation.example_value,
        }
      )
    )
  return matches


def apply_sample_observations(matches: list[JsonDict], observations: dict[tuple[str, str], FieldObservation]) -> None:
  for match in matches:
    observation = observations.get((str(match.get("topic")), str(match.get("field_path"))))
    if not observation:
      continue
    current_source = str(match.get("source") or "metadata")
    match["source"] = current_source if current_source.endswith("+sample") else f"{current_source}+sample"
    match["topic_presence"] = "present"
    match["extractable"] = True
    match["needs_sampling"] = False
    match["sample_count"] = observation.sample_count
    if observation.example_value is not None:
      match["example_value"] = observation.example_value


def confidence_for(field_match: FieldScore, source: str, topic_presence: str = "unknown") -> str:
  if topic_presence == "not_present":
    return "low"
  if field_match.score >= 0.95 and source in {"metadata", "metadata+sample"}:
    return "high"
  if field_match.score >= 0.9:
    return "high"
  return "medium"


def score_field_match(field_path: str, normalized_query: str) -> FieldScore | None:
  if not normalized_query:
    return None
  normalized_path = field_path.lower()
  basename = normalized_path.rsplit(".", 1)[-1]
  candidates: list[FieldScore] = []
  if normalized_query in {normalized_path, basename}:
    candidates.append(FieldScore(1.0, "exact"))
  if normalized_query in basename:
    candidates.append(FieldScore(0.95, "basename_substring"))
  elif normalized_query in normalized_path:
    candidates.append(FieldScore(0.9, "path_substring"))

  query_tokens = topic_tokens(normalized_query)
  field_tokens = path_tokens(normalized_path)
  if query_tokens and field_tokens:
    overlap = len(set(query_tokens) & set(field_tokens)) / len(set(query_tokens))
    if overlap > 0:
      candidates.append(FieldScore(0.72 + 0.18 * overlap, "token_overlap"))
    approximate = approximate_token_score(query_tokens, field_tokens)
    if approximate >= 0.72:
      candidates.append(FieldScore(0.45 + 0.35 * approximate, "approximate"))

  full_similarity = difflib.SequenceMatcher(None, normalized_query, normalized_path).ratio()
  if full_similarity >= 0.5:
    candidates.append(FieldScore(0.35 + 0.35 * full_similarity, "approximate"))
  if not candidates:
    return None
  best = max(candidates, key=lambda candidate: candidate.score)
  return best if best.score >= 0.4 else None


def filter_candidate_topics(topics: list[str], options: FieldDiscoveryOptions) -> tuple[list[str], dict[str, FieldScore]]:
  patterns = compile_patterns(options.topic_regex)
  exact_topics = set(options.topic)
  candidates = []
  for topic in topics:
    if exact_topics and topic not in exact_topics:
      continue
    if options.topic_contains and not all(value in topic for value in options.topic_contains):
      continue
    if patterns and not all(pattern.search(topic) for pattern in patterns):
      continue
    candidates.append(topic)

  topic_scores: dict[str, FieldScore] = {}
  if exact_topics:
    topic_scores.update({topic: FieldScore(1.0, "explicit_topic") for topic in candidates})
  if options.topic_contains:
    topic_scores.update({topic: FieldScore(max(topic_scores.get(topic, FieldScore(0.0, "")).score, 0.75), "topic_substring") for topic in candidates})
  if options.topic_regex:
    topic_scores.update({topic: FieldScore(max(topic_scores.get(topic, FieldScore(0.0, "")).score, 0.75), "topic_regex") for topic in candidates})
  if options.topic_fuzzy:
    fuzzy_matches = fuzzy_topic_matches(candidates, options.topic_fuzzy, limit=len(candidates))
    candidates = [match.topic for match in fuzzy_matches]
    topic_scores.update({match.topic: FieldScore(match.score, match.reason) for match in fuzzy_matches})
  return candidates, topic_scores


def bounds_metadata(candidate_topics: list[str], sampled_topics: list[str], options: FieldDiscoveryOptions) -> JsonDict:
  omitted_topics = candidate_topics[len(sampled_topics) :]
  return {
    "bounds": {
      "max_topics_sampled": max(0, options.max_topics_sampled),
      "max_topics": max(0, options.max_topics),
      "sample_top": max(0, options.sample_top),
      "sample_limit_per_topic": max(0, options.sample_limit),
      "max_fields_per_topic": max(0, options.max_fields_per_topic),
      "match_limit": max(0, options.limit),
      "no_sample": options.no_sample,
    },
    "candidate_topic_count": len(candidate_topics),
    "sampled_topic_count": len(sampled_topics),
    "omitted_topic_count": len(omitted_topics),
    "omitted_topics": omitted_topics[:10],
  }


def fallback_sample_topic_count(options: FieldDiscoveryOptions) -> int:
  if options.no_sample:
    return 0
  if options.sample_top > 0:
    return min(max(0, options.sample_top), max(0, options.max_topics_sampled))
  if options.topic or options.topic_contains or options.topic_regex or options.topic_fuzzy:
    return max(0, options.max_topics_sampled)
  return 0


def read_field_metadata(zml: Any, path: str) -> BackendResult:
  for method_name in ("field_metadata", "list_field_metadata"):
    method = getattr(zml, method_name, None)
    if callable(method):
      return method(path)
  return BackendResult(blocker=Blocker(tool="metadata", message="backend does not expose field metadata discovery"), backend="metadata", metadata={"selected": "metadata", "operation": "field metadata", "unsupported_operation": True})


def schema_metadata_records(path: str, present_topics: list[str] | None = None) -> list[FieldMetadataRecord]:
  try:
    from .raw import TOPIC_SCHEMAS
  except Exception:
    return []
  records: list[FieldMetadataRecord] = []

  if present_topics is not None:
    present_set = set(present_topics)
    for topic in present_topics:
      schema = TOPIC_SCHEMAS.get(topic)
      if schema:
        records.extend(FieldMetadataRecord(topic, str(field), source="schema", topic_presence="present") for field in schema.get("fields") or ())
    for topic, schema in TOPIC_SCHEMAS.items():
      if topic in present_set or not topic_likely_in_path(path, topic):
        continue
      records.extend(FieldMetadataRecord(topic, str(field), source="schema", topic_presence="not_present") for field in schema.get("fields") or ())
    return records

  for topic, schema in TOPIC_SCHEMAS.items():
    if not topic_likely_in_path(path, topic):
      continue
    records.extend(FieldMetadataRecord(topic, str(field), source="schema") for field in schema.get("fields") or ())
  return records


def schema_metadata_probe(systems_root: str | None) -> JsonDict:
  systems_available = bool(systems_root and Path(systems_root).exists())
  return {
    "selected": "raw-schema",
    "source": "schema",
    "operation": "field metadata",
    "systems_root": systems_root,
    "cwd": systems_root if systems_available else None,
    "systems_root_available": systems_available,
  }


def merge_metadata_records(primary: list[FieldMetadataRecord], supplemental: list[FieldMetadataRecord]) -> list[FieldMetadataRecord]:
  merged = list(primary)
  seen = {(record.topic, record.field_path) for record in merged}
  for record in supplemental:
    key = (record.topic, record.field_path)
    if key not in seen:
      seen.add(key)
      merged.append(record)
  return merged


def mark_records_topic_presence(records: list[FieldMetadataRecord], present_topics: list[str] | None) -> list[FieldMetadataRecord]:
  if present_topics is None:
    return records
  present_set = set(present_topics)
  return [replace(record, topic_presence="present" if record.topic in present_set else "not_present") for record in records]


def topic_likely_in_path(path: str, topic: str) -> bool:
  head = topic.lstrip("/").split(".", 1)[0].lower()
  lowered = path.lower()
  return bool(head and (f"/{head}/" in lowered or f"/{head}.zml" in lowered or f"/{head}.zml.zst" in lowered))


def probe_metadata(result: BackendResult) -> JsonDict:
  probe = dict(result.metadata or {})
  if result.blocker:
    probe["blocker"] = result.blocker.to_dict()
  return compact_dict(probe)


def parse_field_metadata(text: str, max_fields_per_topic: int) -> list[FieldMetadataRecord]:
  stripped = text.strip()
  if not stripped:
    return []
  records: list[FieldMetadataRecord] = []
  try:
    decoded = json.loads(stripped)
  except json.JSONDecodeError:
    for line in stripped.splitlines():
      records.extend(parse_metadata_line(line, max_fields_per_topic))
    return records
  records.extend(records_from_metadata_value(decoded, None, max_fields_per_topic))
  return records


def parse_metadata_line(line: str, max_fields_per_topic: int) -> list[FieldMetadataRecord]:
  stripped = line.strip()
  if not stripped or stripped.startswith("#"):
    return []
  try:
    decoded = json.loads(stripped)
  except json.JSONDecodeError:
    parts = stripped.split()
    key_values = dict(part.split("=", 1) for part in parts if "=" in part)
    topic = key_values.get("topic") or key_values.get("identifier") or (parts[0] if parts and parts[0].startswith("/") else "")
    field = key_values.get("field") or key_values.get("field_path") or (parts[1] if len(parts) > 1 and topic else "")
    return [FieldMetadataRecord(topic, field)] if topic and field else []
  return records_from_metadata_value(decoded, None, max_fields_per_topic)


def records_from_metadata_value(value: Any, topic: str | None, max_fields_per_topic: int) -> list[FieldMetadataRecord]:
  if isinstance(value, list):
    records: list[FieldMetadataRecord] = []
    for item in value:
      records.extend(records_from_metadata_value(item, topic, max_fields_per_topic))
    return records
  if not isinstance(value, dict):
    return []

  current_topic = str(value.get("topic") or value.get("name") or value.get("identifier") or topic or "")
  if value.get("field_path") or value.get("field"):
    field_path = str(value.get("field_path") or value.get("field"))
    return [FieldMetadataRecord(current_topic, field_path, safe_example_value(value.get("example_value")))] if current_topic and field_path else []

  records: list[FieldMetadataRecord] = []
  for key in ("topics", "streams"):
    records.extend(records_from_metadata_value(value.get(key), current_topic, max_fields_per_topic))
  fields = value.get("fields") or value.get("field_paths") or value.get("schema")
  if current_topic and fields:
    records.extend(FieldMetadataRecord(current_topic, field_path, example) for field_path, example in metadata_field_paths(fields, max_fields_per_topic))
  return records


def metadata_field_paths(value: Any, max_fields_per_topic: int) -> list[tuple[str, Any]]:
  limit = max(0, max_fields_per_topic)
  paths: list[tuple[str, Any]] = []

  def add(path: str, example: Any = None) -> None:
    if path and len(paths) < limit:
      paths.append((path, safe_example_value(example)))

  def walk(item: Any, prefix: str = "") -> None:
    if len(paths) >= limit:
      return
    if isinstance(item, str):
      add(item)
    elif isinstance(item, list):
      for child in item:
        walk(child, prefix)
    elif isinstance(item, dict):
      field_name = item.get("path") or item.get("field_path") or item.get("name") or item.get("field")
      if isinstance(field_name, str) and ("type" in item or "example_value" in item or "field_path" in item or "path" in item):
        add(append_component(prefix, field_name) if prefix and "." not in field_name else field_name, item.get("example_value"))
        return
      for key, child in sorted(item.items()):
        if key in {"type", "example_value"}:
          continue
        walk(child, append_component(prefix, str(key)))

  walk(value)
  return paths


def unique_topics_from_matches(matches: list[JsonDict], limit: int) -> list[str]:
  topics: list[str] = []
  seen: set[str] = set()
  for match in matches:
    topic = str(match.get("topic") or "")
    if topic and topic not in seen:
      seen.add(topic)
      topics.append(topic)
    if len(topics) >= limit:
      break
  return topics


def parse_topic_list(text: str) -> list[str]:
  topics = []
  for line in text.splitlines():
    stripped = line.strip()
    if stripped and not stripped.startswith("#"):
      topics.append(stripped.split()[0])
  return topics


def probe_present_topics(zml: Any, path: str) -> tuple[BackendResult | None, list[str] | None]:
  list_topics = getattr(zml, "list_topics", None)
  if not callable(list_topics):
    return None, None
  try:
    result = list_topics(path)
  except Exception:
    return None, None
  if result.blocker:
    return result, None
  return result, parse_topic_list(result.stdout)


def field_match_sort_key(match: JsonDict) -> tuple[float, float, float, float, int, str, str]:
  presence_rank = {"present": 2.0, "unknown": 1.0, "not_present": 0.0}.get(str(match.get("topic_presence") or "unknown"), 1.0)
  extractable_rank = 1.0 if match.get("extractable") else 0.0
  return (-extractable_rank, -presence_rank, -float(match.get("field_score") or match.get("score") or 0), -float(match.get("topic_score") or 0), -int(match.get("sample_count") or 0), str(match.get("topic") or ""), str(match.get("field_path") or ""))


def read_topic(zml: Any, path: str, topic: str) -> BackendResult:
  if hasattr(zml, "read_topic"):
    return zml.read_topic(path, topic, TimeWindow())
  return zml.print_topic(path, topic)


def with_backend_metadata(file_result: JsonDict, list_result: BackendResult, reads: list[JsonDict]) -> JsonDict:
  metadata = compact_dict({"list_topics": list_result.metadata, "reads": reads})
  if metadata:
    file_result["backend"] = metadata
  return file_result


def compact_match(match: JsonDict) -> JsonDict:
  return {key: value for key, value in match.items() if key not in {"field_score", "topic_score"} and value not in (None, [], {}, ())}


def compile_patterns(regexes: tuple[str, ...]) -> list[re.Pattern[str]]:
  patterns = []
  for raw in regexes:
    try:
      patterns.append(re.compile(raw))
    except re.error as exc:
      raise ValueError(f"invalid --topic-regex {raw!r}: {exc}") from exc
  return patterns


def path_tokens(value: str) -> list[str]:
  return [part for part in re.split(r"[/._:\-+\s\[\]\*]+", value.strip().lower()) if part and not part.isdigit()]


def append_component(prefix: str, key: str) -> str:
  return f"{prefix}.{key}" if prefix else key


def append_index(prefix: str, index: str) -> str:
  return f"{prefix}[{index}]" if prefix else f"[{index}]"


def safe_example_value(value: Any) -> Any:
  if value is None or isinstance(value, (bool, int, float)):
    return value
  if isinstance(value, str) and len(value) <= 120:
    return value
  return None
