from __future__ import annotations

import importlib
import json
import re
import sys
from typing import Any

from .models import Blocker, JsonDict, TimeWindow, compact_dict


TOPIC_SCHEMAS: dict[str, JsonDict] = {
  "/compute_a.zip_executive.cloud_bound_status": {
    "module": "cloud_protos.zip_executive.executive_interfaces_pb2",
    "message": "ExecutiveStatus",
    "fields": ("flight_phase_for_controller",),
  },
  "/SIL.zip_executive.cloud_bound_status": {
    "module": "cloud_protos.zip_executive.executive_interfaces_pb2",
    "message": "ExecutiveStatus",
    "fields": ("flight_phase_for_controller",),
  },
}


def decode_print_raw_stdout(text: str, topic: str, fields: tuple[str, ...], window: TimeWindow) -> tuple[str, Blocker | None]:
  schema = TOPIC_SCHEMAS.get(topic)
  if not schema:
    return "", Blocker(tool="zml-print-raw", message=f"raw protobuf fallback has no schema mapping for topic {topic}", guidance="use a decoded backend or add a reviewed topic-to-protobuf schema mapping")
  if not fields:
    return "", Blocker(tool="zml-print-raw", message="raw protobuf fallback requires explicit requested fields", guidance="pass --field for schema-aware raw decoding")
  unsupported_fields = [field for field in fields if field not in set(schema.get("fields") or ())]
  if unsupported_fields:
    return "", Blocker(tool="zml-print-raw", message=f"raw protobuf fallback has no reviewed field mapping for {topic}: {', '.join(unsupported_fields)}", guidance="use decoded output or add a reviewed field mapping before raw decoding")

  message_class, blocker = load_message_class(str(schema["module"]), str(schema["message"]))
  if blocker:
    return "", blocker

  rows = []
  for line in text.splitlines():
    parsed = parse_print_raw_line(line)
    if not parsed or parsed["topic"] != topic or not window.normalized().contains(parsed["timestamp"]):
      continue
    message = message_class()
    try:
      message.ParseFromString(bytes.fromhex(str(parsed["payload_hex"])))
    except Exception as exc:
      return "", Blocker(tool="zml-print-raw", message=f"raw protobuf payload decode failed for {topic}", stderr_excerpt=str(exc)[:500])
    values, value_blocker = extract_proto_fields(message, fields, topic)
    if value_blocker:
      return "", value_blocker
    rows.append(json.dumps({"topic": topic, "timestamp": parsed["timestamp"], "fields": values}))
  return "\n".join(rows) + ("\n" if rows else ""), None


def parse_print_raw_line(line: str) -> JsonDict | None:
  match = re.match(r"^#\S+\s+@(?P<timestamp>\S+)\s+(?:\S+\s+)?(?P<topic>/\S+)\s+(?P<payload>[0-9A-Fa-f\s]+)$", line.strip())
  if not match:
    return None
  try:
    timestamp = float(match.group("timestamp"))
  except ValueError:
    return None
  return {"timestamp": timestamp, "topic": match.group("topic"), "payload_hex": "".join(match.group("payload").split())}


def load_message_class(module_name: str, class_name: str) -> tuple[Any | None, Blocker | None]:
  try:
    module = importlib.import_module(module_name)
    message_class = getattr(module, class_name)
  except Exception as exc:
    try:
      module = import_schema_without_systems_shadow(module_name)
      message_class = getattr(module, class_name)
    except Exception as retry_exc:
      return None, Blocker(tool="zml-print-raw", message=f"raw protobuf schema is not importable: {module_name}.{class_name}", guidance="run from an environment with generated cloud_protos available or use a decoded backend", stderr_excerpt=f"{exc}; retry_without_/Systems={retry_exc}"[:500])
  return message_class, None


def import_schema_without_systems_shadow(module_name: str) -> Any:
  original_path = list(sys.path)
  sys.path = [path for path in sys.path if path != "/Systems"]
  try:
    for name in list(sys.modules):
      if name == "cloud_protos" or name.startswith("cloud_protos."):
        del sys.modules[name]
    return importlib.import_module(module_name)
  finally:
    sys.path = original_path


def extract_proto_fields(message: Any, fields: tuple[str, ...], topic: str) -> tuple[JsonDict, Blocker | None]:
  values: JsonDict = {}
  descriptors = getattr(getattr(message, "DESCRIPTOR", None), "fields_by_name", {})
  for field in fields:
    descriptor = descriptors.get(field)
    if descriptor is None:
      return {}, Blocker(tool="zml-print-raw", message=f"raw protobuf message for {topic} does not expose requested field {field}", guidance="verify the exact protobuf field name or use decoded output")
    try:
      value = getattr(message, field)
    except Exception as exc:
      return {}, Blocker(tool="zml-print-raw", message=f"raw protobuf field extraction failed for {field}", stderr_excerpt=str(exc)[:500])
    values[field] = enum_name(descriptor, value)
  return compact_dict(values), None


def enum_name(descriptor: Any, value: Any) -> Any:
  enum_type = getattr(descriptor, "enum_type", None)
  if enum_type is None:
    return value
  enum_value = getattr(enum_type, "values_by_number", {}).get(int(value))
  return getattr(enum_value, "name", value)
