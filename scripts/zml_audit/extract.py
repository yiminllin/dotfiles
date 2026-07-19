from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from .models import JsonDict, Sample, TimeWindow, TopicSpec, numeric_value


TIMESTAMP_KEYS = ("timestamp", "log_ts", "time", "ts", "t")
NANOSECOND_TIMESTAMP_KEYS = ("log_monotonic_ns", "log_realtime_gps_ns", "receive_time_ns")
GPS_EPOCH_SECONDS_KEY = "gps_epoch_time.seconds"
GPS_EPOCH_FRACTION_KEY = "gps_epoch_time.fraction"
TOPIC_KEYS = ("topic", "channel", "identifier")
MAX_EXPANDED_FIELDS_PER_SAMPLE = 1000


def parse_samples(text: str, default_topic: str | None = None, fields: Iterable[str] = ()) -> list[Sample]:
  rows = parse_json_rows(text)
  if rows is None:
    rows = parse_zml_print_rows(text)
  if rows is None:
    rows = parse_text_rows(text, default_topic)
  wanted_fields = tuple(fields)
  samples: list[Sample] = []
  for row in rows:
    sample = sample_from_row(row, default_topic, wanted_fields)
    if sample is not None:
      samples.append(sample)
  return samples


def filter_samples(samples: Iterable[Sample], topic: TopicSpec, window: TimeWindow) -> list[Sample]:
  normalized = window.normalized()
  return [sample for sample in samples if sample.topic == topic.name and normalized.contains(sample.timestamp)]


def parse_timestamp(raw: Any) -> float | None:
  if raw is None:
    return None
  number = numeric_value(raw)
  if number is not None:
    return number
  if not isinstance(raw, str):
    return None
  text = raw.strip()
  if text.endswith("Z"):
    text = text[:-1] + "+00:00"
  try:
    parsed = datetime.fromisoformat(text)
  except ValueError:
    return None
  if parsed.tzinfo is None:
    parsed = parsed.replace(tzinfo=timezone.utc)
  return parsed.timestamp()


def parse_time_arg(raw: str | None) -> float | None:
  if raw is None:
    return None
  timestamp = parse_timestamp(raw)
  if timestamp is None:
    raise ValueError(f"invalid timestamp: {raw}")
  return timestamp


def parse_json_rows(text: str) -> list[JsonDict] | None:
  stripped = text.strip()
  if not stripped:
    return []
  try:
    value = json.loads(stripped)
  except json.JSONDecodeError:
    return parse_json_lines(text)
  if isinstance(value, list):
    return [row for row in value if isinstance(row, dict)]
  if isinstance(value, dict):
    if isinstance(value.get("samples"), list):
      return [row for row in value["samples"] if isinstance(row, dict)]
    return [value]
  return None


def parse_json_lines(text: str) -> list[JsonDict] | None:
  rows: list[JsonDict] = []
  saw_json = False
  for line in text.splitlines():
    stripped = line.strip()
    if not stripped:
      continue
    try:
      value = json.loads(stripped)
    except json.JSONDecodeError:
      if saw_json:
        continue
      return None
    if isinstance(value, dict):
      rows.append(value)
      saw_json = True
  return rows if saw_json else None


def parse_text_rows(text: str, default_topic: str | None) -> list[JsonDict]:
  rows = []
  for line in text.splitlines():
    fields = parse_key_value_tokens(line)
    if not fields:
      continue
    if "topic" not in fields and default_topic:
      fields["topic"] = default_topic
    rows.append(fields)
  return rows


def parse_zml_print_rows(text: str) -> list[JsonDict] | None:
  rows: list[JsonDict] = []
  saw_zml_line = False
  for line in text.splitlines():
    stripped = line.strip()
    if not stripped:
      continue
    match = re.match(r"^#\S+\s+@(?P<timestamp>\S+)(?:\s+~?[^/\s]+)?\s+(?P<topic>/\S+)\s+(?P<payload>.*)$", stripped)
    if not match:
      continue
    saw_zml_line = True
    try:
      payload = ast.literal_eval(match.group("payload"))
    except (SyntaxError, ValueError):
      continue
    if isinstance(payload, dict):
      rows.append({"timestamp": match.group("timestamp"), "topic": match.group("topic"), "fields": payload})
  if rows:
    return rows
  return [] if saw_zml_line else None


def parse_key_value_tokens(line: str) -> JsonDict:
  values: JsonDict = {}
  tokens = line.strip().split()
  if not tokens:
    return values
  if "=" not in tokens[0]:
    timestamp = parse_timestamp(tokens[0])
    if timestamp is not None:
      values["timestamp"] = timestamp
      tokens = tokens[1:]
  for token in tokens:
    match = re.match(r"([^=]+)=(.*)", token.rstrip(","))
    if not match:
      continue
    key, value = match.groups()
    values[key] = coerce_scalar(value.strip('"'))
  return values


def sample_from_row(row: JsonDict, default_topic: str | None, wanted_fields: tuple[str, ...]) -> Sample | None:
  topic = first_value(row, TOPIC_KEYS) or default_topic
  timestamp, timestamp_metadata = timestamp_from_row(row)
  if not topic or timestamp is None:
    return None
  payload = row.get("fields") if isinstance(row.get("fields"), dict) else row.get("data") if isinstance(row.get("data"), dict) else row
  fields, metadata = extract_fields_with_metadata(payload, wanted_fields)
  metadata = {**timestamp_metadata, **metadata}
  return Sample(topic=str(topic), timestamp=timestamp, fields=fields, raw=row, metadata=metadata)


