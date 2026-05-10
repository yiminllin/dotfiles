from __future__ import annotations

import json
from typing import Any

from .models import JsonDict
from .parsing import mission_id_from_baraza_link, unique


KEY_ARTIFACT_LIMIT = 30
MISSION_CONTEXT_LIMIT = 20


def render_markdown(packet: JsonDict) -> str:
    lines = ["# HIL/GHA Evidence Packet", ""]
    lines.append(f"- Status: `{packet.get('status', 'unknown')}`")
    lines.append(f"- Mode: `{packet.get('mode', 'unknown')}`")
    source = packet.get("source") or {}
    if source:
        lines.append(f"- Source: `{source.get('input')}`")
    lines.append("")

    append_notes(lines, "Ambiguity", packet.get("ambiguity") or [])
    append_notes(lines, "Confidence", packet.get("confidence") or [])
    append_github(lines, packet)
    append_candidates(lines, packet.get("candidates") or [])
    append_jobs(lines, packet.get("jobs") or [])
    append_s3(lines, packet.get("s3") or {})
    append_mission_context(lines, packet.get("s3") or {}, packet.get("test_records") or [], "## Mission context")
    append_test_records(lines, packet.get("test_records") or [])
    if packet.get("log_summary"):
        append_log_summary(lines, packet["log_summary"])
    append_blockers(lines, packet.get("blockers") or [])
    append_blockers(lines, packet.get("errors") or [], title="Errors")
    append_notes(lines, "Next steps", packet.get("next_steps") or [])
    return "\n".join(lines).rstrip() + "\n"


def append_github(lines: list[str], packet: JsonDict) -> None:
    github = packet.get("github") or {}
    run = github.get("run")
    if not run:
        return
    lines.extend(["## GitHub run", ""])
    for key in ("run_id", "title", "workflow", "branch", "status", "conclusion", "url"):
        if run.get(key) not in (None, ""):
            lines.append(f"- {key}: {link_or_code(run[key])}")
    lines.append("")


def append_candidates(lines: list[str], candidates: list[JsonDict]) -> None:
    if not candidates:
        return
    rows = []
    for candidate in candidates:
        rows.append(
            {
                "job": candidate.get("job_name"),
                "conclusion": candidate.get("job_conclusion"),
                "run": candidate.get("run_id"),
                "job_id": candidate.get("job_id"),
                "test_record": confirmation_status(candidate),
                "url": candidate.get("job_url"),
            }
        )
    append_table(lines, "Candidate HIL jobs", ["job", "conclusion", "run", "job_id", "test_record", "url"], rows)


def append_jobs(lines: list[str], jobs: list[JsonDict]) -> None:
    for index, job in enumerate(jobs, start=1):
        candidate = job.get("candidate") or {}
        meta = (job.get("github") or {}).get("job") or {}
        name = meta.get("name") or candidate.get("job_name") or f"job {index}"
        lines.extend([f"## Job: {name}", ""])
        if candidate.get("job_url"):
            lines.append(f"- GHA: {candidate['job_url']}")
        confirmation = job.get("test_record_confirmation")
        if confirmation:
            lines.append(
                f"- test_record confirmation: `{confirmation.get('status')}` "
                f"for `{confirmation.get('query')}` ({confirmation.get('reason')})"
            )
        for key in ("status", "conclusion", "runner_name", "started_at", "completed_at"):
            if meta.get(key) not in (None, ""):
                lines.append(f"- {key}: `{meta[key]}`")
        lines.append("")
        if job.get("log_summary"):
            append_log_summary(lines, job["log_summary"])
        append_job_s3(lines, job.get("s3") or {})
        append_mission_context(lines, job.get("s3") or {}, job.get("test_records") or [], "### Mission context")
        append_test_records(lines, job.get("test_records") or [], heading="### test_record.json")
        append_blockers(lines, job.get("blockers") or [], title="### Job blockers")


def append_job_s3(lines: list[str], s3: JsonDict) -> None:
    if not s3:
        return
    link_groups = (
        ("S3 roots", s3.get("roots") or []),
        ("S3 links", s3.get("s3_links") or []),
        ("Baraza links", s3.get("baraza_links") or []),
        ("test_record.json", s3.get("test_record_uris") or []),
    )
    lines.extend(["### Links and artifacts", ""])
    inventories = s3.get("inventories") or []
    if not inventories and not key_artifact_rows(s3) and not any(values for _, values in link_groups):
        lines.pop()
        lines.pop()
        return
    for label, values in link_groups:
        if values:
            lines.append(f"- {label}:")
            lines.extend(f"  - {value}" for value in values[:20])
    if inventories:
        rows = []
        for inventory in inventories:
            rows.append({"s3_uri": inventory.get("s3_uri"), "objects": inventory.get("count"), "key hints": len(inventory.get("key_artifact_hints") or [])})
        lines.append("")
        append_table(lines, "### S3 inventory", ["s3_uri", "objects", "key hints"], rows)
    append_key_artifacts(lines, s3)
    if not inventories:
        lines.append("")


