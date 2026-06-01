#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import opencode_stale_tools
except ImportError:  # Phase 2 helper may be absent in partial installs.
    opencode_stale_tools = None


DEFAULT_STATE_DIR = Path("/tmp/opencode-progress")
DEFAULT_LONGRUN_DIR = Path("/tmp/opencode-longrun")
DEFAULT_DB_PATH = "~/.local/share/opencode/opencode.db"
DEFAULT_SNAPSHOT_LIMIT = 10
DEFAULT_LONGRUN_LIMIT = 5
DEFAULT_STALE_MINUTES = 10
DEFAULT_LOOKBACK_DAYS = 30
STATE_FILE_NAME = "progress-state.json"
MANUAL_DIR_NAME = "manual"
PLUGIN_DIR_NAME = "plugins"
PLUGIN_PROGRESS_DIR_NAME = "progress-state"
SCHEMA_VERSION = 1

ACTIVE_STATUSES = {"pending", "running", "starting", "stale", "timing_out"}
SECRET_KEY_PATTERN = (
    r"api[-_]?key|authorization|cookie|credential|password|private[-_]?key|"
    r"refresh[-_]?token|secret|session[-_]?token|token"
)
SECRET_KEY_RE = re.compile(SECRET_KEY_PATTERN, re.IGNORECASE)
SECRET_ASSIGNMENT_RE = re.compile(
    rf"(?i)\b({SECRET_KEY_PATTERN})\b\s*([=:])\s*(['\"]?)[^\s;&,'\"}}]+"
)
SECRET_JSON_RE = re.compile(
    rf"(?i)(['\"]?(?:{SECRET_KEY_PATTERN})['\"]?\s*:\s*['\"]?)[^\s,}}'\"]+"
)
SECRET_FLAG_RE = re.compile(rf"(?i)(--(?:{SECRET_KEY_PATTERN})(?:=|\s+))(['\"]?)[^\s;&,'\"]+")
BEARER_VALUE_RE = re.compile(r"(?i)\bBearer\s+[^\s;&,'\"]+")
URL_USERINFO_RE = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)


def default_state_dir() -> str:
    return os.environ.get("OPENCODE_PROGRESS_STATE_DIR") or os.environ.get("OPENCODE_PROGRESS_DIR") or str(DEFAULT_STATE_DIR)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Maintain local OpenCode progress state for renderers and manual checkpoints."
    )
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--state-dir",
        default=default_state_dir(),
        help=(
            "Progress state directory; defaults to /tmp/opencode-progress or "
            "OPENCODE_PROGRESS_STATE_DIR/OPENCODE_PROGRESS_DIR"
        ),
    )

    snapshot_parser = subparsers.add_parser(
        "snapshot",
        parents=[common],
        help="Snapshot stale/running tools, long-run statuses, and manual notes into state JSON",
    )
    snapshot_parser.add_argument("--out", help=f"Output JSON path; defaults to state-dir/{STATE_FILE_NAME}")
    snapshot_parser.add_argument(
        "--db-path",
        default=os.environ.get("OPENCODE_DB_PATH", DEFAULT_DB_PATH),
        help="OpenCode sqlite DB path for stale tool records; defaults to ~/.local/share/opencode/opencode.db",
    )
    snapshot_parser.add_argument(
        "--lookback-days",
        type=positive_int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"Days of tool history to scan; defaults to {DEFAULT_LOOKBACK_DAYS}",
    )
    snapshot_parser.add_argument(
        "--stale-minutes",
        type=non_negative_int,
        default=DEFAULT_STALE_MINUTES,
        help=f"Active tool records older than this are marked stale; defaults to {DEFAULT_STALE_MINUTES}",
    )
    snapshot_parser.add_argument(
        "--limit",
        type=non_negative_int,
        default=DEFAULT_SNAPSHOT_LIMIT,
        help=f"Maximum stale/running tool records to include; defaults to {DEFAULT_SNAPSHOT_LIMIT}",
    )
    snapshot_parser.add_argument(
        "--include-recent-errors",
        action="store_true",
        help="Include recent tool error records from the stale-tools helper",
    )
    snapshot_parser.add_argument(
        "--longrun-dir",
        default=os.environ.get("OPENCODE_LONGRUN_DIR", str(DEFAULT_LONGRUN_DIR)),
        help="Long-run status directory; defaults to /tmp/opencode-longrun or OPENCODE_LONGRUN_DIR",
    )
    snapshot_parser.add_argument(
        "--longrun-limit",
        type=non_negative_int,
        default=DEFAULT_LONGRUN_LIMIT,
        help=f"Maximum long-run status files to include; defaults to {DEFAULT_LONGRUN_LIMIT}; 0 disables",
    )
    snapshot_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format for the command result; defaults to text",
    )

    status_parser = subparsers.add_parser(
        "status",
        parents=[common],
        help="Render concise progress text from a state file or state directory",
    )
    status_parser.add_argument(
        "target",
        nargs="?",
        help="State JSON file or directory; defaults to --state-dir",
    )
    status_parser.add_argument(
        "--limit",
        type=positive_int,
        default=10,
        help="Maximum entries to render; defaults to 10",
    )
    status_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format; defaults to text",
    )

    write_parser = subparsers.add_parser(
        "write",
        parents=[common],
        help="Write or update a manual current progress entry",
    )
    write_parser.add_argument("--id", required=True, help="Stable manual entry id")
    write_parser.add_argument("--goal", help="Task goal or objective")
    write_parser.add_argument("--phase", help="Current phase, step, or percent label")
    write_parser.add_argument("--current", help="Current action or latest checkpoint")
    write_parser.add_argument(
        "--status",
        default="running",
        choices=("pending", "running", "blocked", "succeeded", "failed", "done"),
        help="Manual entry status; defaults to running",
    )
    write_parser.add_argument("--label", help="Short display label; defaults to --id")
    write_parser.add_argument("--mode", choices=("determinate", "indeterminate"), help="Progress mode")
    write_parser.add_argument("--session-id", help="OpenCode session id, if known")
    write_parser.add_argument("--task-id", help="Subagent or task id, if known")
    write_parser.add_argument("--agent", help="Agent/subagent label, if known")
    write_parser.add_argument("--log", dest="log_path", help="Related log path")
    write_parser.add_argument("--last-output", help="Latest output line or short excerpt")
    write_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format for the command result; defaults to text",
    )

    clear_parser = subparsers.add_parser(
        "clear",
        parents=[common],
        help="Clear one helper-owned manual progress entry by id",
    )
    clear_parser.add_argument("--id", required=True, help="Manual entry id to clear")
    clear_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format for the command result; defaults to text",
    )

    return parser.parse_args()


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


