from __future__ import annotations

from .models import FieldStats, JsonDict, Sample, TopicSummary, numeric_value


def compare_runs(
  fail: dict[str, TopicSummary],
  passing: dict[str, TopicSummary],
  fail_samples: dict[str, list[Sample]],
  pass_samples: dict[str, list[Sample]],
  time_tolerance: float = 0.0,
  numeric_tolerance: float = 0.0,
) -> JsonDict:
  topics = sorted(set(fail) | set(passing))
  missing_in_fail = [topic for topic in topics if not fail.get(topic) or not fail[topic].present]
  missing_in_pass = [topic for topic in topics if not passing.get(topic) or not passing[topic].present]
  rows = [compare_topic(fail[topic], passing[topic]) for topic in topics if topic in fail and topic in passing]
  alignments = [timestamp_alignment(topic, fail_samples.get(topic, []), pass_samples.get(topic, []), time_tolerance) for topic in topics]
  divergences = [first_divergence(topic, fail_samples.get(topic, []), pass_samples.get(topic, []), time_tolerance, numeric_tolerance) for topic in topics]
  return {
    "tolerances": {"time": time_tolerance, "numeric": numeric_tolerance},
    "missing_in_fail": missing_in_fail,
    "missing_in_pass": missing_in_pass,
    "timestamp_alignment": [row for row in alignments if row],
    "topics": [row for row in rows if row],
    "first_divergences": [row for row in divergences if row],
  }


def compare_topic(fail: TopicSummary, passing: TopicSummary) -> JsonDict:
  fields = sorted(set(fail.fields) | set(passing.fields))
  return {
    "topic": fail.topic,
    "fail_present": fail.present,
    "pass_present": passing.present,
    "sample_count_delta": fail.sample_count - passing.sample_count,
    "rate_delta_hz": delta(fail.approximate_rate_hz, passing.approximate_rate_hz),
    "first_timestamp_delta": delta(fail.first_timestamp, passing.first_timestamp),
    "last_timestamp_delta": delta(fail.last_timestamp, passing.last_timestamp),
    "fields": [compare_field(name, fail.fields.get(name), passing.fields.get(name)) for name in fields],
  }


def compare_field(name: str, fail_stats: FieldStats | None, pass_stats: FieldStats | None) -> JsonDict:
  return {
    "field": name,
    "fail_present_count": getattr(fail_stats, "count", 0),
    "pass_present_count": getattr(pass_stats, "count", 0),
    "mean_delta": delta(getattr(fail_stats, "mean", None), getattr(pass_stats, "mean", None)),
    "min_delta": delta(getattr(fail_stats, "min", None), getattr(pass_stats, "min", None)),
    "max_delta": delta(getattr(fail_stats, "max", None), getattr(pass_stats, "max", None)),
    "transition_count_delta": getattr(fail_stats, "transition_count", 0) - getattr(pass_stats, "transition_count", 0),
    "first_delta": delta(numeric_value(getattr(fail_stats, "first", None)), numeric_value(getattr(pass_stats, "first", None))),
    "last_delta": delta(numeric_value(getattr(fail_stats, "last", None)), numeric_value(getattr(pass_stats, "last", None))),
  }


def first_divergence(topic: str, fail: list[Sample], passing: list[Sample], time_tolerance: float = 0.0, numeric_tolerance: float = 0.0) -> JsonDict | None:
  aligned, unmatched_fail, unmatched_pass = align_samples(fail, passing, time_tolerance)
  if not aligned:
    if fail or passing:
      return {"topic": topic, "reason": "no_common_timestamps", "fail_sample_count": len(fail), "pass_sample_count": len(passing)}
    return None

  for fail_sample, pass_sample in aligned:
    fields = sorted(set(fail_sample.fields) & set(pass_sample.fields))
    for field in fields:
      fail_value = fail_sample.fields.get(field)
      pass_value = pass_sample.fields.get(field)
      if not values_equal(fail_value, pass_value, numeric_tolerance):
        return {
          "topic": topic,
          "timestamp": fail_sample.timestamp,
          "pass_timestamp": pass_sample.timestamp,
          "time_delta": fail_sample.timestamp - pass_sample.timestamp,
          "field": field,
          "fail_value": fail_value,
          "pass_value": pass_value,
        }
  if unmatched_fail or unmatched_pass:
    reason = "timestamp_sets_differ" if time_tolerance == 0 else "unmatched_samples"
    return {
      "topic": topic,
      "reason": reason,
      "common_timestamp_count": len(aligned),
      "unmatched_fail_sample_count": len(unmatched_fail),
      "unmatched_pass_sample_count": len(unmatched_pass),
      "unmatched_fail_timestamps": [sample.timestamp for sample in unmatched_fail[:5]],
      "unmatched_pass_timestamps": [sample.timestamp for sample in unmatched_pass[:5]],
    }
  if len(fail) != len(passing):
    return {"topic": topic, "sample_index": min(len(fail), len(passing)), "reason": "sample_count_differs"}
  return None


def timestamp_alignment(topic: str, fail: list[Sample], passing: list[Sample], time_tolerance: float) -> JsonDict | None:
  if not fail and not passing:
    return None
  aligned, unmatched_fail, unmatched_pass = align_samples(fail, passing, time_tolerance)
  return {
    "topic": topic,
    "matched_sample_count": len(aligned),
    "unmatched_fail_sample_count": len(unmatched_fail),
    "unmatched_pass_sample_count": len(unmatched_pass),
    "unmatched_fail_timestamps": [sample.timestamp for sample in unmatched_fail[:5]],
    "unmatched_pass_timestamps": [sample.timestamp for sample in unmatched_pass[:5]],
  }


def align_samples(fail: list[Sample], passing: list[Sample], time_tolerance: float) -> tuple[list[tuple[Sample, Sample]], list[Sample], list[Sample]]:
  fail_ordered = sorted(fail, key=lambda sample: sample.timestamp)
  pass_remaining = sorted(passing, key=lambda sample: sample.timestamp)
  aligned: list[tuple[Sample, Sample]] = []
  unmatched_fail: list[Sample] = []

  for fail_sample in fail_ordered:
    match_index = nearest_match_index(fail_sample, pass_remaining, time_tolerance)
    if match_index is None:
      unmatched_fail.append(fail_sample)
      continue
    pass_sample = pass_remaining.pop(match_index)
    aligned.append((fail_sample, pass_sample))

  return aligned, unmatched_fail, pass_remaining


def nearest_match_index(fail_sample: Sample, candidates: list[Sample], time_tolerance: float) -> int | None:
  if time_tolerance == 0:
    for index, candidate in enumerate(candidates):
      if candidate.timestamp == fail_sample.timestamp:
        return index
    return None
  best_index: int | None = None
  best_delta: float | None = None
  for index, candidate in enumerate(candidates):
    delta_value = abs(candidate.timestamp - fail_sample.timestamp)
    if delta_value <= time_tolerance and (best_delta is None or delta_value < best_delta):
      best_index = index
      best_delta = delta_value
  return best_index


def values_equal(left: object, right: object, numeric_tolerance: float) -> bool:
  if left == right:
    return True
  if numeric_tolerance == 0:
    return False
  left_number = numeric_value(left)
  right_number = numeric_value(right)
  if left_number is None or right_number is None:
    return False
  return abs(left_number - right_number) <= numeric_tolerance


def delta(left: float | None, right: float | None) -> float | None:
  if left is None or right is None:
    return None
  return left - right
