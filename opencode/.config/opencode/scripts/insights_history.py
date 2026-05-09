#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
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
        choices=("summary", "raw-corrections", "latency"),
        default="summary",
        help=(
            "Report mode: summary preserves the default /insights output; "
            "raw-corrections prints root raw evidence for aggregate correction; "
            "latency classifies local time sinks and model-setting evidence."
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


def safe_json_loads(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


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


def fetch_sessions(cur: sqlite3.Cursor, since_ms: int, until_ms: int) -> list[dict]:
    rows = cur.execute(
        """
    select
      s.id,
      s.title,
      s.parent_id,
      s.directory,
      s.path,
      s.time_created,
      s.time_updated,
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
    return [dict(row) for row in rows]


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
            messages.append(
                {
                    "session_id": row["session_id"],
                    "session_title": row["session_title"],
                    "parent_id": row["parent_id"],
                    "directory": row["directory"],
                    "path": row["path"],
                    "project_worktree": row["project_worktree"],
                    "message_time": row["message_time"],
                    "agent": message.get("agent"),
                    "model_id": message.get("modelID"),
                    "provider_id": message.get("providerID"),
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
    matches = [
        message
        for message in messages
        if any(keyword in message["text"].lower() for keyword in keywords)
    ]
    return message_example_lines(matches, count)


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
        status = state.get("status") or "unknown-status"
        duration_ms = None
        if part.get("time_created") and part.get("time_updated"):
            duration_ms = max(0, part["time_updated"] - part["time_created"])
        tool_part = {
            **part,
            "tool": tool,
            "status": status,
            "duration_ms": duration_ms,
            "exit": (state.get("metadata") or {}).get("exit"),
            "output": str((state.get("metadata") or {}).get("output") or ""),
        }
        tool_counts[tool] += 1
        status_counts[status] += 1
        tool_parts.append(tool_part)
    return tool_counts, status_counts, tool_parts


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
    print(
        f"- lookback: last {args.lookback_days} days by time_updated "
        f"({format_time(since_ms)} to {format_time(until_ms)})"
    )
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
    print(
        f"- lookback: last {args.lookback_days} days by time_updated "
        f"({format_time(since_ms)} to {format_time(until_ms)})"
    )
    print(f"- sessions scanned: {len(sessions)} total ({len(root_sessions)} root, {len(child_sessions)} child/subagent)")
    print(f"- tool calls: {sum(tool_counts.values())} total; status={dict(status_counts.most_common())}")
    print(f"- subagent fanout: {len(child_sessions)} child sessions; task tool calls={task_tool_count}")
    print(f"- model-setting evidence: {model_setting_evidence_line(assistant_messages)}")
    print()
    print_list("Tool calls by tool", [f"{tool}: {count}" for tool, count in tool_counts.most_common()])
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
    print(
        f"- lookback: last {args.lookback_days} days by time_updated "
        f"({format_time(since_ms)} to {format_time(until_ms)})"
    )
    print(f"- unavailable: {reason}")


def main() -> int:
    args = parse_args()
    lookback_end = datetime.now()
    lookback_start = lookback_end - timedelta(days=args.lookback_days)
    since_ms = int(lookback_start.timestamp() * 1000)
    until_ms = int(lookback_end.timestamp() * 1000)
    worktree = args.worktree if args.scope == "worktree" else None
    normalized_worktree = normalize_path(args.worktree, allow_relative=True) if worktree else None

    if not os.path.exists(args.db_path):
        print_unavailable(args, since_ms, until_ms, f"OpenCode DB not found at {args.db_path}")
        return 0

    try:
        conn = readonly_sqlite_connection(args.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

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
        print(
            f"- lookback: last {args.lookback_days} days by time_updated "
            f"({format_time(since_ms)} to {format_time(until_ms)})"
        )
        print("- scanning mode: all sessions in lookback; no root/child session caps")
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
            if args.scope == "worktree":
                caveats.append(
                    f"no sessions matched worktree {normalized_worktree or args.worktree} in the lookback window"
                )
            else:
                caveats.append("no sessions found in the lookback window")
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
        return 0
    except Exception as exc:
        print_unavailable(args, since_ms, until_ms, f"failed to summarize OpenCode history ({exc})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
