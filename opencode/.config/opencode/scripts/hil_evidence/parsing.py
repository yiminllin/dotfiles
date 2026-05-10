#!/usr/bin/env python3
"""Pure parsing helpers for HIL/GHA evidence packets."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


DEFAULT_S3_BUCKET = "platform2-testing-logs"
CONCRETE_HIL_S3_PREFIX = f"s3://{DEFAULT_S3_BUCKET}/p2-zip-system-hil/"
MAX_TEST_RECORD_QUERY_MATCHES = 20

GITHUB_RUN_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/actions/runs/"
    r"(?P<run_id>\d+)(?:/job/(?P<job_id>\d+))?/?(?:[?#].*)?$"
)
S3_URI_RE = re.compile(r"^s3://(?P<bucket>[^/\s]+)(?:/(?P<key>.*))?$")
S3_URI_IN_TEXT_RE = re.compile(r"s3://[^\s\"'<>]+")
S3_CONSOLE_IN_TEXT_RE = re.compile(r"https://s3\.console\.aws\.amazon\.com/s3/buckets/[^\s\"'<>]+")
SUMMARY_REF_RE = re.compile(r"S3_WEB_LINK_IN_SUMMARY=\"?([^\"\s]+)")

ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])")
BARAZA_LINK_RE = re.compile(r"https://baraza[^\s\"'<>)]*", re.IGNORECASE)
FLIGHT_ID_RE = re.compile(r"\b(?:New\s+)?flight ID:\s*([A-Za-z0-9_\-]+)", re.IGNORECASE)
MISSION_ID_RE = re.compile(r"\b(?:New\s+)?mission ID:\s*([A-Za-z0-9_\-]+)", re.IGNORECASE)
FLIGHT_ID_VALUE_RE = re.compile(r"\bP2F_[A-Za-z0-9_\-]+")
MISSION_ID_VALUE_RE = re.compile(r"\b(?:P2M|ZZM)_[A-Za-z0-9_\-]+")


def parse_github_actions_url(raw_url: str) -> dict[str, str | None] | None:
    match = GITHUB_RUN_RE.match(raw_url.strip())
    if not match:
        return None
    return {
        "repo": f"{match.group('owner')}/{match.group('repo')}",
        "run_id": match.group("run_id"),
        "job_id": match.group("job_id"),
    }


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def clean_link(link: str, *, strip_ansi_sequences: bool = True, trailing_chars: str = ".,;)]") -> str:
    text = strip_ansi(link) if strip_ansi_sequences else link
    return text.strip().rstrip(trailing_chars)


def unique(values: Iterable[str], *, skip_empty: bool = False) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if skip_empty and not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    return unique(values, skip_empty=True)


def split_s3_uri(s3_uri: str) -> tuple[str, str]:
    match = S3_URI_RE.match(s3_uri)
    if not match:
        raise ValueError(f"not an S3 URI: {s3_uri}")
    return match.group("bucket"), (match.group("key") or "").lstrip("/")


def normalize_s3_reference(raw_ref: str, default_bucket: str = DEFAULT_S3_BUCKET) -> str:
    raw_ref = strip_ansi(raw_ref).strip().strip("'\"")
    match = S3_URI_RE.match(raw_ref)
    if match:
        bucket = match.group("bucket")
        key = (match.group("key") or "").lstrip("/")
        if not key:
            raise ValueError("S3 bucket root is not allowed; provide a narrower prefix")
        return f"s3://{bucket}/{key}"

    parsed = urlparse(raw_ref)
    if parsed.scheme in {"http", "https"} and parsed.netloc == "s3.console.aws.amazon.com":
        parts = parsed.path.strip("/").split("/")
        bucket = parts[2] if len(parts) >= 3 and parts[:2] == ["s3", "buckets"] else default_bucket
        query = parse_qs(parsed.query)
        prefix = unquote((query.get("prefix") or [""])[0]).lstrip("/")
        query_bucket = (query.get("bucket") or [""])[0]
        bucket = query_bucket or bucket
        if not prefix:
            raise ValueError("S3 console URL has no prefix; provide a narrower S3 prefix")
        return f"s3://{bucket}/{prefix}"

    if raw_ref.startswith(f"{default_bucket}/"):
        prefix = raw_ref[len(default_bucket) + 1 :].lstrip("/")
        if not prefix:
            raise ValueError("S3 bucket root is not allowed; provide a narrower prefix")
        return f"s3://{default_bucket}/{prefix}"
    if raw_ref.startswith("p2-zip-system-hil/"):
        return f"s3://{default_bucket}/{raw_ref}"
    if "/" in raw_ref and not parsed.scheme:
        prefix = raw_ref.lstrip("/")
        if not prefix:
            raise ValueError("S3 bucket root is not allowed; provide a narrower prefix")
        return f"s3://{default_bucket}/{prefix}"
    raise ValueError(f"unsupported S3 reference: {raw_ref}")


def normalize_http_s3_reference(raw_ref: str, bucket: str = DEFAULT_S3_BUCKET) -> str | None:
    cleaned = clean_link(raw_ref)
    parsed = urlparse(cleaned)
    if not parsed.scheme.startswith("http"):
        return None

    if parsed.netloc.endswith("console.aws.amazon.com") and f"/s3/buckets/{bucket}" in parsed.path:
        query = parse_qs(parsed.query)
        prefix = first_query_value(query, "prefix")
        return s3_uri_from_prefix(prefix, bucket) if prefix else None
    if is_bucket_hosted_s3_netloc(parsed.netloc, bucket):
        return s3_uri_from_prefix(unquote(parsed.path.lstrip("/")), bucket)
    if is_path_style_s3_netloc(parsed.netloc) and parsed.path.startswith(f"/{bucket}/"):
        prefix = parsed.path.removeprefix(f"/{bucket}/")
        return s3_uri_from_prefix(unquote(prefix), bucket)
    return None


def normalize_s3_root(ref: str, runner_name: str | None = None, bucket: str = DEFAULT_S3_BUCKET) -> str | None:
    cleaned = clean_link(ref)
    if runner_name:
        cleaned = replace_runner_name_placeholder(cleaned, runner_name)
    if has_unresolved_runner_name_placeholder(cleaned):
        return None
    if cleaned.startswith(f"s3://{bucket}/"):
        return cleaned if is_test_record_uri(cleaned) else ensure_s3_prefix(cleaned)
    return normalize_http_s3_reference(cleaned, bucket)


def is_bucket_hosted_s3_netloc(netloc: str, bucket: str = DEFAULT_S3_BUCKET) -> bool:
    return bool(re.fullmatch(rf"{re.escape(bucket)}\.s3(?:\.[A-Za-z0-9-]+)?\.amazonaws\.com", netloc))


def is_path_style_s3_netloc(netloc: str) -> bool:
    return bool(re.fullmatch(r"s3(?:\.[A-Za-z0-9-]+)?\.amazonaws\.com", netloc))


def first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return unquote(values[0]).lstrip("/")


def s3_uri_from_prefix(prefix: str, bucket: str = DEFAULT_S3_BUCKET) -> str | None:
    cleaned = prefix.strip().lstrip("/")
    if not cleaned or has_unresolved_runner_name_placeholder(cleaned):
        return None
    uri = f"s3://{bucket}/{cleaned}"
    return uri.rstrip("/") if is_test_record_uri(uri) else ensure_s3_prefix(uri)


def is_test_record_uri(uri: str) -> bool:
    return uri.rstrip("/").rsplit("/", 1)[-1] == "test_record.json"


def ensure_s3_prefix(uri: str) -> str:
    return f"{uri.rstrip('/')}/"


def replace_runner_name_placeholder(text: str, runner_name: str) -> str:
    return (
        text.replace("${RUNNER_NAME}", runner_name)
        .replace("$RUNNER_NAME", runner_name)
        .replace("%24RUNNER_NAME", runner_name)
        .replace("%24%7BRUNNER_NAME%7D", runner_name)
        .replace("%24%7bRUNNER_NAME%7d", runner_name)
    )


def has_unresolved_runner_name_placeholder(text: str) -> bool:
    return "RUNNER_NAME" in unquote(text)


def extract_artifact_s3_refs(text: str, runner_name: str = "", details: bool = False) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    candidates: list[tuple[str, str]] = []
    candidates.extend(("summary", match.group(1)) for match in SUMMARY_REF_RE.finditer(text))
    candidates.extend(("s3-uri", match.group(0)) for match in S3_URI_IN_TEXT_RE.finditer(text))
    candidates.extend(("s3-console", match.group(0)) for match in S3_CONSOLE_IN_TEXT_RE.finditer(text))

    seen: set[str] = set()
    for source, raw_ref in candidates:
        clean_ref = clean_link(raw_ref, trailing_chars="'\"),]")
        if runner_name:
            clean_ref = clean_ref.replace("$RUNNER_NAME", runner_name)
        if not details and not is_default_s3_ref(clean_ref):
            continue
        try:
            s3_uri = normalize_s3_reference(clean_ref)
        except ValueError:
            continue
        if not details and not is_default_s3_ref(s3_uri):
            continue
        if s3_uri in seen:
            continue
        seen.add(s3_uri)
        refs.append({"source": source, "raw": clean_ref, "s3_uri": s3_uri})
    return refs


def is_default_s3_ref(ref: str) -> bool:
    if ANSI_ESCAPE_RE.search(ref):
        return False
    if any(token in ref for token in ("{", "}", "$", "<", ">")):
        return False
    lowered = ref.lower()
    if "build-cache" in lowered or "build-artifacts" in lowered:
        return False
    try:
        s3_uri = normalize_s3_reference(ref)
    except ValueError:
        return False
    return s3_uri.startswith(CONCRETE_HIL_S3_PREFIX)


def extract_log_links(log_text: str, bucket: str = DEFAULT_S3_BUCKET) -> dict[str, list[str]]:
    s3_summary_link_re = re.compile(r"""\bS3_WEB_LINK_IN_SUMMARY\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s"']+))""")
    s3_console_link_re = re.compile(
        rf"""https://[^\s"'<>)]*console\.aws\.amazon\.com/s3/buckets/"""
        rf"""{re.escape(bucket)}[^\s"'<>)]*prefix=[^\s"'<>)]*"""
    )
    s3_direct_link_re = re.compile(
        rf"""https://(?:{re.escape(bucket)}\.s3(?:\.[A-Za-z0-9-]+)?\.amazonaws\.com"""
        rf"""|s3(?:\.[A-Za-z0-9-]+)?\.amazonaws\.com/{re.escape(bucket)})/[^\s"'<>)]*"""
    )
    s3_uri_re = re.compile(rf"""s3://{re.escape(bucket)}/[^\s"'<>)]*""")

    s3_links: list[str] = []
    for match in s3_summary_link_re.finditer(log_text):
        s3_links.append(clean_link(next(group for group in match.groups() if group)))
    s3_links.extend(
        clean_link(match.group(0)) for match in s3_console_link_re.finditer(log_text)
    )
    s3_links.extend(
        clean_link(match.group(0)) for match in s3_direct_link_re.finditer(log_text)
    )
    s3_links.extend(clean_link(match.group(0)) for match in s3_uri_re.finditer(log_text))

    baraza_links = [clean_link(match.group(0)) for match in BARAZA_LINK_RE.finditer(log_text)]
    return {
        "s3_links": dedupe_preserving_order(s3_links),
        "baraza_links": dedupe_preserving_order(baraza_links),
    }


