#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import textwrap
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from urllib.parse import quote


CATEGORY_KEYWORDS = {
    "routing": (
        "orchestrator",
        "builder",
        "yolo",
        "debugger",
        "code-reviewer",
        "subagent",
        "delegate",
        "route",
        "agent",
    ),
    "autonomy": (
        "continue",
        "default",
        "defaults",
        "one-shot",
        "bounded",
        "self-contained",
        "interactively",
    ),
    "verbosity": (
        "concise",
        "brief",
        "verbosity",
        "too long",
        "too short",
    ),
    "artifact_usage": (
        "plan",
        "design",
        "artifact",
        "artifacts",
        "notes",
        "user-profile",
        "profile",
    ),
    "safety": (
        "approval",
        "approve",
        "reject",
        "refine",
        "must not",
        "do not",
        "forbidden",
        "no writes",
        "safe",
    ),
    "output_format": (
        "summary",
        "return format",
        "reply options",
        "format",
        "report",
        "bullet",
        "bullets",
    ),
    "validation": (
        "validate",
        "validation",
        "verify",
        "verification",
        "revalidate",
        "check",
    ),
}

CORRECTION_KEYWORDS = (
    "actually",
    "not what i asked",
    "you missed",
    "incorrect",
    "wrong",
    "instead",
    "don't",
    "do not",
    "no,",
    "please focus",
    "too much",
    "too broad",
)

EASY_TASK_KEYWORDS = (
    "quick",
    "tiny",
    "small",
    "simple",
    "one command",
    "status",
    "explain",
    "example",
    "where is",
    "what does",
    "how does",
)

PERMISSION_STALL_KEYWORDS = (
    "permission denied",
    "permission prompt",
    "requires permission",
    "requires approval",
    "approval required",
    "forbidden",
    "not allowed",
    "not permitted",
    "auth error",
    "authentication failed",
    "not authenticated",
    "credential expired",
    "expired credential",
)

TOOL_PATTERN_RULES = (
    {
        "label": "git",
        "regexes": (r"(^|[;&|({}\s])git(\s|$)",),
        "tool_names": (),
    },
    {
        "label": "git-spice/gs",
        "regexes": (r"(^|[;&|({}\s])(git-spice|gs)(\s|$)",),
        "tool_names": (),
    },
    {
        "label": "gh",
        "regexes": (r"(^|[;&|({}\s])gh(\s|$)",),
        "tool_names": (),
    },
    {
        "label": "zml",
        "regexes": (r"\bzml\b",),
        "tool_names": (),
    },
    {
        "label": "bazel test",
        "regexes": (r"(^|[;&|({}\s])bazel\s+test(\s|$)",),
        "tool_names": (),
    },
    {
        "label": "aws s3/upload/S3",
        "regexes": (r"(^|[;&|({}\s])aws\s+s3(\s|$)|s3://|\bs3\b|\bupload(ed)?\b",),
        "tool_names": (),
    },
    {
        "label": "python ad hoc/plotting",
        "regexes": (r"(^|[;&|({}\s])python3?(\s|$)|\bmatplotlib\b|\bplotting?\b",),
        "tool_names": (),
    },
    {
        "label": "tmux",
        "regexes": (r"(^|[;&|({}\s])tmux(\s|$)",),
        "tool_names": (),
    },
    {
        "label": "rg",
        "regexes": (r"(^|[;&|({}\s])rg(\s|$)",),
        "tool_names": ("grep",),
    },
    {
        "label": "jq",
        "regexes": (r"(^|[;&|({}\s])jq(\s|$)",),
        "tool_names": (),
    },
)

BROAD_ROOT_COMMAND_RE = re.compile(
    r"(^|[;&|({}\s])(find|rg|grep|ls|du|fd)\s+[^;&|]*?(^|\s)(/|/proc)(\s|$)"
)
SUSPICIOUS_TOOL_DURATION_MS = 5 * 60 * 1000
STALE_TOOL_AGE_MS = 5 * 60 * 1000
LATENCY_ATTRIBUTION_BUCKETS = 8

DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_SESSION_EXAMPLES = 12
DEFAULT_FOLLOWUP_EXAMPLES = 8
DEFAULT_WORKTREE_EXAMPLES = 30
DEFAULT_WORKTREE_FOLLOWUP_EXAMPLES = 3
DEFAULT_LONG_SPAN_MINUTES = 30


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
            "Summarize all local OpenCode sessions in the lookback window for /insights. "
            "Scanning is uncapped; example counts only control display length."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("summary", "raw-corrections", "latency", "tool-patterns"),
        default="summary",
        help=(
            "Report mode: summary preserves the default /insights output; "
            "raw-corrections prints root raw evidence for aggregate correction; "
            "latency classifies local time sinks and model-setting evidence; "
            "tool-patterns reports repeated command/tool payload patterns."
        ),
    )
    parser.add_argument(
        "--db-path",
        default=os.path.expanduser("~/.local/share/opencode/opencode.db"),
        help="Path to the OpenCode sqlite database",
    )
    parser.add_argument(
        "--scope",
        choices=("all", "worktree"),
        default="all",
        help="History scope to scan; defaults to all local OpenCode sessions",
    )
    parser.add_argument(
        "--worktree",
        default=os.getcwd(),
        help="Project directory to scan when --scope worktree is used; defaults to cwd",
    )
    parser.add_argument(
        "--lookback-days",
        type=positive_int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="Days of local history to scan by session time_updated; defaults to 30",
    )
    incremental = parser.add_mutually_exclusive_group()
    incremental.add_argument(
        "--since",
        metavar="TIMESTAMP",
        help=(
            "Override the lookback start time; accepts common ISO-ish local times "
            "such as 2026-05-31T20:00, '2026-05-31 20:00', or date-only."
        ),
    )
    incremental.add_argument(
        "--since-cache",
        metavar="PATH",
        help=(
            "Start after the latest session timestamp recorded in a previous "
            "--write-cache JSON file."
        ),
    )
    incremental.add_argument(
        "--since-session",
        metavar="SESSION_ID_OR_TITLE_SUBSTRING",
        help=(
            "Start after a matching session id/title; exact id/title matches "
            "are preferred, substring matches must be unique."
        ),
    )
    parser.add_argument(
        "--write-cache",
        metavar="PATH",
        help="Write compact scan metadata/counts JSON without message text.",
    )
    parser.add_argument(
        "--session-examples",
        type=non_negative_int,
        default=DEFAULT_SESSION_EXAMPLES,
        help=(
            "Recent root and child sessions to print as examples per section; "
            "0 hides examples. Counts still include every scanned session."
        ),
    )
    parser.add_argument(
        "--followup-examples",
        type=non_negative_int,
        default=DEFAULT_FOLLOWUP_EXAMPLES,
        help=(
            "Recent root follow-ups and child task prompts to print as examples; "
            "0 hides examples. Counts still include every scanned message."
        ),
    )
    parser.add_argument(
        "--worktree-examples",
        type=non_negative_int,
        default=DEFAULT_WORKTREE_EXAMPLES,
        help=(
            "Worktree coverage rows to print; 0 hides rows. Counts still include "
            "every scanned worktree."
        ),
    )
    parser.add_argument(
        "--worktree-followup-examples",
        type=non_negative_int,
        default=DEFAULT_WORKTREE_FOLLOWUP_EXAMPLES,
        help=(
            "Root follow-up examples to print for each dominant worktree; 0 hides the section. "
            "Counts still include every scanned message."
        ),
    )
    parser.add_argument(
        "--long-span-minutes",
        type=positive_int,
        default=DEFAULT_LONG_SPAN_MINUTES,
        help="Minimum session duration to report in --mode latency; defaults to 30",
    )
    return parser.parse_args()