def append_key_artifacts(lines: list[str], s3: JsonDict) -> None:
    rows = key_artifact_rows(s3)
    if rows:
        append_table(lines, "### Key S3 artifacts", ["category", "type", "uri", "size", "note"], rows)
    else:
        return


def key_artifact_rows(s3: JsonDict) -> list[JsonDict]:
    rows: list[JsonDict] = []
    for inventory in s3.get("inventories") or []:
        for artifact in inventory.get("test_record_artifacts") or []:
            rows.append(
                {
                    "category": "test_record",
                    "type": artifact.get("type") or "test_record.json",
                    "uri": artifact.get("uri"),
                    "size": artifact.get("size"),
                    "note": artifact.get("note") or "Authoritative test result and manifest.",
                }
            )
        for hint in inventory.get("key_artifact_hints") or []:
            rows.append(
                {
                    "category": hint.get("category") or "artifact",
                    "type": hint.get("type") or "key file",
                    "uri": hint.get("uri"),
                    "size": hint.get("size"),
                    "note": hint.get("note"),
                }
            )
    for uri in s3.get("test_record_uris") or []:
        rows.append(
            {
                "category": "test_record",
                "type": "test_record.json",
                "uri": uri,
                "size": "",
                "note": "Authoritative test result and manifest.",
            }
        )
    return merge_rows_preferring_values(rows, ("uri",))[:KEY_ARTIFACT_LIMIT]


def append_s3(lines: list[str], s3: JsonDict) -> None:
    if not s3:
        return
    lines.extend(["## S3", ""])
    append_job_s3(lines, s3)


def append_test_records(lines: list[str], records: list[JsonDict], heading: str = "## test_record.json") -> None:
    if not records:
        return
    lines.extend([heading, ""])
    rows = []
    for record in records:
        rows.append(
            {
                "uri": record.get("s3_uri"),
                "test": record.get("test_name"),
                "result": record.get("result"),
                "matches": len(record.get("query_matches") or []),
            }
        )
    append_table_rows(lines, ["uri", "test", "result", "matches"], rows)


def append_mission_context(lines: list[str], s3: JsonDict, records: list[JsonDict], heading: str) -> None:
    context = collect_mission_context(s3, records)
    if not any(context.get(key) for key in ("links", "mission_ids", "flight_ids", "candidates")):
        return

    lines.extend([heading, ""])
    if context["links"]:
        lines.append("- Baraza links:")
        lines.extend(f"  - {link}" for link in context["links"][:10])
    else:
        lines.append("- Baraza links: not directly observed; displaying IDs only.")
    if context["mission_ids"]:
        lines.append("- Inferred mission IDs: " + ", ".join(f"`{value}`" for value in context["mission_ids"][:10]))
    if context["flight_ids"]:
        lines.append("- Inferred flight IDs: " + ", ".join(f"`{value}`" for value in context["flight_ids"][:10]))
    if context["candidates"]:
        lines.append("")
        append_table_rows(lines, ["mission_id", "flight_id", "baraza_link", "source", "note"], context["candidates"][:MISSION_CONTEXT_LIMIT])
    else:
        lines.append("")


def collect_mission_context(s3: JsonDict, records: list[JsonDict]) -> JsonDict:
    context: JsonDict = {"links": [], "mission_ids": [], "flight_ids": [], "candidates": []}
    merge_baraza_context(context, s3.get("baraza") or {}, "job log")
    for inventory in s3.get("inventories") or []:
        merge_baraza_context(context, inventory.get("baraza") or {}, "S3 inventory")
    for record in records:
        merge_record_context(context, record)
    context["links"] = unique(context["links"])
    context["mission_ids"] = unique(context["mission_ids"])
    context["flight_ids"] = unique(context["flight_ids"])
    context["candidates"] = dedupe_rows(context["candidates"], ("mission_id", "flight_id", "baraza_link"))
    return context


def merge_baraza_context(context: JsonDict, baraza: JsonDict, source: str) -> None:
    links = [str(link) for link in baraza.get("links") or [] if link]
    mission_ids = [str(value) for value in baraza.get("mission_ids") or [] if value]
    flight_ids = [str(value) for value in baraza.get("flight_ids") or [] if value]
    context["links"].extend(links)
    context["mission_ids"].extend(mission_ids)
    context["flight_ids"].extend(flight_ids)
    for candidate in baraza.get("candidates") or []:
        add_mission_candidate(context, candidate, source)
    for link in links:
        add_mission_candidate(context, {"link": link, "mission_id": mission_id_from_baraza_link(link)}, source)


