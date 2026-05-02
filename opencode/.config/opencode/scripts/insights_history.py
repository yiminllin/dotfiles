#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import textwrap
from collections import Counter, defaultdict
from datetime import datetime, timedelta


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

DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_SESSION_EXAMPLES = 12
DEFAULT_FOLLOWUP_EXAMPLES = 8
DEFAULT_WORKTREE_EXAMPLES = 30


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
    return parser.parse_args()


def safe_json_loads(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


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
) -> tuple[list[dict], list[dict]]:
    if not session_ids:
        return [], []

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
                    "chunks": [],
                },
            )
            entry["chunks"].append(text)

    by_session: dict[str, list[dict]] = defaultdict(list)
    for entry in grouped.values():
        text = " ".join(chunk.strip() for chunk in entry["chunks"] if chunk.strip())
        text = " ".join(text.split())
        if not text:
            continue
        entry["text"] = text
        del entry["chunks"]
        by_session[entry["session_id"]].append(entry)

    all_messages: list[dict] = []
    followups: list[dict] = []
    for messages in by_session.values():
        ordered = sorted(messages, key=lambda item: item["message_time"] or 0)
        for index, message in enumerate(ordered):
            all_messages.append(message)
            if index > 0:
                followups.append(message)

    all_messages.sort(key=lambda item: item["message_time"] or 0, reverse=True)
    followups.sort(key=lambda item: item["message_time"] or 0, reverse=True)
    return all_messages, followups


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
        conn = sqlite3.connect(args.db_path)
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

        all_user_messages, followups = collect_user_messages(cur, session_ids)
        root_messages = [message for message in all_user_messages if message.get("parent_id") is None]
        child_messages = [message for message in all_user_messages if message.get("parent_id") is not None]
        root_followups = [message for message in followups if message.get("parent_id") is None]
        child_followups = [message for message in followups if message.get("parent_id") is not None]

        root_evidence = root_followups if len(root_followups) >= 2 else root_messages
        child_evidence = child_followups if len(child_followups) >= 2 else child_messages
        combined_evidence = root_evidence + child_evidence

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
            f"- user text messages scanned: {len(all_user_messages)} total "
            f"({len(root_messages)} root, {len(child_messages)} child/subagent)"
        )
        print(
            f"- follow-ups found: {len(followups)} total "
            f"({len(root_followups)} root, {len(child_followups)} child/subagent)"
        )
        print(
            "- display note: counts/categories scan all matching sessions; "
            "examples below are truncated only for readability"
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
            "Root follow-up examples",
            message_example_lines(root_followups, args.followup_examples),
        )
        print_list(
            "Child/subagent task prompt examples",
            message_example_lines(child_messages, args.followup_examples),
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
        print_list("Evidence caveats", caveats)
        return 0
    except Exception as exc:
        print_unavailable(args, since_ms, until_ms, f"failed to summarize OpenCode history ({exc})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
