from __future__ import annotations

from typing import Any, Iterable

from .models import FieldStats, JsonDict, Sample, TopicSpec, TopicSummary, numeric_value


def summarize_topic(topic: TopicSpec, samples: Iterable[Sample], transition_limit: int = 5) -> TopicSummary:
  ordered = sorted(samples, key=lambda sample: sample.timestamp)
  if not ordered:
    return TopicSummary(topic=topic.name, present=False)
  first_timestamp = ordered[0].timestamp
  last_timestamp = ordered[-1].timestamp
  duration = last_timestamp - first_timestamp
  rate = (len(ordered) - 1) / duration if duration > 0 and len(ordered) > 1 else None
  field_names = topic_field_names(topic, ordered)
  return TopicSummary(
    topic=topic.name,
    present=True,
    sample_count=len(ordered),
    first_timestamp=first_timestamp,
    last_timestamp=last_timestamp,
    approximate_rate_hz=rate,
    fields={name: summarize_field(name, ordered, transition_limit) for name in field_names},
  )


def topic_field_names(topic: TopicSpec, samples: list[Sample]) -> list[str]:
  expanded = sorted({key for sample in samples for key in sample.fields})
  if not topic.fields:
    return expanded
  requested_exact = [field for field in topic.fields if "*" not in field]
  return sorted(set(requested_exact) | set(expanded))


def summarize_field(name: str, samples: list[Sample], transition_limit: int = 5) -> FieldStats:
  values = [sample.fields.get(name) for sample in samples]
  present_values = [value for value in values if value is not None]
  numeric_values = [number for value in present_values if (number := numeric_value(value)) is not None]
  first = present_values[0] if present_values else None
  last = present_values[-1] if present_values else None
  return FieldStats(
    name=name,
    count=len(present_values),
    missing_count=len(values) - len(present_values),
    first=first,
    last=last,
    min=min(numeric_values) if numeric_values else None,
    max=max(numeric_values) if numeric_values else None,
    mean=sum(numeric_values) / len(numeric_values) if numeric_values else None,
    transition_count=count_transitions(present_values),
    transition_details=transition_details(name, samples, transition_limit),
  )


def count_transitions(values: list[Any]) -> int:
  if not values:
    return 0
  transitions = 0
  previous = values[0]
  for value in values[1:]:
    if value != previous:
      transitions += 1
      previous = value
  return transitions


def transition_details(name: str, samples: list[Sample], limit: int) -> list[JsonDict]:
  if limit <= 0:
    return []
  details: list[JsonDict] = []
  previous: Any = None
  have_previous = False
  for sample in samples:
    value = sample.fields.get(name)
    if value is None:
      continue
    if have_previous and value != previous:
      details.append({"timestamp": sample.timestamp, "from_value": previous, "to_value": value})
      if len(details) >= limit:
        break
    previous = value
    have_previous = True
  return details
