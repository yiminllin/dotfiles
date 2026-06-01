#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import textwrap
from datetime import datetime, timedelta
from urllib.parse import quote, urlsplit, urlunsplit


DEFAULT_DB_PATH = "~/.local/share/opencode/opencode.db"
DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_STALE_MINUTES = 10
DEFAULT_LIMIT = 50
RECENT_ERROR_MINUTES = 60

ACTIVE_STATUSES = {"running", "pending"}
SECRET_KEY_RE = re.compile(
    r"(api[-_]?key|authorization|cookie|credential|password|private[-_]?key|refresh[-_]?token|secret|token)",
    re.IGNORECASE,
)
SECRET_KEY_PATTERN = (
    r"api[-_]?key|authorization|cookie|credential|password|private[-_]?key|"
    r"refresh[-_]?token|secret|token"
)
SECRET_ASSIGNMENT_RE = re.compile(
    rf"(?i)\b({SECRET_KEY_PATTERN})\b\s*([=:])\s*(['\"]?)[^\s;&'\"]+"
)
SECRET_FLAG_RE = re.compile(
    rf"(?i)(--(?:{SECRET_KEY_PATTERN})\s+)(['\"]?)[^\s;&'\"]+"
)
BEARER_VALUE_RE = re.compile(r"(?i)\bBearer\s+[^\s;&'\"]+")
CONTENT_KEYS = {
    "content",
    "newString",
    "oldString",
    "output",
    "patchText",
    "prompt",
    "stderr",
    "stdout",
    "text",
}


def positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def non_negative_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only diagnostic for stale/running/pending OpenCode tool and "
            "subagent task records after interrupts."
        )
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help="Path to the OpenCode sqlite database; defaults to ~/.local/share/opencode/opencode.db",
    )
    parser.add_argument(
        "--lookback-days",
        type=positive_int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="Days of local tool history to scan by part time_updated; defaults to 30",
    )
    parser.add_argument(
        "--stale-minutes",
        type=non_negative_int,
        default=DEFAULT_STALE_MINUTES,
        help="Minutes since last update before an active record is marked stale; defaults to 10",
    )
    parser.add_argument(
        "--limit",
        type=non_negative_int,
        default=DEFAULT_LIMIT,
        help="Maximum records to display; defaults to 50; 0 prints only the summary",
    )
    parser.add_argument(
        "--include-recent-errors",
        action="store_true",
        help=f"Also include error records updated in the last {RECENT_ERROR_MINUTES} minutes",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format; defaults to text",
    )
    return parser.parse_args()


def readonly_sqlite_connection(db_path: str) -> sqlite3.Connection:
    path = os.path.abspath(os.path.expanduser(db_path))
    uri = f"file:{quote(path)}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def safe_json_loads(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def shorten(text: str, width: int = 160) -> str:
    collapsed = " ".join(text.split())
    return textwrap.shorten(collapsed, width=width, placeholder="...")


def scrub_string(value: str, width: int = 160) -> str:
    scrubbed = SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>",
        value,
    )
    scrubbed = SECRET_FLAG_RE.sub(lambda match: f"{match.group(1)}<redacted>", scrubbed)
    scrubbed = BEARER_VALUE_RE.sub("Bearer <redacted>", scrubbed)
    return shorten(scrubbed, width=width)


def scrub_url(value: str) -> str:
    parts = urlsplit(value)
    netloc = parts.netloc
    if "@" in netloc:
        host = parts.hostname or "<redacted-host>"
        netloc = f"{host}:{parts.port}" if parts.port else host
    if parts.query or parts.fragment:
        return urlunsplit((parts.scheme, netloc, parts.path, "<redacted>", ""))
    if netloc != parts.netloc:
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    return value


def format_time(timestamp_ms: int | None) -> str:
    if not timestamp_ms:
        return "unknown"
    return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def duration_label(duration_ms: int | None) -> str:
    if duration_ms is None:
        return "unknown"
    seconds = max(0, duration_ms) // 1000
    days, seconds = divmod(seconds, 24 * 60 * 60)
    hours, seconds = divmod(seconds, 60 * 60)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}d{hours:02d}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def session_kind(parent_id: str | None) -> str:
    return "root" if parent_id is None else "child/subagent"


def format_session_location(record: dict) -> str:
    directory = record.get("directory") or record.get("path")
    project_worktree = record.get("project_worktree")
    if directory and project_worktree and directory != project_worktree:
        return f"{directory} (project {project_worktree})"
    return directory or project_worktree or "unknown location"