def safe_json_loads(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def sqlite_table_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    rows = cur.execute(f"pragma table_info({table})").fetchall()
    return {row["name"] for row in rows}


def first_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def extract_reasoning_effort(value: object) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).replace("_", "").replace("-", "").lower()
            if normalized == "reasoningeffort":
                found = first_string(nested)
                if found:
                    return found
            if normalized == "reasoning" and isinstance(nested, dict):
                found = first_string(nested.get("effort"))
                if found:
                    return found
            found = extract_reasoning_effort(nested)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = extract_reasoning_effort(item)
            if found:
                return found
    return None


def extract_model_id(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("modelID", "model_id", "model"):
        found = first_string(value.get(key))
        if found:
            return found
    for nested in value.values():
        if isinstance(nested, dict):
            found = extract_model_id(nested)
            if found:
                return found
        elif isinstance(nested, list):
            for item in nested:
                found = extract_model_id(item)
                if found:
                    return found
    return None


def model_label(model_id: str | None, provider_id: str | None = None) -> str | None:
    if not model_id:
        return None
    if provider_id and not model_id.startswith(f"{provider_id}/"):
        return f"{provider_id}/{model_id}"
    return model_id


def parse_since_timestamp(raw: str) -> int:
    value = raw.strip()
    if not value:
        raise ValueError("empty timestamp")

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            "expected an ISO-ish timestamp such as 2026-05-31T20:00, "
            "'2026-05-31 20:00', or 2026-05-31"
        ) from exc
    return int(parsed.timestamp() * 1000)