def extract_baraza(text: str) -> dict[str, Any]:
    text = strip_ansi(text)
    links = [clean_link(match.group(0)) for match in BARAZA_LINK_RE.finditer(text)]
    flight_ids = extract_flight_ids(text)
    mission_ids = extract_mission_ids(text)
    return {
        "links": unique([link for link in links if is_useful_baraza_link(link)]),
        "flight_ids": flight_ids,
        "mission_ids": mission_ids,
        "candidates": baraza_candidates(links, mission_ids, flight_ids),
    }


def extract_baraza_from_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    baraza = empty_baraza()
    for text in inventory_baraza_texts(inventory):
        merge_baraza(baraza, extract_baraza(text))
    return baraza


def inventory_baraza_texts(inventory: dict[str, Any]) -> list[str]:
    texts = [str(inventory.get("s3_uri") or ""), str(inventory.get("prefix") or "")]
    for item in inventory.get("items") or []:
        texts.append(str(item.get("key") or ""))
        texts.append(str(item.get("uri") or ""))
    return [text for text in texts if text]


def empty_baraza() -> dict[str, Any]:
    return {"links": [], "flight_ids": [], "mission_ids": [], "candidates": []}


def merge_baraza(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    for key in ("links", "flight_ids", "mission_ids"):
        target[key] = unique(
            [str(item) for item in target.get(key, []) + source.get(key, []) if item]
        )
    target["candidates"] = merge_baraza_candidates(
        target.get("candidates") or [],
        source.get("candidates") or [],
    )
    return target


def extract_flight_ids(text: str) -> list[str]:
    return unique(
        group_matches_without_ellipsis(FLIGHT_ID_RE, text)
        + group_matches_without_ellipsis(FLIGHT_ID_VALUE_RE, text, 0)
    )


def extract_mission_ids(text: str) -> list[str]:
    return unique(
        group_matches_without_ellipsis(MISSION_ID_RE, text)
        + group_matches_without_ellipsis(MISSION_ID_VALUE_RE, text, 0)
    )


def group_matches_without_ellipsis(pattern: re.Pattern[str], text: str, group: int = 1) -> list[str]:
    values = []
    for match in pattern.finditer(text):
        value = match.group(group)
        if match.end(group) < len(text) and text[match.end(group)] == "…":
            continue
        values.append(value)
    return values


def baraza_candidates(links: list[str], mission_ids: list[str], flight_ids: list[str]) -> list[dict[str, str]]:
    candidates = inferred_baraza_id_candidates(mission_ids, flight_ids)
    for link in unique([link for link in links if is_useful_baraza_link(link)]):
        mission_id = mission_id_from_baraza_link(link)
        if mission_id:
            add_baraza_candidate(candidates, {"link": link, "mission_id": mission_id})
        elif not candidates:
            add_baraza_candidate(candidates, {"link": link})
    return candidates


def inferred_baraza_id_candidates(mission_ids: list[str], flight_ids: list[str]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    if mission_ids and flight_ids:
        if len(mission_ids) == len(flight_ids):
            for mission_id, flight_id in zip(mission_ids, flight_ids):
                add_baraza_candidate(candidates, {"mission_id": mission_id, "flight_id": flight_id})
        elif len(mission_ids) == 1:
            for flight_id in flight_ids:
                add_baraza_candidate(candidates, {"mission_id": mission_ids[0], "flight_id": flight_id})
        elif len(flight_ids) == 1:
            for mission_id in mission_ids:
                add_baraza_candidate(candidates, {"mission_id": mission_id, "flight_id": flight_ids[0]})
        else:
            for mission_id in mission_ids:
                add_baraza_candidate(candidates, {"mission_id": mission_id})
            for flight_id in flight_ids:
                add_baraza_candidate(candidates, {"flight_id": flight_id})
        return candidates
    for mission_id in mission_ids:
        add_baraza_candidate(candidates, {"mission_id": mission_id})
    for flight_id in flight_ids:
        add_baraza_candidate(candidates, {"flight_id": flight_id})
    return candidates


def merge_baraza_candidates(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    for candidate in existing + incoming:
        add_baraza_candidate(merged, {key: str(value) for key, value in candidate.items() if value})
    return merged


def add_baraza_candidate(candidates: list[dict[str, str]], candidate: dict[str, str]) -> None:
    candidate = {key: value for key, value in candidate.items() if value}
    if not candidate:
        return
    matched = False
    for existing in candidates:
        if same_baraza_candidate(existing, candidate):
            existing.update({key: value for key, value in candidate.items() if value})
            matched = True
    if matched:
        return
    candidates.append(candidate)


def same_baraza_candidate(left: dict[str, str], right: dict[str, str]) -> bool:
    left_flight = left.get("flight_id")
    right_flight = right.get("flight_id")
    return bool(
        (left.get("link") and left.get("link") == right.get("link"))
        or (
            left.get("mission_id")
            and left.get("mission_id") == right.get("mission_id")
            and (not left_flight or not right_flight or left_flight == right_flight)
        )
        or (
            left_flight
            and left_flight == right_flight
            and (
                not left.get("mission_id")
                or not right.get("mission_id")
                or left.get("mission_id") == right.get("mission_id")
            )
        )
    )


def mission_id_from_baraza_link(link: str) -> str | None:
    path_parts = [part for part in urlparse(link).path.split("/") if part]
    for index, part in enumerate(path_parts[:-1]):
        if part.lower() == "missions":
            mission_id = path_parts[index + 1]
            return mission_id if "…" not in mission_id else None
    return None


def is_useful_baraza_link(link: str) -> bool:
    path = urlparse(link).path.lower()
    return not (path == "/api" or path.startswith("/api/"))


def find_test_record_keys_from_recursive_ls(output: str) -> list[str]:
    keys: list[str] = []
    for line in output.splitlines():
        columns = line.strip().split(maxsplit=3)
        if len(columns) != 4:
            continue
        key = columns[3].strip()
        if key == "test_record.json" or key.endswith("/test_record.json"):
            keys.append(key)
    return dedupe_preserving_order(keys)


def find_json_query_matches(value: Any, query: str) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    collect_json_query_matches(value, query.lower(), "$", matches)
    return matches[:MAX_TEST_RECORD_QUERY_MATCHES]


def find_json_exact_query_matches(value: Any, query: str) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    collect_json_exact_query_matches(value, query.lower(), "$", matches)
    return matches[:MAX_TEST_RECORD_QUERY_MATCHES]


def collect_json_query_matches(value: Any, query: str, path: str, matches: list[dict[str, str]]) -> None:
    if len(matches) >= MAX_TEST_RECORD_QUERY_MATCHES:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = json_path_join(path, str(key))
            if query in str(key).lower():
                matches.append({"path": child_path, "field": str(key), "snippet": str(key)})
                if len(matches) >= MAX_TEST_RECORD_QUERY_MATCHES:
                    return
            collect_json_query_matches(child, query, child_path, matches)
            if len(matches) >= MAX_TEST_RECORD_QUERY_MATCHES:
                return
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            collect_json_query_matches(child, query, f"{path}[{index}]", matches)
            if len(matches) >= MAX_TEST_RECORD_QUERY_MATCHES:
                return
        return

    text = json.dumps(value) if isinstance(value, (bool, int, float)) or value is None else str(value)
    if query in text.lower():
        matches.append({"path": path, "field": path.rsplit(".", 1)[-1], "snippet": short_snippet(text, query)})


def collect_json_exact_query_matches(value: Any, query: str, path: str, matches: list[dict[str, str]]) -> None:
    if len(matches) >= MAX_TEST_RECORD_QUERY_MATCHES:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = json_path_join(path, str(key))
            if str(key).lower() == query:
                matches.append({"path": child_path, "field": str(key), "snippet": str(key)})
                if len(matches) >= MAX_TEST_RECORD_QUERY_MATCHES:
                    return
            collect_json_exact_query_matches(child, query, child_path, matches)
            if len(matches) >= MAX_TEST_RECORD_QUERY_MATCHES:
                return
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            collect_json_exact_query_matches(child, query, f"{path}[{index}]", matches)
            if len(matches) >= MAX_TEST_RECORD_QUERY_MATCHES:
                return
        return

    text = json.dumps(value) if isinstance(value, (bool, int, float)) or value is None else str(value)
    if text.lower() == query or query in (match.lower() for match in re.findall(r"\[([^\]]+)\]", text)):
        matches.append({"path": path, "field": path.rsplit(".", 1)[-1], "snippet": text[:80]})


def json_path_join(base: str, key: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return f"{base}.{key}"
    return f"{base}[{json.dumps(key)}]"


def short_snippet(text: str, query: str, window: int = 80) -> str:
    lowered = text.lower()
    index = lowered.find(query)
    if index < 0 or len(text) <= window:
        return text[:window]
    half = max(1, window // 2)
    start = max(0, index - half)
    end = min(len(text), index + len(query) + half)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def extract_test_record_summary(record: Any, s3_uri: str) -> dict[str, Any]:
    data = record if isinstance(record, dict) else {}
    test_info = data.get("test_info") if isinstance(data.get("test_info"), dict) else {}
    mission_info = data.get("mission_info")
    summary = {
        "s3_uri": s3_uri,
        "test_name": first_present(test_info, "name", "test_name", "nodeid"),
        "result": first_present(test_info, "result", "status", "outcome"),
        "parameters": compact_json_value(test_info.get("parameters")),
        "phase_results": extract_phase_results(data.get("phases")),
        "manifest_files": extract_manifest_files(data.get("manifest")),
        "mission_info": compact_json_value(mission_info),
    }
    baraza_urls = extract_baraza_urls(mission_info)
    if baraza_urls:
        summary["baraza_urls"] = [{"url": url, "source": "mission_info"} for url in baraza_urls]
    identifiers = extract_mission_info_identifiers(mission_info)
    if identifiers:
        summary["mission_info_identifiers"] = identifiers
    return {key: value for key, value in summary.items() if value not in (None, [], {})}


def first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def extract_phase_results(phases: Any) -> list[dict[str, Any]]:
    if not isinstance(phases, list):
        return []
    results: list[dict[str, Any]] = []
    for index, phase in enumerate(phases):
        if not isinstance(phase, dict):
            continue
        result = first_present(phase, "result", "status", "outcome")
        results.append(
            {
                "name": first_present(phase, "name", "phase", "phase_name") or f"phase[{index}]",
                "result": result,
            }
        )
    return [entry for entry in results if entry.get("name") or entry.get("result")]


def extract_manifest_files(manifest: Any) -> list[dict[str, Any]]:
    if isinstance(manifest, dict):
        manifest = manifest.values()
    if not isinstance(manifest, Iterable) or isinstance(manifest, (str, bytes)):
        return []
    files: list[dict[str, Any]] = []
    for item in manifest:
        if isinstance(item, dict):
            files.append(
                {
                    key: item.get(key)
                    for key in ("key", "filename", "path", "phase", "artifact_type")
                    if item.get(key) not in (None, "")
                }
            )
        elif item not in (None, ""):
            files.append({"filename": str(item)})
    return [entry for entry in files if entry][:20]


def compact_json_value(value: Any, max_items: int = 20, max_string: int = 200) -> Any:
    if isinstance(value, dict):
        return {
            str(key): compact_json_value(child, max_items, max_string)
            for key, child in list(value.items())[:max_items]
        }
    if isinstance(value, list):
        return [compact_json_value(item, max_items, max_string) for item in value[:max_items]]
    if isinstance(value, str) and len(value) > max_string:
        return f"{value[:max_string]}…"
    return value


def extract_baraza_urls(value: Any) -> list[str]:
    urls: list[str] = []
    for _, scalar in iter_scalar_json_values(value):
        if isinstance(scalar, str):
            urls.extend(
                clean_link(match.group(0))
                for match in BARAZA_LINK_RE.finditer(scalar)
            )
    return dedupe_preserving_order(urls)


def extract_mission_info_identifiers(value: Any) -> list[dict[str, str]]:
    identifiers: list[dict[str, str]] = []
    for path, scalar in iter_scalar_json_values(value):
        path_lower = path.lower()
        kind = next((name for name in ("mission", "flight", "asset") if name in path_lower), None)
        if kind and scalar not in (None, ""):
            identifiers.append({"kind": kind, "path": path, "value": str(scalar), "source": "mission_info"})
    return identifiers[:20]


def iter_scalar_json_values(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_scalar_json_values(child, json_path_join(path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_scalar_json_values(child, f"{path}[{index}]")
    else:
        yield path, value
