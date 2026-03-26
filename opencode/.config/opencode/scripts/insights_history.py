#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import textwrap
from collections import Counter, defaultdict
from datetime import datetime


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

ROOT_SESSION_LOOKBACK_EXTRA = 4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize recent OpenCode history for /insights"
    )
    parser.add_argument(
        "--db-path",
        default=os.path.expanduser("~/.local/share/opencode/opencode.db"),
        help="Path to the OpenCode sqlite database",
    )
    parser.add_argument(
        "--worktree",
        default=os.getcwd(),
        help="Project directory to summarize; defaults to current working directory",
    )
    parser.add_argument(
        "--session-limit",
        type=int,
        default=6,
        help="Number of recent sessions to sample",
    )
    parser.add_argument(
        "--followup-limit",
        type=int,
        default=4,
        help="Number of follow-up examples to print",
    )
    return parser.parse_args()


def safe_json_loads(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def shorten(text: str, width: int = 160) -> str:
    collapsed = " ".join(text.split())
    return textwrap.shorten(collapsed, width=width, placeholder="...")


def format_time(timestamp_ms: int | None) -> str:
    if not timestamp_ms:
        return "unknown"
    return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M")


def match_project(cur: sqlite3.Cursor, worktree: str) -> sqlite3.Row | None:
    target = os.path.realpath(os.path.abspath(worktree))
    rows = cur.execute("select id, worktree from project").fetchall()
    matches = []

    for row in rows:
        candidate = os.path.realpath(row["worktree"])
        if target == candidate or target.startswith(candidate + os.sep):
            matches.append((len(candidate), row))

    if not matches:
        return None

    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def assistant_agent_counts_by_session(
    cur: sqlite3.Cursor, session_ids: list[str]
) -> dict[str, Counter]:
    if not session_ids:
        return {}

    placeholders = ",".join("?" for _ in session_ids)
    rows = cur.execute(
        f"select session_id, data from message where session_id in ({placeholders})",
        session_ids,
    ).fetchall()

    counts_by_session: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        message = safe_json_loads(row["data"])
        if message.get("role") != "assistant":
            continue
        agent = message.get("agent")
        if agent:
            counts_by_session[row["session_id"]][agent] += 1
    return dict(counts_by_session)


def assistant_agent_counts(cur: sqlite3.Cursor, session_ids: list[str]) -> Counter:
    counts: Counter[str] = Counter()
    for session_counts in assistant_agent_counts_by_session(cur, session_ids).values():
        counts.update(session_counts)
    return counts


def select_recent_sessions(
    cur: sqlite3.Cursor, project_id: str, limit: int
) -> tuple[list[dict], dict]:
    root_rows = cur.execute(
        """
    select id, title, parent_id, time_created, time_updated
    from session
    where project_id = ? and time_archived is null and parent_id is null
    order by time_updated desc
    limit ?
    """,
        (project_id, limit + ROOT_SESSION_LOOKBACK_EXTRA),
    ).fetchall()

    if root_rows:
        root_sessions = [dict(row) for row in root_rows]
        counts_by_session = assistant_agent_counts_by_session(
            cur, [session["id"] for session in root_sessions]
        )
        for session in root_sessions:
            session["assistant_counts"] = counts_by_session.get(
                session["id"], Counter()
            )

        orchestrator_root_sessions = [
            session
            for session in root_sessions
            if session["assistant_counts"].get("orchestrator", 0) > 0
        ]
        selected = orchestrator_root_sessions or root_sessions
        sampling_mode = (
            "recent root sessions with orchestrator activity"
            if orchestrator_root_sessions
            else "recent root sessions"
        )
        skipped_newest = False
        if len(selected) > 3:
            selected = selected[1:]
            skipped_newest = True

        return selected[:limit], {
            "sampling_mode": sampling_mode,
            "skipped_newest": skipped_newest,
            "used_root_only": True,
        }

    fallback_rows = cur.execute(
        """
    select id, title, parent_id, time_created, time_updated
    from session
    where project_id = ? and time_archived is null
    order by time_updated desc
    limit ?
    """,
        (project_id, limit),
    ).fetchall()
    return [dict(row) for row in fallback_rows], {
        "sampling_mode": "recent sessions (fallback)",
        "skipped_newest": False,
        "used_root_only": False,
    }


def collect_user_messages(
    cur: sqlite3.Cursor, session_ids: list[str]
) -> tuple[list[dict], list[dict]]:
    placeholders = ",".join("?" for _ in session_ids)
    rows = cur.execute(
        f"""
    select
      s.title as session_title,
      m.session_id,
      m.id as message_id,
      m.time_created as message_time,
      m.data as message_data,
      p.time_created as part_time,
      p.data as part_data
    from message m
    join session s on s.id = m.session_id
    join part p on p.message_id = m.id
    where m.session_id in ({placeholders})
    order by m.time_created asc, p.time_created asc
    """,
        session_ids,
    ).fetchall()

    grouped: dict[tuple[str, str], dict] = {}
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
        by_session[entry["session_id"]].append(entry)

    all_messages: list[dict] = []
    followups: list[dict] = []
    for session_id, messages in by_session.items():
        ordered = sorted(messages, key=lambda item: item["message_time"])
        for index, message in enumerate(ordered):
            all_messages.append(message)
            if index > 0:
                followups.append(message)

    return all_messages, followups


def category_counts(messages: list[dict]) -> Counter:
    counts: Counter[str] = Counter()
    for message in messages:
        lowered = message["text"].lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(keyword in lowered for keyword in keywords):
                counts[category] += 1
    return counts


def print_list(title: str, lines: list[str]) -> None:
    print(title)
    if not lines:
        print("- none")
        print()
        return
    for line in lines:
        print(f"- {line}")
    print()


def main() -> int:
    args = parse_args()

    if not os.path.exists(args.db_path):
        print("Recent local history evidence")
        print(f"- unavailable: OpenCode DB not found at {args.db_path}")
        return 0

    try:
        conn = sqlite3.connect(args.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        project = match_project(cur, args.worktree)
        if project is None:
            print("Recent local history evidence")
            print(
                f"- unavailable: no OpenCode project history matched {os.path.realpath(args.worktree)}"
            )
            print("- hint: run OpenCode in this project first, then retry /insights")
            return 0

        sessions, selection_meta = select_recent_sessions(
            cur, project["id"], args.session_limit
        )
        if not sessions:
            print("Recent local history evidence")
            print(f"- unavailable: no sessions found yet for {project['worktree']}")
            return 0

        session_ids = [session["id"] for session in sessions]
        agent_counts = assistant_agent_counts(cur, session_ids)
        all_user_messages, followups = collect_user_messages(cur, session_ids)

        evidence_messages = followups if len(followups) >= 2 else all_user_messages
        taxonomy = category_counts(evidence_messages)

        root_count = sum(1 for session in sessions if session["parent_id"] is None)
        child_count = len(sessions) - root_count

        print("Recent local history evidence")
        print(f"- worktree: {project['worktree']}")
        print(f"- sampling mode: {selection_meta['sampling_mode']}")
        print(
            f"- skipped newest eligible session: {'yes' if selection_meta['skipped_newest'] else 'no'}"
        )
        print(
            f"- sampled sessions: {len(sessions)} ({root_count} root, {child_count} child)"
        )
        print(f"- sampled user messages: {len(all_user_messages)}")
        print(f"- sampled follow-ups: {len(followups)}")
        print()

        recent_session_lines = [
            f"[{format_time(session['time_updated'])}] {'root' if session['parent_id'] is None else 'child'} `{shorten(session['title'], 90)}`"
            for session in sessions
        ]
        print_list("Recent sessions", recent_session_lines)

        agent_lines = [
            f"{agent}: {count}" for agent, count in agent_counts.most_common()
        ]
        print_list("Assistant agent counts", agent_lines)

        taxonomy_lines = [
            f"{category}: {count}" for category, count in taxonomy.most_common()
        ]
        print_list("Feedback category hints", taxonomy_lines)

        followup_examples = sorted(
            followups, key=lambda item: item["message_time"], reverse=True
        )
        followup_lines = [
            f"`{shorten(item['session_title'], 60)}`: {shorten(item['text'])}"
            for item in followup_examples[: args.followup_limit]
        ]
        print_list("Follow-up examples", followup_lines)

        caveats = []
        if not selection_meta["used_root_only"]:
            caveats.append(
                "fell back to non-root sessions because root history was unavailable"
            )
        if len(sessions) < 3:
            caveats.append("sample is thin; prefer conservative proposals")
        if len(followups) < 2:
            caveats.append(
                "follow-up evidence is limited; current-session context may dominate"
            )
        if not taxonomy:
            caveats.append(
                "no strong category signal detected in the sampled user messages"
            )
        print_list("Evidence caveats", caveats)
        return 0
    except Exception as exc:
        print("Recent local history evidence")
        print(f"- unavailable: failed to summarize OpenCode history ({exc})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