def expand_path(raw: str | None) -> Path | None:
    if raw is None:
        return None
    return Path(os.path.expanduser(raw)).resolve()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iso_from_ms(timestamp_ms: int | None) -> str | None:
    if not timestamp_ms:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat(timespec="seconds")


def duration_label(seconds: float | int | None) -> str:
    if seconds is None:
        return "unknown"
    total = max(0, int(seconds))
    days, total = divmod(total, 24 * 60 * 60)
    hours, total = divmod(total, 60 * 60)
    minutes, seconds = divmod(total, 60)
    if days:
        return f"{days}d{hours:02d}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def shorten(value: object, width: int = 120) -> str:
    if value is None:
        return ""
    collapsed = " ".join(str(value).split())
    return textwrap.shorten(collapsed, width=width, placeholder="...")


def scrub_text(value: object, width: int = 160) -> str | None:
    if value is None:
        return None
    scrubbed = str(value)
    scrubbed = URL_USERINFO_RE.sub(r"\1<redacted>@", scrubbed)
    scrubbed = BEARER_VALUE_RE.sub("Bearer <redacted>", scrubbed)
    scrubbed = SECRET_JSON_RE.sub(r"\1<redacted>", scrubbed)
    scrubbed = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", scrubbed)
    scrubbed = SECRET_FLAG_RE.sub(lambda match: f"{match.group(1)}<redacted>", scrubbed)
    return shorten(scrubbed, width)


def scrub_path(value: object, width: int = 240) -> str | None:
    return scrub_text(value, width)


def scrub_command(command: object) -> object:
    if command is None:
        return None
    if not isinstance(command, list):
        return scrub_text(command, 400)

    scrubbed = []
    redact_next = False
    for part in command[:80]:
        text = str(part)
        if redact_next:
            scrubbed.append("<redacted>")
            redact_next = False
            continue
        scrubbed.append(scrub_text(text, 160) or "")
        flag_name = text.lstrip("-").split("=", 1)[0]
        redact_next = text.startswith("--") and "=" not in text and SECRET_KEY_RE.search(flag_name) is not None
    if len(command) > 80:
        scrubbed.append(f"... {len(command) - 80} more args")
    return scrubbed