def payload_piece(key: str, value: object) -> str | None:
    if value == "":
        return None
    if SECRET_KEY_RE.search(key):
        return f"{key}=<redacted>"
    if key in CONTENT_KEYS:
        if isinstance(value, str):
            return f"{key}=<{len(value)} chars>"
        return f"{key}=<{type(value).__name__}>"
    if isinstance(value, str):
        text = scrub_url(value) if key == "url" else value
        return f"{key}={scrub_string(text, 120)}"
    if isinstance(value, (int, float, bool)) or value is None:
        return f"{key}={value}"
    if isinstance(value, (list, dict)):
        return f"{key}=<{type(value).__name__}, {len(value)} items>"
    return None


def summarize_input(tool: str, input_data: dict) -> str:
    if not input_data:
        return "no input payload"

    if tool == "task":
        keys = ("subagent_type", "description", "task_id", "command", "prompt")
    elif tool == "bash":
        keys = ("description", "workdir", "timeout", "command")
    elif tool in {"read", "glob", "grep", "webfetch"}:
        keys = ("filePath", "path", "pattern", "include", "url", "offset", "limit", "format")
    elif tool in {"apply_patch", "edit", "write"}:
        keys = ("filePath", "patchText", "oldString", "newString", "content")
    else:
        keys = tuple(input_data.keys())

    pieces = [payload_piece(key, input_data.get(key)) for key in keys if key in input_data]
    summary = "; ".join(piece for piece in pieces if piece)
    return summary or "input payload omitted"