def timestamp_from_row(row: JsonDict) -> tuple[float | None, JsonDict]:
  for key in TIMESTAMP_KEYS:
    if key not in row:
      continue
    timestamp = parse_timestamp(row[key])
    if timestamp is not None:
      return timestamp, {}

  for key in NANOSECOND_TIMESTAMP_KEYS:
    if key not in row:
      continue
    timestamp_ns = numeric_value(row[key])
    if timestamp_ns is not None:
      return timestamp_ns / 1_000_000_000.0, {"timestamp_source": key, "timestamp_unit": "ns", "timebase": key[:-3]}

  gps_epoch_seconds = numeric_value(row.get(GPS_EPOCH_SECONDS_KEY))
  if gps_epoch_seconds is not None:
    gps_epoch_fraction = numeric_value(row.get(GPS_EPOCH_FRACTION_KEY)) or 0.0
    return gps_epoch_seconds + gps_epoch_fraction, {"timestamp_source": "gps_epoch_time", "timebase": "gps_epoch_time"}

  return None, {}


def extract_fields(payload: JsonDict, wanted_fields: tuple[str, ...]) -> JsonDict:
  fields, _ = extract_fields_with_metadata(payload, wanted_fields)
  return fields


def extract_fields_with_metadata(payload: JsonDict, wanted_fields: tuple[str, ...]) -> tuple[JsonDict, JsonDict]:
  if wanted_fields:
    fields: JsonDict = {}
    for path in wanted_fields:
      for concrete_path, value in expand_field_path(payload, path):
        if len(fields) >= MAX_EXPANDED_FIELDS_PER_SAMPLE:
          return fields, {"field_expansion_truncated": True, "expanded_field_limit": MAX_EXPANDED_FIELDS_PER_SAMPLE}
        fields[concrete_path] = value
    return fields, {}
  return {key: value for key, value in payload.items() if key not in TIMESTAMP_KEYS and key not in TOPIC_KEYS}, {}


MISSING = object()


def expand_field_path(payload: JsonDict, path: str) -> list[tuple[str, Any]]:
  if path in payload:
    return [(path, payload[path])]
  return sorted(_expand_parts(payload, split_field_path(path), "", MAX_EXPANDED_FIELDS_PER_SAMPLE + 1), key=lambda item: item[0])


def field_path_value(payload: JsonDict, path: str) -> Any:
  matches = expand_field_path(payload, path)
  if len(matches) != 1 or matches[0][0] != path:
    return MISSING
  return matches[0][1]


def split_field_path(path: str) -> list[str]:
  return [part for part in path.split(".") if part]


def _expand_parts(current: Any, parts: list[str], prefix: str, limit: int) -> list[tuple[str, Any]]:
  if limit <= 0:
    return []
  if not parts:
    return [(prefix, current)] if prefix else []
  matches: list[tuple[str, Any]] = []
  seen_paths: set[str] = set()
  for part_count in range(len(parts), 0, -1):
    head = ".".join(parts[:part_count])
    rest = parts[part_count:]
    for _, value, concrete in resolve_part(current, head):
      next_prefix = append_path(prefix, concrete)
      for match in _expand_parts(value, rest, next_prefix, limit - len(matches)):
        if match[0] in seen_paths:
          continue
        matches.append(match)
        seen_paths.add(match[0])
        if len(matches) >= limit:
          return matches[:limit]
  return matches


def resolve_part(current: Any, part: str) -> list[tuple[str | int, Any, str]]:
  base_match = re.fullmatch(r"([^\[]*)(?:\[(\*|\d+)\])?", part)
  if not base_match:
    return []
  key, index = base_match.groups()
  values: list[tuple[str | int, Any, str]]
  if key == "*":
    if not isinstance(current, dict):
      return []
    values = [(dict_key, current[dict_key], str(dict_key)) for dict_key in sorted(current)]
  elif key:
    if not isinstance(current, dict) or key not in current:
      return []
    values = [(key, current[key], key)]
  else:
    values = [("", current, "")]

  if index is None:
    return values

  indexed: list[tuple[str | int, Any, str]] = []
  for _, value, concrete in values:
    if not isinstance(value, list):
      continue
    if index == "*":
      indexed.extend((item_index, item, f"{concrete}[{item_index}]") for item_index, item in enumerate(value))
      continue
    item_index = int(index)
    if 0 <= item_index < len(value):
      indexed.append((item_index, value[item_index], f"{concrete}[{item_index}]"))
  return indexed


def append_path(prefix: str, part: str) -> str:
  if not prefix:
    return part
  if part.startswith("["):
    return f"{prefix}{part}"
  return f"{prefix}.{part}"


def first_value(row: JsonDict, keys: Iterable[str]) -> Any:
  for key in keys:
    if key in row:
      return row[key]
  return None


def coerce_scalar(raw: str) -> Any:
  if raw.lower() in {"true", "false"}:
    return raw.lower() == "true"
  number = numeric_value(raw)
  return number if number is not None else raw
