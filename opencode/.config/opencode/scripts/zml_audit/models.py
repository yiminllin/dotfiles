from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from typing import Any


JsonDict = dict[str, Any]


@dataclass(frozen=True)
class Blocker:
  tool: str
  message: str
  command: str | None = None
  guidance: str | None = None
  returncode: int | None = None
  stderr_excerpt: str | None = None

  def to_dict(self) -> JsonDict:
    return compact_dict(self.__dict__)


@dataclass(frozen=True)
class TimeWindow:
  start: float | None = None
  end: float | None = None
  center: float | None = None
  duration: float | None = None

  def normalized(self) -> TimeWindow:
    start = self.start
    end = self.end
    if self.center is not None and self.duration is not None:
      half = self.duration / 2.0
      if start is None:
        start = self.center - half
      if end is None:
        end = self.center + half
    return TimeWindow(start=start, end=end, center=self.center, duration=self.duration)

  def contains(self, timestamp: float | None) -> bool:
    if timestamp is None:
      return False
    window = self.normalized()
    if window.start is not None and timestamp < window.start:
      return False
    if window.end is not None and timestamp > window.end:
      return False
    return True

  def to_dict(self) -> JsonDict:
    return compact_dict(self.normalized().__dict__)


@dataclass(frozen=True)
class TopicSpec:
  name: str
  fields: tuple[str, ...] = ()

  def to_dict(self) -> JsonDict:
    return compact_dict({"name": self.name, "fields": list(self.fields)})


@dataclass(frozen=True)
class SourceResolution:
  input: str
  kind: str
  candidates: tuple[str, ...] = ()
  blockers: tuple[Blocker, ...] = ()

  def to_dict(self) -> JsonDict:
    return compact_dict(
      {
        "input": self.input,
        "kind": self.kind,
        "candidates": list(self.candidates),
        "blockers": [blocker.to_dict() for blocker in self.blockers],
      }
    )


@dataclass(frozen=True)
class Sample:
  topic: str
  timestamp: float
  fields: JsonDict = field(default_factory=dict)
  raw: JsonDict = field(default_factory=dict)
  metadata: JsonDict = field(default_factory=dict)

  def to_dict(self) -> JsonDict:
    return compact_dict({"topic": self.topic, "timestamp": self.timestamp, "fields": self.fields, "metadata": self.metadata})


@dataclass(frozen=True)
class FieldStats:
  name: str
  count: int = 0
  missing_count: int = 0
  first: Any = None
  last: Any = None
  min: float | None = None
  max: float | None = None
  mean: float | None = None
  transition_count: int = 0
  transition_details: list[JsonDict] = field(default_factory=list)

  def to_dict(self) -> JsonDict:
    return compact_dict(
      {
        "count": self.count,
        "missing_count": self.missing_count,
        "first": self.first,
        "last": self.last,
        "min": self.min,
        "max": self.max,
        "mean": self.mean,
        "transition_count": self.transition_count,
        "transition_details": self.transition_details,
      }
    )


@dataclass(frozen=True)
class TopicSummary:
  topic: str
  present: bool
  sample_count: int = 0
  first_timestamp: float | None = None
  last_timestamp: float | None = None
  approximate_rate_hz: float | None = None
  fields: dict[str, FieldStats] = field(default_factory=dict)

  def to_dict(self) -> JsonDict:
    return compact_dict(
      {
        "topic": self.topic,
        "present": self.present,
        "sample_count": self.sample_count,
        "first_timestamp": self.first_timestamp,
        "last_timestamp": self.last_timestamp,
        "approximate_rate_hz": self.approximate_rate_hz,
        "fields": {name: stats.to_dict() for name, stats in sorted(self.fields.items())},
      }
    )


def compact_dict(values: JsonDict) -> JsonDict:
  return {key: value for key, value in values.items() if value not in (None, [], {}, ())}


def utc_now() -> str:
  return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def numeric_value(value: Any) -> float | None:
  if isinstance(value, bool) or value is None:
    return None
  if isinstance(value, (int, float)):
    number = float(value)
  elif isinstance(value, str):
    try:
      number = float(value)
    except ValueError:
      return None
  else:
    return None
  return number if isfinite(number) else None