def metadata_says_interrupted(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if "interrupt" in str(key).lower():
                return True
            if key in {"output", "stdout", "stderr"}:
                continue
            if metadata_says_interrupted(nested):
                return True
    elif isinstance(value, list):
        return any(metadata_says_interrupted(item) for item in value)
    elif isinstance(value, str):
        lowered = value.lower().strip()
        return lowered in {"interrupt", "interrupted", "user_interrupted"}
    return False


def fetch_tool_rows(cur: sqlite3.Cursor, since_ms: int, until_ms: int) -> list[sqlite3.Row]:
    return cur.execute(
        """
    select
      part.id as part_id,
      part.message_id,
      part.session_id,
      part.time_created as part_time_created,
      part.time_updated as part_time_updated,
      part.data as part_data,
      s.title as session_title,
      s.parent_id as session_parent_id,
      s.directory,
      s.path,
      s.agent as session_agent,
      p.worktree as project_worktree
    from part
    join session s on s.id = part.session_id
    join project p on p.id = s.project_id
    where s.time_archived is null
      and part.time_updated >= ?
      and part.time_updated <= ?
    order by part.time_updated desc
    """,
        (since_ms, until_ms),
    ).fetchall()


def fetch_sessions_by_id(cur: sqlite3.Cursor, session_ids: set[str]) -> dict[str, dict]:
    if not session_ids:
        return {}
    sessions: dict[str, dict] = {}
    session_list = sorted(session_ids)
    for index in range(0, len(session_list), 500):
        chunk = session_list[index : index + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows = cur.execute(
            f"""
        select
          s.id,
          s.title,
          s.parent_id,
          s.directory,
          s.path,
          s.agent,
          s.time_updated,
          p.worktree as project_worktree
        from session s
        join project p on p.id = s.project_id
        where s.id in ({placeholders})
        """,
            chunk,
        ).fetchall()
        sessions.update({row["id"]: dict(row) for row in rows})
    return sessions


def part_duration_ms(status: str, created_ms: int | None, updated_ms: int | None, now_ms: int) -> int | None:
    if not created_ms:
        return None
    end_ms = now_ms if status in ACTIVE_STATUSES else updated_ms
    if not end_ms:
        return None
    return max(0, end_ms - created_ms)


def row_to_candidate(row: sqlite3.Row, now_ms: int) -> dict | None:
    data = safe_json_loads(row["part_data"])
    if data.get("type") != "tool":
        return None
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    status = state.get("status") or "unknown"
    tool = data.get("tool") or "unknown-tool"
    input_data = state.get("input") if isinstance(state.get("input"), dict) else {}
    state_metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
    top_metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    updated_ms = row["part_time_updated"]
    created_ms = row["part_time_created"]
    age_ms = max(0, now_ms - (updated_ms or created_ms or now_ms))
    return {
        "part_id": row["part_id"],
        "call_id": data.get("callID"),
        "message_id": row["message_id"],
        "session_id": row["session_id"],
        "session_title": row["session_title"],
        "session_kind": session_kind(row["session_parent_id"]),
        "session_parent_id": row["session_parent_id"],
        "session_agent": row["session_agent"],
        "directory": row["directory"],
        "path": row["path"],
        "project_worktree": row["project_worktree"],
        "tool": tool,
        "status": status,
        "time_created": created_ms,
        "time_updated": updated_ms,
        "age_ms": age_ms,
        "duration_ms": part_duration_ms(status, created_ms, updated_ms, now_ms),
        "payload_summary": summarize_input(tool, input_data),
        "interrupted": metadata_says_interrupted(state_metadata) or metadata_says_interrupted(top_metadata),
        "error_summary": payload_piece("error", state.get("error")) if state.get("error") else None,
        "subagent_type": input_data.get("subagent_type") if tool == "task" else None,
        "subagent_task_id": input_data.get("task_id") if tool == "task" else None,
        "subagent_session_id": state_metadata.get("sessionId") if tool == "task" else None,
        "subagent_parent_session_id": state_metadata.get("parentSessionId") if tool == "task" else None,
    }


def collect_candidates(
    cur: sqlite3.Cursor,
    args: argparse.Namespace,
    since_ms: int,
    until_ms: int,
    now_ms: int,
) -> list[dict]:
    recent_error_since_ms = now_ms - RECENT_ERROR_MINUTES * 60 * 1000
    candidates = []
    subagent_session_ids: set[str] = set()

    for row in fetch_tool_rows(cur, since_ms, until_ms):
        candidate = row_to_candidate(row, now_ms)
        if not candidate:
            continue
        status = candidate["status"]
        if status in ACTIVE_STATUSES:
            candidates.append(candidate)
        elif (
            args.include_recent_errors
            and status == "error"
            and (candidate.get("time_updated") or 0) >= recent_error_since_ms
        ):
            candidates.append(candidate)

        if candidate.get("subagent_session_id"):
            subagent_session_ids.add(candidate["subagent_session_id"])

    child_sessions = fetch_sessions_by_id(cur, subagent_session_ids)
    for candidate in candidates:
        child = child_sessions.get(candidate.get("subagent_session_id"))
        if child:
            candidate["subagent_session_title"] = child.get("title")
            candidate["subagent_session_kind"] = session_kind(child.get("parent_id"))
            candidate["subagent_session_location"] = format_session_location(child)
            candidate["subagent_session_agent"] = child.get("agent")
            candidate["subagent_session_updated"] = child.get("time_updated")

    return candidates


def ranked_records(candidates: list[dict], stale_ms: int, limit: int) -> list[dict]:
    def sort_key(record: dict) -> tuple:
        active = record["status"] in ACTIVE_STATUSES
        stale = active and record["age_ms"] >= stale_ms
        return (stale, active, record.get("time_updated") or 0, record["age_ms"])

    records = sorted(candidates, key=sort_key, reverse=True)
    return records[:limit] if limit else []


def record_to_json(record: dict, stale_ms: int) -> dict:
    return {
        "part_id": record.get("part_id"),
        "call_id": record.get("call_id"),
        "tool": record.get("tool"),
        "status": record.get("status"),
        "stale": record.get("status") in ACTIVE_STATUSES and record.get("age_ms", 0) >= stale_ms,
        "interrupted": record.get("interrupted"),
        "age_ms": record.get("age_ms"),
        "age": duration_label(record.get("age_ms")),
        "duration_ms": record.get("duration_ms"),
        "duration": duration_label(record.get("duration_ms")),
        "time_created": record.get("time_created"),
        "time_updated": record.get("time_updated"),
        "created_at": format_time(record.get("time_created")),
        "updated_at": format_time(record.get("time_updated")),
        "session": {
            "id": record.get("session_id"),
            "title": record.get("session_title"),
            "kind": record.get("session_kind"),
            "agent": record.get("session_agent"),
            "location": format_session_location(record),
        },
        "subagent": {
            "type": record.get("subagent_type"),
            "task_id": record.get("subagent_task_id"),
            "session_id": record.get("subagent_session_id"),
            "parent_session_id": record.get("subagent_parent_session_id"),
            "session_title": record.get("subagent_session_title"),
            "session_kind": record.get("subagent_session_kind"),
            "session_location": record.get("subagent_session_location"),
            "session_agent": record.get("subagent_session_agent"),
            "session_updated_at": format_time(record.get("subagent_session_updated")),
        }
        if record.get("tool") == "task"
        else None,
        "payload_summary": record.get("payload_summary"),
        "error_summary": record.get("error_summary"),
    }


def summary(
    candidates: list[dict],
    stale_ms: int,
    args: argparse.Namespace,
    since_ms: int,
    until_ms: int,
) -> dict:
    active = [record for record in candidates if record["status"] in ACTIVE_STATUSES]
    stale = [record for record in active if record["age_ms"] >= stale_ms]
    task_records = [record for record in candidates if record.get("tool") == "task"]
    recent_errors = [record for record in candidates if record["status"] == "error"]
    return {
        "lookback_days": args.lookback_days,
        "lookback_start": format_time(since_ms),
        "lookback_end": format_time(until_ms),
        "stale_minutes": args.stale_minutes,
        "limit": args.limit,
        "include_recent_errors": bool(args.include_recent_errors),
        "records_matched": len(candidates),
        "active_records": len(active),
        "stale_active_records": len(stale),
        "task_tool_records": len(task_records),
        "recent_error_records": len(recent_errors),
    }


def print_text_report(
    records: list[dict],
    candidates: list[dict],
    args: argparse.Namespace,
    since_ms: int,
    until_ms: int,
    stale_ms: int,
) -> None:
    report_summary = summary(candidates, stale_ms, args, since_ms, until_ms)
    print("OpenCode stale tool diagnostics")
    print(f"- db: {os.path.expanduser(args.db_path)}")
    print(
        f"- lookback: last {args.lookback_days} days by part time_updated "
        f"({report_summary['lookback_start']} to {report_summary['lookback_end']})"
    )
    print(f"- stale threshold: {args.stale_minutes} minutes")
    print(
        "- matched: "
        f"{report_summary['records_matched']} records; "
        f"active={report_summary['active_records']}; "
        f"stale-active={report_summary['stale_active_records']}; "
        f"task={report_summary['task_tool_records']}; "
        f"recent-errors={report_summary['recent_error_records']}"
    )
    print()

    if not records:
        print("Active/stale/recent-error records")
        print("- none")
        return

    print("Active/stale/recent-error records")
    for record in records:
        if record["status"] == "error":
            record_label = "recent-error"
        elif record["age_ms"] >= stale_ms:
            record_label = "stale"
        else:
            record_label = "active"
        interrupted = "yes" if record.get("interrupted") else "no"
        print(
            f"- {record['tool']} {record['status']} ({record_label}; interrupted={interrupted}; "
            f"age={duration_label(record['age_ms'])}; duration={duration_label(record['duration_ms'])})"
        )
        print(
            f"  session: {record['session_kind']} `{shorten(record['session_title'] or '', 70)}` — "
            f"{format_session_location(record)}"
        )
        if record.get("tool") == "task":
            child_title = record.get("subagent_session_title") or "unknown child session"
            child_id = record.get("subagent_session_id") or "unknown"
            print(
                f"  subagent: {record.get('subagent_type') or 'unknown'}; "
                f"task_id={record.get('subagent_task_id') or 'unknown'}; "
                f"session={child_id} `{shorten(child_title, 70)}`"
            )
        print(f"  updated: {format_time(record.get('time_updated'))}")
        print(f"  payload: {shorten(record.get('payload_summary') or '', 220)}")
        if record.get("error_summary"):
            print(f"  error: {shorten(record['error_summary'], 180)}")


def print_json_report(
    records: list[dict],
    candidates: list[dict],
    args: argparse.Namespace,
    since_ms: int,
    until_ms: int,
    stale_ms: int,
) -> None:
    payload = {
        "summary": summary(candidates, stale_ms, args, since_ms, until_ms),
        "records": [record_to_json(record, stale_ms) for record in records],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def print_error(args: argparse.Namespace, message: str) -> None:
    if args.format == "json":
        print(json.dumps({"error": message, "db_path": os.path.expanduser(args.db_path)}, indent=2, sort_keys=True))
    else:
        print("OpenCode stale tool diagnostics", file=sys.stderr)
        print(f"- unavailable: {message}", file=sys.stderr)


def main() -> int:
    args = parse_args()
    db_path = os.path.expanduser(args.db_path)
    if not os.path.exists(db_path):
        print_error(args, f"OpenCode DB not found at {db_path}")
        return 2
    if not os.access(db_path, os.R_OK):
        print_error(args, f"OpenCode DB is not readable at {db_path}")
        return 2

    now = datetime.now()
    since_ms = int((now - timedelta(days=args.lookback_days)).timestamp() * 1000)
    until_ms = int(now.timestamp() * 1000)
    stale_ms = args.stale_minutes * 60 * 1000

    try:
        conn = readonly_sqlite_connection(args.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        candidates = collect_candidates(cur, args, since_ms, until_ms, until_ms)
    except sqlite3.Error as exc:
        print_error(args, f"failed to read OpenCode DB ({exc})")
        return 2

    records = ranked_records(candidates, stale_ms, args.limit)
    if args.format == "json":
        print_json_report(records, candidates, args, since_ms, until_ms, stale_ms)
    else:
        print_text_report(records, candidates, args, since_ms, until_ms, stale_ms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