def scrub_entry(entry: dict[str, Any]) -> dict[str, Any]:
    clean = dict(entry)
    for key in ("label", "goal", "phase", "current", "last_output"):
        if key in clean:
            clean[key] = scrub_text(clean[key], 240 if key == "last_output" else 160)
    for key in ("log_path", "status_path", "cwd"):
        if key in clean:
            clean[key] = scrub_path(clean[key])
    if "command" in clean:
        clean["command"] = scrub_command(clean["command"])

    session = clean.get("session")
    if isinstance(session, dict):
        clean["session"] = {
            key: scrub_text(value) if key in {"title", "agent"} else scrub_path(value) if key == "location" else value
            for key, value in session.items()
        }
    subagent = clean.get("subagent")
    if isinstance(subagent, dict):
        clean["subagent"] = {
            key: scrub_text(value) if key in {"type", "session_title"} else value for key, value in subagent.items()
        }
    tool = clean.get("tool")
    if isinstance(tool, dict):
        clean["tool"] = {key: scrub_text(value) if key == "name" else value for key, value in tool.items()}
    return clean


def safe_file_id(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw.strip()).strip("-._")
    if not cleaned:
        raise SystemExit("manual entry id must contain at least one filename-safe character")
    return cleaned


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def read_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file is not an object: {path}")
    return payload


def manual_dir(state_dir: Path) -> Path:
    return state_dir / MANUAL_DIR_NAME


def manual_path(state_dir: Path, manual_id: str) -> Path:
    return manual_dir(state_dir) / f"{safe_file_id(manual_id)}.json"


def plugin_progress_dir(state_dir: Path) -> Path:
    return state_dir / PLUGIN_DIR_NAME / PLUGIN_PROGRESS_DIR_NAME