def merge_record_context(context: JsonDict, record: JsonDict) -> None:
    links = [str(item.get("url")) for item in record.get("baraza_urls") or [] if item.get("url")]
    mission_ids = []
    flight_ids = []
    for item in record.get("mission_info_identifiers") or []:
        value = str(item.get("value") or "")
        if item.get("kind") == "mission" and value:
            mission_ids.append(value)
        if item.get("kind") == "flight" and value:
            flight_ids.append(value)
    context["links"].extend(links)
    context["mission_ids"].extend(mission_ids)
    context["flight_ids"].extend(flight_ids)
    if links:
        for link in links:
            link_mission_id = mission_id_from_baraza_link(link)
            for mission_id in [link_mission_id] if link_mission_id else mission_ids or [None]:
                for flight_id in flight_ids or [None]:
                    add_mission_candidate(
                        context,
                        {"link": link, "mission_id": mission_id, "flight_id": flight_id},
                        "test_record.json",
                    )
        return
    for mission_id in mission_ids or [None]:
        for flight_id in flight_ids or [None]:
            add_mission_candidate(context, {"mission_id": mission_id, "flight_id": flight_id}, "test_record.json")


def add_mission_candidate(context: JsonDict, candidate: JsonDict, source: str) -> None:
    row = {
        "mission_id": candidate.get("mission_id"),
        "flight_id": candidate.get("flight_id"),
        "baraza_link": candidate.get("link"),
        "source": source,
    }
    if not any(row.get(key) for key in ("mission_id", "flight_id", "baraza_link")):
        return
    if not row.get("baraza_link"):
        row["note"] = "link not directly observed"
    context["candidates"].append(row)


def dedupe_rows(rows: list[JsonDict], keys: tuple[str, ...]) -> list[JsonDict]:
    deduped = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        marker = tuple(str(row.get(key) or "") for key in keys)
        if marker in seen or not any(marker):
            continue
        seen.add(marker)
        deduped.append(row)
    return deduped


def merge_rows_preferring_values(rows: list[JsonDict], keys: tuple[str, ...]) -> list[JsonDict]:
    merged: list[JsonDict] = []
    by_marker: dict[tuple[str, ...], JsonDict] = {}
    for row in rows:
        marker = tuple(str(row.get(key) or "") for key in keys)
        if not any(marker):
            continue
        existing = by_marker.get(marker)
        if existing is None:
            existing = dict(row)
            by_marker[marker] = existing
            merged.append(existing)
            continue
        for key, value in row.items():
            if value not in (None, "") and existing.get(key) in (None, ""):
                existing[key] = value
    return merged


def append_log_summary(lines: list[str], summary: JsonDict) -> None:
    lines.extend(["### Lightweight failure summary", ""])
    for label, key in (
        ("Validator failures", "validator_failures"),
        ("Alarm/error lines", "alarm_error_lines"),
        ("Artifact hints", "artifact_hint_lines"),
    ):
        values = summary.get(key) or []
        if values:
            lines.append(f"- {label}:")
            lines.extend(f"  - L{item.get('line')}: {item.get('text')}" for item in values)
    failed = summary.get("failed_scenarios_or_tests") or []
    if failed:
        lines.append("- Failed scenarios/tests:")
        lines.extend(f"  - `{item}`" for item in failed)
    if not any(summary.get(key) for key in ("validator_failures", "alarm_error_lines", "artifact_hint_lines", "failed_scenarios_or_tests")):
        lines.append("- No high-signal failure lines detected.")
    lines.append("")


def append_notes(lines: list[str], title: str, notes: list[str]) -> None:
    if not notes:
        return
    lines.extend([f"## {title}", ""])
    lines.extend(f"- {note}" for note in notes)
    lines.append("")


def append_blockers(lines: list[str], blockers: list[JsonDict], title: str = "Blockers") -> None:
    if not blockers:
        return
    heading = title if title.startswith("#") else f"## {title}"
    lines.extend([heading, ""])
    for blocker in blockers:
        lines.append(f"- {blocker.get('tool', 'tool')}: {blocker.get('message')}")
        if blocker.get("command"):
            lines.append(f"  - command: `{blocker['command']}`")
        if blocker.get("guidance"):
            lines.append(f"  - guidance: {blocker['guidance']}")
        if blocker.get("stderr_excerpt"):
            lines.append(f"  - stderr: `{markdown_cell(blocker['stderr_excerpt'])}`")
    lines.append("")


def append_table(lines: list[str], title: str, headers: list[str], rows: list[JsonDict]) -> None:
    lines.extend([title, ""])
    append_table_rows(lines, headers, rows)


def append_table_rows(lines: list[str], headers: list[str], rows: list[JsonDict]) -> None:
    if not rows:
        lines.extend(["_None._", ""])
        return
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(markdown_cell(row.get(header)) for header in headers) + " |")
    lines.append("")


def confirmation_status(item: JsonDict) -> str:
    confirmation = item.get("test_record_confirmation") or {}
    return str(confirmation.get("status") or "")


def markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ")
    return text.replace("|", "\\|")


def link_or_code(value: Any) -> str:
    text = str(value)
    return text if text.startswith("http") else f"`{markdown_cell(text)}`"


def render_json(packet: JsonDict) -> str:
    return json.dumps(packet, indent=2, sort_keys=True) + "\n"
