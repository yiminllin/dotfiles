from __future__ import annotations

import re
from collections import deque

from .models import JsonDict
from .parsing import extract_log_links, strip_ansi


FAILED_TEST_RE = re.compile(
    r"(?:FAILED\s+([^\s]+)|(?:scenario|test)\s+([^:]+?)\s+(?:failed|failure))",
    re.IGNORECASE,
)
ALARM_ERROR_RE = re.compile(r"\b(?:ERROR|FATAL|CRITICAL|Traceback|Exception|ALARM|Alarm)\b")


def summarize_log(log_text: str, max_scan_lines: int | None = None, max_items: int = 20) -> JsonDict:
    lines = strip_ansi(log_text).splitlines()
    scanned = lines if max_scan_lines is None else lines[:max_scan_lines]
    summary = {
        "line_count": len(lines),
        "scanned_line_count": len(scanned),
        "truncated": len(lines) > len(scanned),
        "validator_failures": collect_matching_lines(scanned, is_validator_failure, max_items),
        "alarm_error_lines": collect_matching_lines(scanned, lambda line: bool(ALARM_ERROR_RE.search(line)), max_items),
        "failed_scenarios_or_tests": failed_tests(scanned, max_items),
        "artifact_hint_lines": collect_matching_lines(scanned, is_artifact_hint, max_items),
        "links": extract_log_links(log_text),
    }
    summary["next_step_hints"] = next_step_hints(summary)
    return summary


def collect_matching_lines(lines: list[str], predicate, max_items: int) -> list[JsonDict]:
    head_limit, tail_limit = split_limits(max_items)
    head_matches = []
    tail_matches: deque[JsonDict] = deque(maxlen=tail_limit)
    seen: set[str] = set()
    for index, line in enumerate(lines, start=1):
        text = line.strip()
        if not text or not predicate(text):
            continue
        compact = compact_line(text)
        if compact in seen:
            continue
        seen.add(compact)
        match = {"line": index, "text": compact}
        if len(head_matches) < head_limit:
            head_matches.append(match)
        elif tail_limit:
            tail_matches.append(match)
    return head_matches + list(tail_matches)


def is_validator_failure(line: str) -> bool:
    lowered = line.lower()
    return "validator" in lowered and any(token in lowered for token in ("fail", "error", "violation", "missing"))


def is_artifact_hint(line: str) -> bool:
    lowered = line.lower()
    return any(token in lowered for token in ("s3://", "s3_web_link_in_summary", "test_record.json", "baraza", "artifact"))


def failed_tests(lines: list[str], max_items: int) -> list[str]:
    head_limit, tail_limit = split_limits(max_items)
    head_values = []
    tail_values: deque[str] = deque(maxlen=tail_limit)
    seen: set[str] = set()
    for line in lines:
        match = FAILED_TEST_RE.search(line)
        if not match:
            continue
        value = compact_line(next(group for group in match.groups() if group))
        if value in seen:
            continue
        seen.add(value)
        if len(head_values) < head_limit:
            head_values.append(value)
        elif tail_limit:
            tail_values.append(value)
    return head_values + list(tail_values)


def split_limits(max_items: int) -> tuple[int, int]:
    if max_items <= 1:
        return max(0, max_items), 0
    head_limit = (max_items + 1) // 2
    return head_limit, max_items - head_limit


def next_step_hints(summary: JsonDict) -> list[str]:
    hints = []
    if summary.get("validator_failures"):
        hints.append("Inspect validator failure context in the job log and matching artifact inventory.")
    if summary.get("failed_scenarios_or_tests"):
        hints.append("Open the matching test_record.json to confirm the exact failing scenario/test parameters.")
    links = summary.get("links") or {}
    if links.get("s3_links"):
        hints.append("Use the S3 links to inspect test_record.json, phoenix.log, journal logs, and validator artifacts.")
    if links.get("baraza_links"):
        hints.append("Use the Baraza links or inferred mission IDs for mission-level context.")
    if not hints:
        hints.append("No high-signal failure lines were detected; inspect full job logs and artifacts manually.")
    return hints


def compact_line(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "…"