def read_since_cache(path: str) -> tuple[int, str]:
    expanded = os.path.expanduser(path)
    with open(expanded, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("cache file does not contain a JSON object")

    latest_session = (
        data.get("latest_session") if isinstance(data.get("latest_session"), dict) else {}
    )
    latest_ms = latest_session.get("timestamp_ms")
    if isinstance(latest_ms, int):
        return latest_ms + 1, f"after latest session from cache {expanded}"

    scan_window = data.get("scan_window") if isinstance(data.get("scan_window"), dict) else {}
    until_ms = scan_window.get("until_ms")
    if isinstance(until_ms, int):
        return until_ms + 1, f"after previous cache scan window from {expanded}"

    raise ValueError("cache file has no latest_session.timestamp_ms or scan_window.until_ms")


def readonly_sqlite_connection(db_path: str) -> sqlite3.Connection:
    path = os.path.abspath(os.path.expanduser(db_path))
    uri = f"file:{quote(path)}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def shorten(text: str, width: int = 160) -> str:
    collapsed = " ".join(text.split())
    return textwrap.shorten(collapsed, width=width, placeholder="...")


def format_time(timestamp_ms: int | None) -> str:
    if not timestamp_ms:
        return "unknown"
    return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M")


def scan_window_line(args: argparse.Namespace, since_ms: int, until_ms: int) -> str:
    if getattr(args, "scan_window_note", None):
        return (
            f"- incremental window: {args.scan_window_note} by time_updated "
            f"({format_time(since_ms)} to {format_time(until_ms)})"
        )
    return (
        f"- lookback: last {args.lookback_days} days by time_updated "
        f"({format_time(since_ms)} to {format_time(until_ms)})"
    )


def session_time_range(sessions: list[dict]) -> str:
    timestamps = [session.get("time_updated") for session in sessions if session.get("time_updated")]
    if not timestamps:
        return "none"
    return f"{format_time(min(timestamps))} to {format_time(max(timestamps))}"


def duration_label(duration_ms: int | None) -> str:
    if duration_ms is None:
        return "unknown"
    seconds = duration_ms // 1000
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def chunks(items: list[str], size: int = 500) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def normalize_path(path: str | None, allow_relative: bool = False) -> str | None:
    if not path:
        return None
    expanded = os.path.expanduser(path)
    if not allow_relative and not os.path.isabs(expanded):
        return None
    return os.path.realpath(os.path.abspath(expanded))


def project_contains_worktree(project_worktree: str | None, target: str) -> bool:
    candidate = normalize_path(project_worktree)
    return bool(candidate and (target == candidate or target.startswith(candidate + os.sep)))


def path_inside_worktree(path: str | None, target: str) -> bool:
    candidate = normalize_path(path)
    return bool(candidate and (candidate == target or candidate.startswith(target + os.sep)))


def session_matches_worktree(session: dict, target: str) -> bool:
    return (
        project_contains_worktree(session.get("project_worktree"), target)
        or path_inside_worktree(session.get("directory"), target)
        or path_inside_worktree(session.get("path"), target)
    )


def session_kind(session: dict) -> str:
    return "root" if session.get("parent_id") is None else "child"


def worktree_label(session: dict) -> str:
    return session.get("project_worktree") or session.get("directory") or session.get("path") or "unknown location"


def format_session_location(session: dict) -> str:
    directory = session.get("directory") or session.get("path")
    project_worktree = session.get("project_worktree")
    if directory and project_worktree and directory != project_worktree:
        return f"{directory} (project {project_worktree})"
    return directory or project_worktree or "unknown location"


def print_list(title: str, lines: list[str]) -> None:
    print(title)
    if not lines:
        print("- none")
        print()
        return
    for line in lines:
        print(f"- {line}")
    print()


def print_cache_written(path: str | None) -> None:
    if path:
        print(f"Cache written: {path}")


def fetch_sessions(cur: sqlite3.Cursor, since_ms: int, until_ms: int) -> list[dict]:
    session_columns = sqlite_table_columns(cur, "session")
    optional_selects = [
        "s.agent as session_agent" if "agent" in session_columns else "null as session_agent",
        "s.data as session_data" if "data" in session_columns else "null as session_data",
        "s.metadata as session_metadata" if "metadata" in session_columns else "null as session_metadata",
    ]
    rows = cur.execute(
        f"""
    select
      s.id,
      s.title,
      s.parent_id,
      s.directory,
      s.path,
      s.time_created,
      s.time_updated,
      {", ".join(optional_selects)},
      p.id as project_id,
      p.worktree as project_worktree
    from session s
    join project p on p.id = s.project_id
    where s.time_archived is null
      and s.time_updated >= ?
      and s.time_updated <= ?
    order by s.time_updated desc
    """,
        (since_ms, until_ms),
    ).fetchall()
    sessions = []
    for row in rows:
        session = dict(row)
        session_data = safe_json_loads(session.pop("session_data", None))
        session_metadata = safe_json_loads(session.pop("session_metadata", None))
        session["metadata"] = {**session_data, **session_metadata}
        session["reasoning_effort"] = extract_reasoning_effort(session["metadata"])
        session["model_id"] = extract_model_id(session["metadata"])
        sessions.append(session)
    return sessions


def fetch_session_lookup_rows(cur: sqlite3.Cursor) -> list[dict]:
    rows = cur.execute(
        """
    select id, title, time_updated
    from session
    where time_archived is null
    order by time_updated desc
    """
    ).fetchall()
    return [dict(row) for row in rows]


def resolve_since_session(cur: sqlite3.Cursor, query: str) -> tuple[int, str]:
    needle = query.strip()
    if not needle:
        raise ValueError("empty --since-session query")

    rows = fetch_session_lookup_rows(cur)
    exact_matches = [
        row
        for row in rows
        if row["id"] == needle or (row.get("title") or "") == needle
    ]
    matches = exact_matches
    if not matches:
        lowered = needle.lower()
        matches = [
            row
            for row in rows
            if lowered in row["id"].lower() or lowered in (row.get("title") or "").lower()
        ]

    if not matches:
        raise ValueError(f"--since-session matched no session for {needle!r}")
    if len(matches) > 1:
        examples = "; ".join(
            f"{row['id']} [{format_time(row.get('time_updated'))}] {shorten(row.get('title') or '', 80)}"
            for row in matches[:8]
        )
        more = f"; ... {len(matches) - 8} more" if len(matches) > 8 else ""
        raise ValueError(
            f"ambiguous --since-session {needle!r}: matched {len(matches)} sessions: "
            f"{examples}{more}"
        )

    match = matches[0]
    if not match.get("time_updated"):
        raise ValueError(f"matched session {match['id']} has no time_updated")
    return (
        match["time_updated"] + 1,
        f"after session {match['id']} ({shorten(match.get('title') or '', 80)})",
    )


def select_scanned_sessions(
    cur: sqlite3.Cursor,
    *,
    since_ms: int,
    until_ms: int,
    worktree: str | None = None,
) -> tuple[list[dict], dict]:
    target = normalize_path(worktree, allow_relative=True) if worktree else None
    sessions = fetch_sessions(cur, since_ms=since_ms, until_ms=until_ms)
    if target:
        sessions = [session for session in sessions if session_matches_worktree(session, target)]

    meta: dict = {"target": target}
    if target:
        meta["matched_projects"] = sorted(
            {
                session["project_worktree"]
                for session in sessions
                if project_contains_worktree(session.get("project_worktree"), target)
            }
        )
        meta["matched_locations"] = sorted(
            {
                path
                for session in sessions
                for path in (session.get("directory"), session.get("path"))
                if path_inside_worktree(path, target)
            }
        )
    return sessions, meta


def assistant_agent_counts_by_session(
    cur: sqlite3.Cursor, session_ids: list[str]
) -> dict[str, Counter]:
    if not session_ids:
        return {}

    counts_by_session: dict[str, Counter] = defaultdict(Counter)
    for session_id_chunk in chunks(session_ids):
        placeholders = ",".join("?" for _ in session_id_chunk)
        rows = cur.execute(
            f"select session_id, data from message where session_id in ({placeholders})",
            session_id_chunk,
        ).fetchall()

        for row in rows:
            message = safe_json_loads(row["data"])
            if message.get("role") != "assistant":
                continue
            agent = message.get("agent")
            if agent:
                counts_by_session[row["session_id"]][agent] += 1
    return dict(counts_by_session)


def aggregate_agent_counts(
    counts_by_session: dict[str, Counter], sessions: list[dict]
) -> Counter:
    counts: Counter[str] = Counter()
    for session in sessions:
        counts.update(counts_by_session.get(session["id"], Counter()))
    return counts


def collect_user_messages(
    cur: sqlite3.Cursor, session_ids: list[str]
) -> list[dict]:
    if not session_ids:
        return []

    grouped: dict[tuple[str, str], dict] = {}
    for session_id_chunk in chunks(session_ids):
        placeholders = ",".join("?" for _ in session_id_chunk)
        rows = cur.execute(
            f"""
        select
          s.title as session_title,
          s.parent_id,
          s.directory,
          s.path,
          p.worktree as project_worktree,
          m.session_id,
          m.id as message_id,
          m.time_created as message_time,
          m.data as message_data,
          part.data as part_data
        from message m
        join session s on s.id = m.session_id
        join project p on p.id = s.project_id
        join part on part.message_id = m.id
        where m.session_id in ({placeholders})
        order by m.time_created asc, part.time_created asc
        """,
            session_id_chunk,
        ).fetchall()

        for row in rows:
            message = safe_json_loads(row["message_data"])
            part = safe_json_loads(row["part_data"])
            if message.get("role") != "user" or part.get("type") != "text":
                continue

            text = (part.get("text") or "").strip()
            if not text:
                continue

            key = (row["session_id"], row["message_id"])
            synthetic = bool(message.get("synthetic") or part.get("synthetic"))
            entry = grouped.setdefault(
                key,
                {
                    "session_id": row["session_id"],
                    "session_title": row["session_title"],
                    "parent_id": row["parent_id"],
                    "directory": row["directory"],
                    "path": row["path"],
                    "project_worktree": row["project_worktree"],
                    "message_time": row["message_time"],
                    "synthetic": False,
                    "chunks": [],
                },
            )
            entry["synthetic"] = bool(entry["synthetic"] or synthetic)
            entry["chunks"].append(text)

    all_messages: list[dict] = []
    for entry in grouped.values():
        text = " ".join(chunk.strip() for chunk in entry["chunks"] if chunk.strip())
        text = " ".join(text.split())
        if not text:
            continue
        entry["text"] = text
        del entry["chunks"]
        all_messages.append(entry)

    all_messages.sort(key=lambda item: item["message_time"] or 0, reverse=True)
    return all_messages


def collect_assistant_messages(cur: sqlite3.Cursor, session_ids: list[str]) -> list[dict]:
    if not session_ids:
        return []

    messages: list[dict] = []
    for session_id_chunk in chunks(session_ids):
        placeholders = ",".join("?" for _ in session_id_chunk)
        rows = cur.execute(
            f"""
        select
          s.title as session_title,
          s.parent_id,
          s.directory,
          s.path,
          p.worktree as project_worktree,
          m.session_id,
          m.id as message_id,
          m.time_created as message_time,
          m.data as message_data
        from message m
        join session s on s.id = m.session_id
        join project p on p.id = s.project_id
        where m.session_id in ({placeholders})
        order by m.time_created desc
        """,
            session_id_chunk,
        ).fetchall()

        for row in rows:
            message = safe_json_loads(row["message_data"])
            if message.get("role") != "assistant":
                continue
            tokens = message.get("tokens") if isinstance(message.get("tokens"), dict) else {}
            model_id = extract_model_id(message)
            messages.append(
                {
                    "session_id": row["session_id"],
                    "message_id": row["message_id"],
                    "session_title": row["session_title"],
                    "parent_id": row["parent_id"],
                    "directory": row["directory"],
                    "path": row["path"],
                    "project_worktree": row["project_worktree"],
                    "message_time": row["message_time"],
                    "agent": message.get("agent"),
                    "model_id": model_id,
                    "provider_id": message.get("providerID"),
                    "model": model_label(model_id, message.get("providerID")),
                    "reasoning_effort": extract_reasoning_effort(message),
                    "reasoning_tokens": tokens.get("reasoning"),
                }
            )
    messages.sort(key=lambda item: item["message_time"] or 0, reverse=True)
    return messages


def collect_parts(cur: sqlite3.Cursor, session_ids: list[str]) -> list[dict]:
    if not session_ids:
        return []

    parts: list[dict] = []
    for session_id_chunk in chunks(session_ids):
        placeholders = ",".join("?" for _ in session_id_chunk)
        rows = cur.execute(
            f"""
        select
          s.title as session_title,
          s.parent_id,
          s.directory,
          s.path,
          p.worktree as project_worktree,
          part.session_id,
          part.message_id,
          part.time_created,
          part.time_updated,
          part.data as part_data
        from part
        join session s on s.id = part.session_id
        join project p on p.id = s.project_id
        where part.session_id in ({placeholders})
        order by part.time_created desc
        """,
            session_id_chunk,
        ).fetchall()

        for row in rows:
            data = safe_json_loads(row["part_data"])
            parts.append(
                {
                    "session_id": row["session_id"],
                    "message_id": row["message_id"],
                    "session_title": row["session_title"],
                    "parent_id": row["parent_id"],
                    "directory": row["directory"],
                    "path": row["path"],
                    "project_worktree": row["project_worktree"],
                    "time_created": row["time_created"],
                    "time_updated": row["time_updated"],
                    "data": data,
                }
            )
    return parts


def collect_followups(messages: list[dict]) -> list[dict]:
    by_session: dict[str, list[dict]] = defaultdict(list)
    for message in messages:
        by_session[message["session_id"]].append(message)

    followups: list[dict] = []
    for messages in by_session.values():
        ordered = sorted(messages, key=lambda item: item["message_time"] or 0)
        for index, message in enumerate(ordered):
            if index > 0:
                followups.append(message)

    followups.sort(key=lambda item: item["message_time"] or 0, reverse=True)
    return followups


def category_counts(messages: list[dict]) -> Counter:
    counts: Counter[str] = Counter()
    for message in messages:
        lowered = message["text"].lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(keyword in lowered for keyword in keywords):
                counts[category] += 1
    return counts


def category_lines(messages: list[dict]) -> list[str]:
    return [f"{category}: {count}" for category, count in category_counts(messages).most_common()]


def compact_cache_payload(
    args: argparse.Namespace,
    sessions: list[dict],
    since_ms: int,
    until_ms: int,
    combined_evidence: list[dict],
) -> dict:
    root_count = sum(1 for session in sessions if session_kind(session) == "root")
    child_count = sum(1 for session in sessions if session_kind(session) == "child")
    worktree_counts = Counter(worktree_label(session) for session in sessions)
    latest_session = sessions[0] if sessions else None

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": args.mode,
        "scope": {
            "type": args.scope,
            "worktree": (
                normalize_path(args.worktree, allow_relative=True)
                if args.scope == "worktree"
                else None
            ),
        },
        "scan_window": {
            "since_ms": since_ms,
            "until_ms": until_ms,
            "since": datetime.fromtimestamp(since_ms / 1000).isoformat(timespec="seconds"),
            "until": datetime.fromtimestamp(until_ms / 1000).isoformat(timespec="seconds"),
            "incremental": bool(getattr(args, "scan_window_note", None)),
            "note": getattr(args, "scan_window_note", None),
        },
        "session_counts": {
            "total": len(sessions),
            "root": root_count,
            "child": child_count,
        },
        "top_worktrees": [
            {"worktree": worktree, "sessions": count}
            for worktree, count in worktree_counts.most_common(10)
        ],
        "top_categories": [
            {"category": category, "count": count}
            for category, count in category_counts(combined_evidence).most_common(10)
        ],
        "latest_session": (
            {
                "timestamp_ms": latest_session.get("time_updated"),
                "timestamp": format_time(latest_session.get("time_updated")),
                "id": latest_session.get("id"),
                "title": latest_session.get("title"),
            }
            if latest_session
            else None
        ),
    }