def collect_stale_tool_entries(args: argparse.Namespace, generated_at: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    db_path = os.path.expanduser(args.db_path)
    source = {
        "name": "opencode_stale_tools",
        "db_path": db_path,
        "lookback_days": args.lookback_days,
        "stale_minutes": args.stale_minutes,
        "limit": args.limit,
        "available": False,
    }
    if opencode_stale_tools is None:
        source["error"] = "opencode_stale_tools.py is not importable"
        return [], source
    if not os.path.exists(db_path):
        source["error"] = f"OpenCode DB not found at {db_path}"
        return [], source
    if not os.access(db_path, os.R_OK):
        source["error"] = f"OpenCode DB is not readable at {db_path}"
        return [], source

    now = datetime.now()
    since_ms = int((now - timedelta(days=args.lookback_days)).timestamp() * 1000)
    until_ms = int(now.timestamp() * 1000)
    stale_ms = args.stale_minutes * 60 * 1000
    try:
        conn = opencode_stale_tools.readonly_sqlite_connection(args.db_path)
        conn.row_factory = sqlite3.Row
        try:
            candidates = opencode_stale_tools.collect_candidates(conn.cursor(), args, since_ms, until_ms, until_ms)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        source["error"] = f"failed to read OpenCode DB ({exc})"
        return [], source

    records = opencode_stale_tools.ranked_records(candidates, stale_ms, args.limit)
    source.update(
        {
            "available": True,
            "summary": opencode_stale_tools.summary(candidates, stale_ms, args, since_ms, until_ms),
        }
    )
    return [stale_tool_entry(record, stale_ms, generated_at) for record in records], source


def stale_tool_entry(record: dict[str, Any], stale_ms: int, generated_at: str) -> dict[str, Any]:
    is_stale = record.get("status") in opencode_stale_tools.ACTIVE_STATUSES and record.get("age_ms", 0) >= stale_ms
    tool = record.get("tool") or "unknown-tool"
    status = "stale" if is_stale else str(record.get("status") or "unknown")
    session_title = scrub_text(record.get("session_title"), 80) or "untitled session"
    current = scrub_text(record.get("payload_summary"), 160) or "tool input unavailable"
    return {
        "id": f"tool:{record.get('part_id') or record.get('call_id') or tool}",
        "source": "stale_tools",
        "label": f"{tool} in {session_title}",
        "goal": f"{tool} tool call",
        "phase": "runtime tool",
        "current": current,
        "status": status,
        "mode": "indeterminate",
        "updated_at": iso_from_ms(record.get("time_updated")) or generated_at,
        "started_at": iso_from_ms(record.get("time_created")),
        "age": opencode_stale_tools.duration_label(record.get("age_ms")),
        "elapsed": opencode_stale_tools.duration_label(record.get("duration_ms")),
        "last_output": scrub_text(record.get("error_summary"), 240),
        "stale": is_stale,
        "tool": {
            "name": tool,
            "status": record.get("status"),
            "part_id": record.get("part_id"),
            "call_id": record.get("call_id"),
            "interrupted": record.get("interrupted"),
        },
        "session": {
            "id": record.get("session_id"),
            "title": scrub_text(record.get("session_title")),
            "kind": record.get("session_kind"),
            "agent": scrub_text(record.get("session_agent")),
            "location": scrub_path(opencode_stale_tools.format_session_location(record)),
        },
        "subagent": {
            "type": record.get("subagent_type"),
            "task_id": record.get("subagent_task_id"),
            "session_id": record.get("subagent_session_id"),
            "session_title": scrub_text(record.get("subagent_session_title")),
        }
        if tool == "task"
        else None,
    }


def collect_longrun_entries(longrun_dir: Path, limit: int, generated_at: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = {
        "name": "opencode_longrun",
        "directory": str(longrun_dir),
        "limit": limit,
        "available": longrun_dir.exists(),
    }
    if limit == 0:
        source["disabled"] = True
        return [], source
    if not longrun_dir.exists():
        source["error"] = f"long-run directory not found at {longrun_dir}"
        return [], source
    if not longrun_dir.is_dir():
        source["error"] = f"long-run path is not a directory: {longrun_dir}"
        return [], source

    entries = []
    paths = sorted(longrun_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths[:limit]:
        try:
            status = read_json_object(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            entries.append(unavailable_entry("longrun", path, str(exc), generated_at))
            continue
        entries.append(longrun_entry(path, status, generated_at))
    source["records_found"] = len(paths)
    source["records_included"] = len(entries)
    return entries, source


def longrun_entry(path: Path, status: dict[str, Any], generated_at: str) -> dict[str, Any]:
    state = str(status.get("state") or status.get("status") or "unknown")
    name = scrub_text(status.get("name") or path.stem, 120) or path.stem
    last_output = scrub_text(status.get("last_log_line") or status.get("last_output_sample"), 240)
    return {
        "id": f"longrun:{path.name}",
        "source": "longrun",
        "label": name,
        "goal": name,
        "phase": "long-run command",
        "current": scrub_text(last_output, 160) or state,
        "status": state,
        "mode": "indeterminate",
        "updated_at": status.get("updated_at") or generated_at,
        "started_at": status.get("started_at"),
        "elapsed": duration_label(status.get("elapsed_seconds")),
        "log_path": scrub_path(status.get("log_path")),
        "status_path": scrub_path(path),
        "last_output": last_output,
        "command": scrub_command(status.get("command")),
        "cwd": scrub_path(status.get("cwd")),
        "pid": status.get("pid"),
        "returncode": status.get("returncode"),
        "timed_out": status.get("timed_out"),
    }


def unavailable_entry(source: str, path: Path, error: str, generated_at: str) -> dict[str, Any]:
    return {
        "id": f"{source}:unavailable:{path.name}",
        "source": source,
        "label": scrub_text(f"unreadable {path.name}"),
        "goal": "read progress source",
        "phase": "source read",
        "current": scrub_text(error, 240),
        "status": "blocked",
        "mode": "indeterminate",
        "updated_at": generated_at,
    }


def load_manual_entries(state_dir: Path) -> list[dict[str, Any]]:
    directory = manual_dir(state_dir)
    if not directory.exists():
        return []
    entries = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = read_json_object(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        entry = payload.get("entry", payload)
        if isinstance(entry, dict):
            entries.append(scrub_entry(entry))
    return entries


def load_plugin_entries(state_dir: Path) -> list[dict[str, Any]]:
    directory = plugin_progress_dir(state_dir)
    if not directory.exists():
        return []
    entries = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = read_json_object(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if payload.get("kind") != "opencode_plugin_progress_entry":
            continue
        entry = payload.get("entry")
        if isinstance(entry, dict):
            entries.append(scrub_entry(entry))
    return entries


def build_state(
    entries: list[dict[str, Any]],
    sources: dict[str, Any],
    generated_at: str,
    state_dir: Path,
) -> dict[str, Any]:
    ordered_entries = sorted((scrub_entry(entry) for entry in entries), key=entry_sort_key, reverse=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "opencode_progress_state",
        "generated_at": generated_at,
        "state_dir": str(state_dir),
        "summary": summarize_entries(ordered_entries),
        "sources": sources,
        "entries": ordered_entries,
    }


def summarize_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for entry in entries:
        status = str(entry.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "total": len(entries),
        "active": sum(1 for entry in entries if entry.get("status") in ACTIVE_STATUSES),
        "stale": sum(1 for entry in entries if entry.get("stale") or entry.get("status") == "stale"),
        "manual": sum(1 for entry in entries if entry.get("source") == "manual"),
        "plugin": sum(1 for entry in entries if entry.get("source") == "plugin"),
        "longrun": sum(1 for entry in entries if entry.get("source") == "longrun"),
        "stale_tools": sum(1 for entry in entries if entry.get("source") == "stale_tools"),
        "by_status": by_status,
    }


def entry_sort_key(entry: dict[str, Any]) -> tuple[str, str]:
    return (str(entry.get("updated_at") or ""), str(entry.get("id") or ""))


def merge_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for entry in entries:
        entry_id = str(entry.get("id") or "")
        if not entry_id:
            continue
        merged[entry_id] = entry
    return sorted(merged.values(), key=entry_sort_key, reverse=True)


def snapshot(args: argparse.Namespace) -> int:
    state_dir = expand_path(args.state_dir) or DEFAULT_STATE_DIR
    out_path = expand_path(args.out) or state_dir / STATE_FILE_NAME
    longrun_dir = expand_path(args.longrun_dir) or DEFAULT_LONGRUN_DIR
    generated_at = utc_now()

    stale_entries, stale_source = collect_stale_tool_entries(args, generated_at)
    longrun_entries, longrun_source = collect_longrun_entries(longrun_dir, args.longrun_limit, generated_at)
    manual_entries = load_manual_entries(state_dir)
    plugin_entries = load_plugin_entries(state_dir)
    state = build_state(
        stale_entries + longrun_entries + manual_entries + plugin_entries,
        {
            "stale_tools": stale_source,
            "longrun": longrun_source,
            "manual": {"directory": str(manual_dir(state_dir)), "records_found": len(manual_entries)},
            "plugin": {"directory": str(plugin_progress_dir(state_dir)), "records_found": len(plugin_entries)},
        },
        generated_at,
        state_dir,
    )
    atomic_write_json(out_path, state)

    if args.format == "json":
        print(json.dumps({"path": str(out_path), "summary": state["summary"]}, indent=2, sort_keys=True))
    else:
        summary = state["summary"]
        print(
            f"wrote {out_path} | entries={summary['total']} active={summary['active']} "
            f"stale={summary['stale']} manual={summary['manual']} plugin={summary['plugin']} "
            f"longrun={summary['longrun']}"
        )
        for name, source in state["sources"].items():
            if source.get("error"):
                print(f"- {name}: {source['error']}")
    return 0


def latest_state_file(state_dir: Path) -> Path | None:
    if not state_dir.exists():
        return None
    candidates = [path for path in state_dir.glob("*.json") if path.is_file() and not path.name.startswith(".")]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: (path.stat().st_mtime, path.name), reverse=True)[0]


def load_status_state(target: Path, state_dir: Path) -> dict[str, Any]:
    if target.is_file():
        payload = read_json_object(target)
        return build_state(
            list(payload.get("entries") or []),
            dict(payload.get("sources") or {}),
            str(payload.get("generated_at") or utc_now()),
            state_dir,
        )
    if target.exists() and not target.is_dir():
        raise ValueError(f"status target is not a JSON file or directory: {target}")

    latest = latest_state_file(target)
    base_state = read_json_object(latest) if latest else None
    entries = [] if base_state is None else list(base_state.get("entries") or [])
    if target == state_dir:
        manual_entries = load_manual_entries(state_dir)
        plugin_entries = load_plugin_entries(state_dir)
        entries.extend(manual_entries)
        entries.extend(plugin_entries)
    generated_at = str(base_state.get("generated_at")) if base_state else utc_now()
    sources = dict(base_state.get("sources") or {}) if base_state else {}
    if target == state_dir:
        sources["manual"] = {"directory": str(manual_dir(state_dir)), "records_found": len(manual_entries)}
        sources["plugin"] = {"directory": str(plugin_progress_dir(state_dir)), "records_found": len(plugin_entries)}
    return build_state(merge_entries(entries), sources, generated_at, state_dir)


def render_status(state: dict[str, Any], limit: int) -> str:
    entries = merge_entries(list(state.get("entries") or []))
    summary = summarize_entries(entries)
    header = (
        f"OpenCode progress: {summary['total']} entries; active={summary['active']}; "
        f"stale={summary['stale']}; manual={summary['manual']}; plugin={summary['plugin']}; "
        f"updated={state.get('generated_at', 'unknown')}"
    )
    if not entries:
        return f"{header}\n- none"

    lines = [header]
    for entry in entries[:limit]:
        lines.extend(render_entry(entry))
    hidden = len(entries) - limit
    if hidden > 0:
        lines.append(f"- ... {hidden} more")
    return "\n".join(lines)


def render_entry(entry: dict[str, Any]) -> list[str]:
    entry = scrub_entry(entry)
    status = entry.get("status") or "unknown"
    label = shorten(entry.get("label") or entry.get("goal") or entry.get("id"), 90)
    pieces = [f"- [{status}] {label}"]
    if entry.get("phase"):
        pieces.append(f"phase={shorten(entry['phase'], 40)}")
    if entry.get("current"):
        pieces.append(f"current={shorten(entry['current'], 120)}")
    if entry.get("elapsed"):
        pieces.append(f"elapsed={entry['elapsed']}")
    if entry.get("age"):
        pieces.append(f"age={entry['age']}")
    if entry.get("updated_at"):
        pieces.append(f"updated={entry['updated_at']}")

    lines = [" | ".join(pieces)]
    detail_pieces = []
    for key, label_name in (("log_path", "log"), ("status_path", "status"), ("last_output", "last")):
        value = entry.get(key)
        if value:
            detail_pieces.append(f"{label_name}={shorten(value, 140)}")
    if detail_pieces:
        lines.append(f"  {' | '.join(detail_pieces)}")
    return lines


def show_status(args: argparse.Namespace) -> int:
    state_dir = expand_path(args.state_dir) or DEFAULT_STATE_DIR
    target = expand_path(args.target) if args.target else state_dir
    if target is None:
        target = state_dir
    try:
        state = load_status_state(target, state_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"OpenCode progress unavailable: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print(render_status(state, args.limit))
    return 0


def write_manual(args: argparse.Namespace) -> int:
    state_dir = expand_path(args.state_dir) or DEFAULT_STATE_DIR
    manual_id = safe_file_id(args.id)
    path = manual_path(state_dir, manual_id)
    now = utc_now()
    entry = {
        "id": f"manual:{manual_id}",
        "manual_id": manual_id,
        "source": "manual",
        "label": scrub_text(args.label or args.id),
        "goal": scrub_text(args.goal),
        "phase": scrub_text(args.phase),
        "current": scrub_text(args.current),
        "status": args.status,
        "mode": args.mode or "indeterminate",
        "updated_at": now,
        "log_path": scrub_path(args.log_path),
        "last_output": scrub_text(args.last_output, 240),
        "session": {"id": args.session_id, "agent": scrub_text(args.agent)} if args.session_id or args.agent else None,
        "task": {"id": args.task_id} if args.task_id else None,
    }
    entry = scrub_entry({key: value for key, value in entry.items() if value is not None})
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "opencode_manual_progress_entry",
        "updated_at": now,
        "entry": entry,
    }
    atomic_write_json(path, payload)

    if args.format == "json":
        print(json.dumps({"path": str(path), "entry": entry}, indent=2, sort_keys=True))
    else:
        print(f"wrote manual progress entry {args.id} at {path}")
    return 0


def clear_manual(args: argparse.Namespace) -> int:
    state_dir = expand_path(args.state_dir) or DEFAULT_STATE_DIR
    path = manual_path(state_dir, args.id)
    removed = False
    if path.exists():
        path.unlink()
        removed = True

    if args.format == "json":
        print(json.dumps({"path": str(path), "removed": removed}, indent=2, sort_keys=True))
    else:
        action = "removed" if removed else "not found"
        print(f"manual progress entry {args.id}: {action} ({path})")
    return 0


def main() -> int:
    args = parse_args()
    if args.command_name == "snapshot":
        return snapshot(args)
    if args.command_name == "status":
        return show_status(args)
    if args.command_name == "write":
        return write_manual(args)
    if args.command_name == "clear":
        return clear_manual(args)
    raise SystemExit(f"unknown command: {args.command_name}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