def write_scan_cache(path: str, payload: dict) -> str:
    expanded = os.path.expanduser(path)
    with open(expanded, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return expanded


def agent_lines(counts: Counter) -> list[str]:
    return [f"{agent}: {count}" for agent, count in counts.most_common()]


def session_example_lines(sessions: list[dict], count: int) -> list[str]:
    if count == 0:
        return []
    return [
        f"[{format_time(session['time_updated'])}] `{shorten(session['title'], 90)}` — {format_session_location(session)}"
        for session in sessions[:count]
    ]


def message_example_lines(messages: list[dict], count: int) -> list[str]:
    if count == 0:
        return []
    return [
        f"`{shorten(message['session_title'], 60)}` — {format_session_location(message)}: {shorten(message['text'])}"
        for message in messages[:count]
    ]


def worktree_followup_example_lines(
    sessions: list[dict],
    root_followups: list[dict],
    per_worktree_count: int,
) -> list[str]:
    if per_worktree_count == 0:
        return []

    coverage: dict[str, Counter] = defaultdict(Counter)
    for session in sessions:
        coverage[worktree_label(session)][session_kind(session)] += 1

    dominant_worktrees = [
        location
        for location, _ in sorted(
            coverage.items(),
            key=lambda item: (sum(item[1].values()), item[0]),
            reverse=True,
        )
    ]

    lines: list[str] = []
    for location in dominant_worktrees:
        messages = [
            message
            for message in root_followups
            if worktree_label(message) == location
        ]
        if not messages:
            continue
        for message in messages[:per_worktree_count]:
            lines.append(
                f"{location}: [{format_time(message['message_time'])}] "
                f"`{shorten(message['session_title'], 60)}` — {shorten(message['text'])}"
            )
    return lines


def worktree_coverage_lines(sessions: list[dict], count: int) -> list[str]:
    if count == 0:
        return []

    coverage: dict[str, Counter] = defaultdict(Counter)
    for session in sessions:
        coverage[worktree_label(session)][session_kind(session)] += 1

    rows = sorted(
        coverage.items(),
        key=lambda item: (sum(item[1].values()), item[0]),
        reverse=True,
    )
    lines = []
    for location, kinds in rows[:count]:
        root_count = kinds.get("root", 0)
        child_count = kinds.get("child", 0)
        total = root_count + child_count
        lines.append(f"{location}: {total} sessions ({root_count} root, {child_count} child)")
    if len(rows) > count:
        omitted = len(rows) - count
        lines.append(f"... {omitted} more worktree/location rows omitted from display")
    return lines


def keyword_message_lines(messages: list[dict], keywords: tuple[str, ...], count: int) -> list[str]:
    if count == 0:
        return []
    return message_example_lines(keyword_matches(messages, keywords), count)


def keyword_matches(messages: list[dict], keywords: tuple[str, ...]) -> list[dict]:
    return [
        message
        for message in messages
        if any(keyword in message["text"].lower() for keyword in keywords)
    ]


def top_category_label(messages: list[dict]) -> str:
    counts = category_counts(messages)
    if not counts:
        return "none"
    category, count = counts.most_common(1)[0]
    return f"{category}: {count}"


def tool_part_summary(parts: list[dict]) -> tuple[Counter, Counter, list[dict]]:
    tool_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    tool_parts: list[dict] = []
    for part in parts:
        data = part["data"]
        if data.get("type") != "tool":
            continue
        tool = data.get("tool") or "unknown-tool"
        state = data.get("state") if isinstance(data.get("state"), dict) else {}
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        top_metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        status = state.get("status") or "unknown-status"
        input_data = state.get("input") if isinstance(state.get("input"), dict) else {}
        combined_metadata = {**top_metadata, **metadata}
        task_session_id = None
        task_parent_session_id = None
        if tool == "task":
            task_session_id = (
                combined_metadata.get("sessionId")
                or combined_metadata.get("session_id")
                or combined_metadata.get("sessionID")
            )
            task_parent_session_id = (
                combined_metadata.get("parentSessionId")
                or combined_metadata.get("parent_session_id")
                or combined_metadata.get("parentSessionID")
            )
        duration_ms = None
        if part.get("time_created") and part.get("time_updated"):
            duration_ms = max(0, part["time_updated"] - part["time_created"])
        tool_part = {
            **part,
            "tool": tool,
            "status": status,
            "duration_ms": duration_ms,
            "input": input_data,
            "metadata": combined_metadata,
            "exit": metadata.get("exit"),
            "output": str(metadata.get("output") or state.get("output") or ""),
            "task_subagent_type": input_data.get("subagent_type") if tool == "task" else None,
            "task_description": input_data.get("description") if tool == "task" else None,
            "task_id": input_data.get("task_id") if tool == "task" else None,
            "task_command": input_data.get("command") if tool == "task" else None,
            "task_prompt": input_data.get("prompt") if tool == "task" else None,
            "task_session_id": task_session_id,
            "task_parent_session_id": task_parent_session_id,
            "reasoning_effort": extract_reasoning_effort({"input": input_data, "metadata": combined_metadata}),
        }
        tool_counts[tool] += 1
        status_counts[status] += 1
        tool_parts.append(tool_part)
    return tool_counts, status_counts, tool_parts


def compact_payload(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value or "")


def tool_payload(part: dict) -> str:
    input_data = part.get("input") if isinstance(part.get("input"), dict) else {}
    if part.get("tool") == "bash" and input_data.get("command"):
        return str(input_data["command"])
    if input_data:
        return compact_payload(input_data)
    return part.get("tool") or "unknown-tool"


def tool_payload_key(part: dict) -> str:
    return f"{part.get('tool') or 'unknown-tool'}: {tool_payload(part)}"


def regex_matches(text: str, regexes: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(re.search(regex, lowered) for regex in regexes)


def tool_part_matches_pattern(part: dict, rule: dict) -> bool:
    if part.get("tool") in rule["tool_names"]:
        return True
    return regex_matches(tool_payload(part), rule["regexes"])


def tool_pattern_summary_lines(tool_parts: list[dict], messages: list[dict]) -> list[str]:
    lines: list[str] = []
    for rule in TOOL_PATTERN_RULES:
        matching_parts = [part for part in tool_parts if tool_part_matches_pattern(part, rule)]
        payload_counts = Counter(tool_payload_key(part) for part in matching_parts)
        mention_count = sum(1 for message in messages if regex_matches(message["text"], rule["regexes"]))
        repeated_payloads = sum(1 for count in payload_counts.values() if count > 1)
        lines.append(
            f"{rule['label']}: actual tool payloads={len(matching_parts)}; "
            f"unique payloads={len(payload_counts)}; repeated payloads={repeated_payloads}; "
            f"weaker text mentions={mention_count}"
        )
    return lines


def top_payload_samples(tool_parts: list[dict], count: int) -> list[str]:
    if count == 0:
        return []
    lines: list[str] = []
    for rule in TOOL_PATTERN_RULES:
        payload_counts = Counter(
            tool_payload_key(part)
            for part in tool_parts
            if tool_part_matches_pattern(part, rule)
        )
        for payload, payload_count in sorted(payload_counts.items(), key=lambda item: (-item[1], item[0]))[:count]:
            lines.append(f"{rule['label']}: {payload_count}× {shorten(payload, 180)}")
    return lines


def text_mention_samples(messages: list[dict], count: int) -> list[str]:
    if count == 0:
        return []
    lines: list[str] = []
    for rule in TOOL_PATTERN_RULES:
        matches = [message for message in messages if regex_matches(message["text"], rule["regexes"])]
        for message in matches[:count]:
            lines.append(
                f"{rule['label']}: `{shorten(message['session_title'], 60)}` — "
                f"{format_session_location(message)}: {shorten(message['text'], 140)}"
            )
    return lines


def broad_root_value(value: object) -> bool:
    if not isinstance(value, str):
        return False
    cleaned = value.strip()
    return cleaned == "/" or cleaned == "/proc" or cleaned.startswith("/proc/")


def broad_root_scan_parts(tool_parts: list[dict]) -> list[dict]:
    matches: list[dict] = []
    for part in tool_parts:
        input_data = part.get("input") if isinstance(part.get("input"), dict) else {}
        if any(broad_root_value(input_data.get(field)) for field in ("path", "filePath")):
            matches.append(part)
            continue
        if part.get("tool") == "bash" and BROAD_ROOT_COMMAND_RE.search(tool_payload(part).lower()):
            matches.append(part)
    return matches


def permission_stall_tool_parts(tool_parts: list[dict]) -> list[dict]:
    matches: list[dict] = []
    for part in tool_parts:
        text = " ".join(
            str(value)
            for value in (
                part.get("tool"),
                part.get("status"),
                part.get("output"),
            )
        ).lower()
        strict_completed_keywords = (
            "auth error",
            "not authenticated",
            "permission denied",
            "approval required",
        )
        if part.get("status") == "completed" and not part.get("exit"):
            continue
        keywords = strict_completed_keywords if part.get("status") == "completed" else PERMISSION_STALL_KEYWORDS
        if any(keyword in text for keyword in keywords):
            matches.append(part)
    return matches


def running_or_stale_tool_parts(tool_parts: list[dict], now_ms: int) -> list[dict]:
    matches: list[dict] = []
    for part in tool_parts:
        if part.get("status") in {"completed", "error"}:
            continue
        last_updated = part.get("time_updated") or part.get("time_created") or now_ms
        age_ms = max(0, now_ms - last_updated)
        if age_ms >= STALE_TOOL_AGE_MS or part.get("status") in {"running", "pending"}:
            matches.append({**part, "age_ms": age_ms})
    return matches


def suspicious_long_tool_parts(tool_parts: list[dict]) -> list[dict]:
    return [
        part
        for part in tool_parts
        if isinstance(part.get("duration_ms"), int) and part["duration_ms"] >= SUSPICIOUS_TOOL_DURATION_MS
    ]


def tool_call_line(part: dict) -> str:
    return (
        f"{duration_label(part.get('duration_ms'))} {part.get('tool')} {part.get('status')} — "
        f"`{shorten(part.get('session_title') or '', 60)}`: {shorten(tool_payload(part), 120)}"
    )


def tool_duration_lines(tool_parts: list[dict], count: int) -> list[str]:
    if count == 0:
        return []
    ranked = sorted(
        tool_parts,
        key=lambda item: (item.get("duration_ms") is not None, item.get("duration_ms") or 0),
        reverse=True,
    )
    return [
        f"{duration_label(part.get('duration_ms'))} {part['tool']} {part['status']} — "
        f"`{shorten(part['session_title'], 60)}` — {format_session_location(part)}"
        for part in ranked[:count]
    ]


def permission_stall_lines(tool_parts: list[dict], messages: list[dict], count: int) -> list[str]:
    if count == 0:
        return []
    lines: list[str] = []
    for part in permission_stall_tool_parts(tool_parts):
        lines.append(
            f"tool {part['tool']} {part['status']} — `{shorten(part['session_title'], 60)}`: "
            f"{shorten(part.get('output') or '', 100)}"
        )
        if len(lines) >= count:
            return lines
    for line in keyword_message_lines(messages, PERMISSION_STALL_KEYWORDS, count - len(lines)):
        lines.append(f"user mention — {line}")
    return lines


def long_span_lines(sessions: list[dict], min_minutes: int, count: int) -> list[str]:
    if count == 0:
        return []
    threshold_ms = min_minutes * 60 * 1000
    ranked = []
    for session in sessions:
        if not session.get("time_created") or not session.get("time_updated"):
            continue
        duration_ms = session["time_updated"] - session["time_created"]
        if duration_ms >= threshold_ms:
            ranked.append((duration_ms, session))
    ranked.sort(reverse=True, key=lambda item: item[0])
    return [
        f"{duration_label(duration_ms)} `{shorten(session['title'], 70)}` — {format_session_location(session)}"
        for duration_ms, session in ranked[:count]
    ]


def first_tool_sample(parts: list[dict]) -> str:
    if not parts:
        return "none"
    ranked = sorted(
        parts,
        key=lambda item: (item.get("duration_ms") or 0, item.get("time_updated") or 0),
        reverse=True,
    )
    return tool_call_line(ranked[0])


def stuck_pattern_diagnostic_lines(
    tool_parts: list[dict],
    root_messages: list[dict],
    root_followups: list[dict],
    now_ms: int,
) -> list[str]:
    broad_root = broad_root_scan_parts(tool_parts)
    permission_tools = permission_stall_tool_parts(tool_parts)
    permission_mentions = keyword_matches(root_messages, PERMISSION_STALL_KEYWORDS)
    running_stale = running_or_stale_tool_parts(tool_parts, now_ms)
    suspicious_long = suspicious_long_tool_parts(tool_parts)
    correction_mentions = keyword_matches(root_followups, CORRECTION_KEYWORDS)
    easy_task_mentions = keyword_matches(root_messages, EASY_TASK_KEYWORDS)
    return [
        f"broad root scans (/ or /proc): {len(broad_root)}; sample={first_tool_sample(broad_root)}",
        (
            f"permission/auth stalls: {len(permission_tools)} tool payloads, "
            f"{len(permission_mentions)} root text mentions; sample={first_tool_sample(permission_tools)}"
        ),
        f"running/stale tool calls: {len(running_stale)}; sample={first_tool_sample(running_stale)}",
        (
            f"suspicious long tool calls (>= {duration_label(SUSPICIOUS_TOOL_DURATION_MS)}): "
            f"{len(suspicious_long)}; sample={first_tool_sample(suspicious_long)}"
        ),
        f"repeated correction-like root follow-ups: {len(correction_mentions)}",
        f"easy-task root prompts: {len(easy_task_mentions)}",
    ]


def model_setting_evidence_line(assistant_messages: list[dict]) -> str:
    model_counts = Counter(message.get("model_id") for message in assistant_messages if message.get("model_id"))
    reasoning_messages = [
        message
        for message in assistant_messages
        if isinstance(message.get("reasoning_tokens"), int) and message["reasoning_tokens"] > 0
    ]
    if model_counts and reasoning_messages:
        strength = "supported"
    elif model_counts or reasoning_messages:
        strength = "weak"
    else:
        strength = "absent"
    models = ", ".join(f"{model}: {count}" for model, count in model_counts.most_common(5)) or "none"
    return (
        f"{strength}: model metadata={models}; "
        f"assistant messages with reasoning-token evidence={len(reasoning_messages)}"
    )


def most_common_label(values: list[str | None]) -> str | None:
    counts = Counter(value for value in values if value)
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def assistant_session_summaries(assistant_messages: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for message in assistant_messages:
        grouped[message["session_id"]].append(message)

    summaries = {}
    for session_id, messages in grouped.items():
        summaries[session_id] = {
            "agent": most_common_label([message.get("agent") for message in messages]),
            "model": most_common_label([message.get("model") or message.get("model_id") for message in messages]),
            "reasoning_effort": most_common_label([message.get("reasoning_effort") for message in messages]),
            "reasoning_tokens": any(
                isinstance(message.get("reasoning_tokens"), int) and message["reasoning_tokens"] > 0
                for message in messages
            ),
            "assistant_messages": len(messages),
        }
    return summaries


def task_descriptor(part: dict, session_by_id: dict[str, dict]) -> str | None:
    child_session = session_by_id.get(part.get("task_session_id"))
    for value in (
        part.get("task_subagent_type"),
        child_session.get("title") if child_session else None,
        part.get("task_description"),
        part.get("task_command"),
        part.get("task_prompt"),
    ):
        text = first_string(value)
        if text:
            return shorten(text, 90)
    return None


def attribution_reasoning_label(summary: dict, part: dict, direct_message: dict | None, session: dict | None) -> str:
    effort = (
        summary.get("reasoning_effort")
        or part.get("reasoning_effort")
        or (direct_message or {}).get("reasoning_effort")
        or (session or {}).get("reasoning_effort")
    )
    if effort:
        return f"configured effort={effort}"
    if summary.get("reasoning_tokens") or (
        direct_message
        and isinstance(direct_message.get("reasoning_tokens"), int)
        and direct_message["reasoning_tokens"] > 0
    ):
        return "configured effort unknown; reasoning tokens present"
    if summary.get("assistant_messages") or direct_message:
        return "configured effort unknown; no reasoning-token evidence"
    return "unknown"


def long_call_attribution_records(
    tool_parts: list[dict],
    assistant_messages: list[dict],
    sessions: list[dict],
) -> list[dict]:
    session_by_id = {session["id"]: session for session in sessions}
    message_by_key = {
        (message.get("session_id"), message.get("message_id")): message
        for message in assistant_messages
        if message.get("message_id")
    }
    summaries_by_session = assistant_session_summaries(assistant_messages)

    records = []
    for part in suspicious_long_tool_parts(tool_parts):
        session = session_by_id.get(part.get("session_id"))
        direct_message = message_by_key.get((part.get("session_id"), part.get("message_id")))
        child_summary = summaries_by_session.get(part.get("task_session_id"), {})
        current_summary = summaries_by_session.get(part.get("session_id"), {})
        summary = child_summary if child_summary else current_summary

        descriptor = task_descriptor(part, session_by_id) if part.get("tool") == "task" else None
        actor = (
            descriptor
            or (direct_message or {}).get("agent")
            or summary.get("agent")
            or (session or {}).get("session_agent")
            or (session or {}).get("title")
            or "unknown"
        )
        if part.get("tool") == "task":
            tool_type = f"task/{descriptor}" if descriptor else "task/unknown"
        else:
            tool_type = part.get("tool") or "unknown"

        model = (
            summary.get("model")
            or (direct_message or {}).get("model")
            or model_label((session or {}).get("model_id"))
            or "unknown"
        )
        records.append(
            {
                "duration_ms": part.get("duration_ms") or 0,
                "actor": actor,
                "tool_type": tool_type,
                "model": model,
                "reasoning": attribution_reasoning_label(summary, part, direct_message, session),
                "session_title": part.get("session_title") or "unknown",
            }
        )
    return records


def attribution_bucket_lines(records: list[dict], field: str) -> list[str]:
    if not records:
        return []

    buckets: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_ms": 0, "max_ms": 0, "sample": ""})
    for record in records:
        label = record.get(field) or "unknown"
        bucket = buckets[label]
        bucket["count"] += 1
        bucket["total_ms"] += record.get("duration_ms") or 0
        bucket["max_ms"] = max(bucket["max_ms"], record.get("duration_ms") or 0)
        if not bucket["sample"]:
            bucket["sample"] = record.get("session_title") or "unknown"

    ranked = sorted(buckets.items(), key=lambda item: (item[1]["total_ms"], item[1]["count"], item[0]), reverse=True)
    shown = ranked[:LATENCY_ATTRIBUTION_BUCKETS]
    if "unknown" in buckets and all(label != "unknown" for label, _ in shown):
        shown = shown[:-1] + [("unknown", buckets["unknown"])] if shown else [("unknown", buckets["unknown"])]

    return [
        (
            f"{label}: {bucket['count']} calls, total {duration_label(bucket['total_ms'])}, "
            f"max {duration_label(bucket['max_ms'])}; sample=`{shorten(bucket['sample'], 70)}`"
        )
        for label, bucket in shown
    ]


def attribution_example_lines(records: list[dict], count: int) -> list[str]:
    if count == 0:
        return []
    ranked = sorted(records, key=lambda record: record.get("duration_ms") or 0, reverse=True)
    return [
        (
            f"{duration_label(record.get('duration_ms'))} actor={record['actor']}; "
            f"tool={record['tool_type']}; model={record['model']}; "
            f"reasoning={record['reasoning']}; session=`{shorten(record['session_title'], 60)}`"
        )
        for record in ranked[:count]
    ]


def print_tool_patterns_report(
    args: argparse.Namespace,
    sessions: list[dict],
    selection_meta: dict,
    since_ms: int,
    until_ms: int,
    messages: list[dict],
    parts: list[dict],
) -> None:
    root_sessions = [session for session in sessions if session_kind(session) == "root"]
    child_sessions = [session for session in sessions if session_kind(session) == "child"]
    _, status_counts, tool_parts = tool_part_summary(parts)

    print("Command/tool pattern evidence")
    if args.scope == "worktree":
        normalized = normalize_path(args.worktree, allow_relative=True) or args.worktree
        print(f"- scope: worktree {normalized}")
        print(
            "- matched project/worktree: "
            f"{', '.join(selection_meta.get('matched_projects', [])) or 'none'}"
        )
        print(
            "- matched session directory/path: "
            f"{', '.join(selection_meta.get('matched_locations', [])) or 'none'}"
        )
    else:
        print("- scope: all local OpenCode sessions")
    print(scan_window_line(args, since_ms, until_ms))
    print(f"- sessions scanned: {len(sessions)} total ({len(root_sessions)} root, {len(child_sessions)} child/subagent)")
    print(f"- tool calls scanned: {len(tool_parts)}; status={dict(status_counts.most_common())}")
    print("- evidence note: actual counts use tool part inputs; text mentions are weaker user-message evidence")
    print()

    print_list("Tracked command/tool patterns", tool_pattern_summary_lines(tool_parts, messages))
    print_list("Actual payload samples", top_payload_samples(tool_parts, args.followup_examples))
    print_list("Weaker text mention samples", text_mention_samples(messages, args.followup_examples))


def print_raw_corrections_report(
    args: argparse.Namespace,
    sessions: list[dict],
    selection_meta: dict,
    since_ms: int,
    until_ms: int,
    root_evidence: list[dict],
    child_evidence: list[dict],
    root_followups: list[dict],
) -> None:
    print("Raw-history correction evidence")
    if args.scope == "worktree":
        normalized = normalize_path(args.worktree, allow_relative=True) or args.worktree
        print(f"- scope: worktree {normalized}")
        print(
            "- worktree matching fields: project.worktree and session.directory/path "
            "are all considered"
        )
        print(
            "- matched project/worktree: "
            f"{', '.join(selection_meta.get('matched_projects', [])) or 'none'}"
        )
        print(
            "- matched session directory/path: "
            f"{', '.join(selection_meta.get('matched_locations', [])) or 'none'}"
        )
    else:
        print("- scope: all local OpenCode sessions")
    print(scan_window_line(args, since_ms, until_ms))
    print(f"- sessions scanned: {len(sessions)}")
    print(f"- aggregate top category: {top_category_label(root_evidence + child_evidence)}")
    print(f"- root raw top category: {top_category_label(root_evidence)}")
    print("- correction rule: current/root raw evidence overrides aggregate categories when they conflict")
    print()
    print_list("Worktree/location coverage", worktree_coverage_lines(sessions, args.worktree_examples))
    print_list(
        "Dominant worktree root follow-up examples",
        worktree_followup_example_lines(sessions, root_followups, args.worktree_followup_examples),
    )
    print_list("Root correction-like follow-ups", keyword_message_lines(root_followups, CORRECTION_KEYWORDS, args.followup_examples))
    print_list("Root raw evidence examples", message_example_lines(root_evidence, args.followup_examples))


def print_latency_report(
    args: argparse.Namespace,
    sessions: list[dict],
    selection_meta: dict,
    since_ms: int,
    until_ms: int,
    messages: list[dict],
    assistant_messages: list[dict],
    parts: list[dict],
) -> None:
    root_sessions = [session for session in sessions if session_kind(session) == "root"]
    child_sessions = [session for session in sessions if session_kind(session) == "child"]
    root_messages = [message for message in messages if message.get("parent_id") is None]
    root_followups = collect_followups(root_messages)
    tool_counts, status_counts, tool_parts = tool_part_summary(parts)
    task_tool_count = tool_counts.get("task", 0)
    attribution_records = long_call_attribution_records(tool_parts, assistant_messages, sessions)

    print("Latency and time-sink evidence")
    if args.scope == "worktree":
        normalized = normalize_path(args.worktree, allow_relative=True) or args.worktree
        print(f"- scope: worktree {normalized}")
        print(
            "- matched project/worktree: "
            f"{', '.join(selection_meta.get('matched_projects', [])) or 'none'}"
        )
        print(
            "- matched session directory/path: "
            f"{', '.join(selection_meta.get('matched_locations', [])) or 'none'}"
        )
    else:
        print("- scope: all local OpenCode sessions")
    print(scan_window_line(args, since_ms, until_ms))
    print(f"- sessions scanned: {len(sessions)} total ({len(root_sessions)} root, {len(child_sessions)} child/subagent)")
    print(f"- tool calls: {sum(tool_counts.values())} total; status={dict(status_counts.most_common())}")
    print(f"- subagent fanout: {len(child_sessions)} child sessions; task tool calls={task_tool_count}")
    print(f"- model-setting evidence: {model_setting_evidence_line(assistant_messages)}")
    print()
    print_list("Tool calls by tool", [f"{tool}: {count}" for tool, count in tool_counts.most_common()])
    print_list(
        "Stuck-pattern diagnostics",
        stuck_pattern_diagnostic_lines(tool_parts, root_messages, root_followups, until_ms),
    )
    print_list("Long-call buckets by actor/descriptor", attribution_bucket_lines(attribution_records, "actor"))
    print_list("Long-call buckets by tool/task type", attribution_bucket_lines(attribution_records, "tool_type"))
    print_list("Long-call buckets by model", attribution_bucket_lines(attribution_records, "model"))
    print_list("Long-call buckets by reasoning", attribution_bucket_lines(attribution_records, "reasoning"))
    print_list("Long-call attribution examples", attribution_example_lines(attribution_records, args.followup_examples))
    print_list("Longest tool call examples", tool_duration_lines(tool_parts, args.followup_examples))
    print_list("Long session spans", long_span_lines(sessions, args.long_span_minutes, args.session_examples))
    print_list("Permission/auth stall hints", permission_stall_lines(tool_parts, root_messages, args.followup_examples))
    print_list("Repeated correction hints", keyword_message_lines(root_followups, CORRECTION_KEYWORDS, args.followup_examples))
    print_list("Easy-task keyword hints", keyword_message_lines(root_messages, EASY_TASK_KEYWORDS, args.followup_examples))


def print_unavailable(args: argparse.Namespace, since_ms: int, until_ms: int, reason: str) -> None:
    print("Recent local history evidence")
    if args.scope == "worktree":
        normalized = normalize_path(args.worktree, allow_relative=True) or args.worktree
        print(f"- scope: worktree {normalized}")
    else:
        print("- scope: all local OpenCode sessions")
    print(scan_window_line(args, since_ms, until_ms))
    print(f"- unavailable: {reason}")


def main() -> int:
    args = parse_args()
    args.scan_window_note = None
    lookback_end = datetime.now()
    lookback_start = lookback_end - timedelta(days=args.lookback_days)
    since_ms = int(lookback_start.timestamp() * 1000)
    until_ms = int(lookback_end.timestamp() * 1000)

    try:
        if args.since:
            since_ms = parse_since_timestamp(args.since)
            args.scan_window_note = f"since {args.since!r}"
        elif args.since_cache:
            since_ms, args.scan_window_note = read_since_cache(args.since_cache)
    except Exception as exc:
        print_unavailable(args, since_ms, until_ms, f"invalid incremental scan window ({exc})")
        return 0

    worktree = args.worktree if args.scope == "worktree" else None
    normalized_worktree = normalize_path(args.worktree, allow_relative=True) if worktree else None

    if not os.path.exists(args.db_path):
        print_unavailable(args, since_ms, until_ms, f"OpenCode DB not found at {args.db_path}")
        return 0

    try:
        conn = readonly_sqlite_connection(args.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        if args.since_session:
            try:
                since_ms, args.scan_window_note = resolve_since_session(cur, args.since_session)
            except ValueError as exc:
                print_unavailable(args, since_ms, until_ms, str(exc))
                return 0

        sessions, selection_meta = select_scanned_sessions(
            cur,
            since_ms=since_ms,
            until_ms=until_ms,
            worktree=worktree,
        )
        root_sessions = [session for session in sessions if session_kind(session) == "root"]
        child_sessions = [session for session in sessions if session_kind(session) == "child"]
        session_ids = [session["id"] for session in sessions]

        counts_by_session = assistant_agent_counts_by_session(cur, session_ids)
        all_agent_counts = aggregate_agent_counts(counts_by_session, sessions)
        root_agent_counts = aggregate_agent_counts(counts_by_session, root_sessions)
        child_agent_counts = aggregate_agent_counts(counts_by_session, child_sessions)

        all_user_messages = collect_user_messages(cur, session_ids)
        human_user_messages = [message for message in all_user_messages if not message.get("synthetic")]
        synthetic_user_messages = [message for message in all_user_messages if message.get("synthetic")]
        followups = collect_followups(human_user_messages)
        synthetic_followups = collect_followups(synthetic_user_messages)

        root_messages = [message for message in human_user_messages if message.get("parent_id") is None]
        child_messages = [message for message in human_user_messages if message.get("parent_id") is not None]
        root_followups = [message for message in followups if message.get("parent_id") is None]
        child_followups = [message for message in followups if message.get("parent_id") is not None]

        root_evidence = root_followups if len(root_followups) >= 2 else root_messages
        child_evidence = child_followups if len(child_followups) >= 2 else child_messages
        combined_evidence = root_evidence + child_evidence
        cache_path = None
        if args.write_cache:
            cache_path = write_scan_cache(
                args.write_cache,
                compact_cache_payload(args, sessions, since_ms, until_ms, combined_evidence),
            )

        if args.mode == "raw-corrections":
            print_raw_corrections_report(
                args,
                sessions,
                selection_meta,
                since_ms,
                until_ms,
                root_evidence,
                child_evidence,
                root_followups,
            )
            print_cache_written(cache_path)
            return 0

        if args.mode == "tool-patterns":
            parts = collect_parts(cur, session_ids)
            print_tool_patterns_report(
                args,
                sessions,
                selection_meta,
                since_ms,
                until_ms,
                human_user_messages,
                parts,
            )
            print_cache_written(cache_path)
            return 0

        if args.mode == "latency":
            assistant_messages = collect_assistant_messages(cur, session_ids)
            parts = collect_parts(cur, session_ids)
            print_latency_report(
                args,
                sessions,
                selection_meta,
                since_ms,
                until_ms,
                human_user_messages,
                assistant_messages,
                parts,
            )
            print_cache_written(cache_path)
            return 0

        print("Recent local history evidence")
        if args.scope == "worktree":
            print(f"- scope: worktree {normalized_worktree or args.worktree}")
            print(
                "- matched project/worktree: "
                f"{', '.join(selection_meta.get('matched_projects', [])) or 'none'}"
            )
            print(
                "- matched session directory/path: "
                f"{', '.join(selection_meta.get('matched_locations', [])) or 'none'}"
            )
        else:
            print("- scope: all local OpenCode sessions")
        print(scan_window_line(args, since_ms, until_ms))
        window_name = "incremental window" if args.scan_window_note else "lookback"
        print(f"- scanning mode: all sessions in {window_name}; no root/child session caps")
        print(
            f"- sessions scanned: {len(sessions)} total "
            f"({len(root_sessions)} root, {len(child_sessions)} child/subagent)"
        )
        print(f"- session updated range: {session_time_range(sessions)}")
        print(
            f"- human user text messages scanned: {len(human_user_messages)} total "
            f"({len(root_messages)} root, {len(child_messages)} child/subagent)"
        )
        print(
            f"- human follow-ups found: {len(followups)} total "
            f"({len(root_followups)} root, {len(child_followups)} child/subagent)"
        )
        print(
            f"- synthetic user text messages separated: {len(synthetic_user_messages)} total "
            f"({len(synthetic_followups)} follow-ups)"
        )
        print(
            "- display note: counts/categories scan all matching sessions; "
            "examples below are truncated only for readability; synthetic user "
            "messages are reported separately from feedback hints"
        )
        print()

        print_list("Worktree/location coverage", worktree_coverage_lines(sessions, args.worktree_examples))
        print_list("Assistant agent counts (all scanned sessions)", agent_lines(all_agent_counts))
        print_list("Root assistant counts", agent_lines(root_agent_counts))
        print_list("Child/subagent assistant counts", agent_lines(child_agent_counts))
        print_list("Feedback category hints (root + child evidence)", category_lines(combined_evidence))
        print_list("Root feedback category hints", category_lines(root_evidence))
        print_list("Child/subagent context category hints", category_lines(child_evidence))

        print_list(
            "Recent root conversation examples",
            session_example_lines(root_sessions, args.session_examples),
        )
        print_list(
            "Recent child/subagent session examples",
            session_example_lines(child_sessions, args.session_examples),
        )
        print_list(
            "Dominant worktree root follow-up examples",
            worktree_followup_example_lines(
                sessions,
                root_followups,
                args.worktree_followup_examples,
            ),
        )
        print_list(
            "Root follow-up examples",
            message_example_lines(root_followups, args.followup_examples),
        )
        print_list(
            "Child/subagent task prompt examples",
            message_example_lines(child_messages, args.followup_examples),
        )
        print_list(
            "Synthetic user message examples",
            message_example_lines(synthetic_user_messages, args.followup_examples),
        )

        caveats = []
        if not sessions:
            empty_window_name = "incremental window" if args.scan_window_note else "lookback window"
            if args.scope == "worktree":
                caveats.append(
                    f"no sessions matched worktree {normalized_worktree or args.worktree} in the {empty_window_name}"
                )
            else:
                caveats.append(f"no sessions found in the {empty_window_name}")
        if len(root_followups) < 2:
            caveats.append(
                "root follow-up evidence is limited; root category hints may include initial user requests"
            )
        if child_messages and not child_followups:
            caveats.append(
                "child/subagent entries are task prompts/context, not direct user corrections"
            )
        if args.session_examples < max(len(root_sessions), len(child_sessions)):
            caveats.append("session examples are display-truncated; scanning/counts were not capped")
        if args.followup_examples < max(len(root_followups), len(child_messages)):
            caveats.append("message examples are display-truncated; scanning/counts were not capped")
        if not category_counts(combined_evidence) and sessions:
            caveats.append("no strong category signal detected in the scanned evidence messages")
        if synthetic_user_messages:
            caveats.append(
                "synthetic user messages were separated from human feedback category hints"
            )
        print_list("Evidence caveats", caveats)
        print_cache_written(cache_path)
        return 0
    except Exception as exc:
        print_unavailable(args, since_ms, until_ms, f"failed to summarize OpenCode history ({exc})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
