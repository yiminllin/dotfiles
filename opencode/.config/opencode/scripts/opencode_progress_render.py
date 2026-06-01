#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opencode_progress_state import (
    ACTIVE_STATUSES,
    default_state_dir,
    duration_label,
    expand_path,
    load_status_state,
    merge_entries,
    scrub_entry,
    shorten,
    summarize_entries,
)


DEFAULT_WIDTH = 80
DEFAULT_LIMIT = 5
DEFAULT_REFRESH_SECONDS = 30
DEFAULT_SNAPSHOT_LIMIT = 10
DEFAULT_SNAPSHOT_FILE_NAME = "agent-board-snapshot.json"
DEFAULT_REFRESH_STAMP_FILE_NAME = ".agent-board-snapshot-refresh.stamp"
MIN_WIDTH = 20


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render compact OpenCode progress state for tmux status lines and boards."
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="State JSON file or directory; defaults to --state-dir",
    )
    parser.add_argument(
        "--mode",
        choices=("statusline", "board"),
        default="statusline",
        help="Render one-line statusline text or compact multi-line board text; defaults to statusline",
    )
    parser.add_argument(
        "--state-dir",
        default=default_state_dir(),
        help="Progress state directory; defaults to the Phase 4 progress-state helper default",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=DEFAULT_LIMIT,
        help=f"Maximum entries to render in board mode; defaults to {DEFAULT_LIMIT}",
    )
    parser.add_argument(
        "--width",
        type=positive_int,
        default=DEFAULT_WIDTH,
        help=f"Maximum output width per line; defaults to {DEFAULT_WIDTH}",
    )
    parser.add_argument(
        "--show-empty",
        action="store_true",
        help="Render counts even when there is no state or no entries",
    )
    parser.add_argument(
        "--show-stale",
        action="store_true",
        help="Include stale historical tool diagnostics in rendered progress",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Best-effort snapshot refresh before rendering when the progress cache is stale or missing",
    )
    parser.add_argument(
        "--refresh-seconds",
        type=non_negative_int,
        default=DEFAULT_REFRESH_SECONDS,
        help=f"Minimum seconds between refresh snapshots; 0 always refreshes; defaults to {DEFAULT_REFRESH_SECONDS}",
    )
    parser.add_argument(
        "--snapshot-limit",
        type=non_negative_int,
        default=DEFAULT_SNAPSHOT_LIMIT,
        help=f"Maximum stale/running tool records to include in refresh snapshots; defaults to {DEFAULT_SNAPSHOT_LIMIT}",
    )
    parser.add_argument(
        "--ascii",
        action="store_true",
        help="Use ASCII separators and warning markers",
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


def load_state(target: str | None, state_dir: str) -> dict[str, Any]:
    state_dir_path = expand_path(state_dir) or Path(default_state_dir())
    target_path = expand_path(target) if target else state_dir_path
    if target_path is None:
        target_path = state_dir_path
    return load_status_state(target_path, state_dir_path)


def refresh_snapshot_if_needed(args: argparse.Namespace, state_dir: Path) -> None:
    if not args.refresh:
        return

    snapshot_path = state_dir / DEFAULT_SNAPSHOT_FILE_NAME
    stamp_path = state_dir / DEFAULT_REFRESH_STAMP_FILE_NAME
    if not snapshot_is_stale(snapshot_path, stamp_path, args.refresh_seconds):
        return

    mark_refresh_attempt(stamp_path)
    helper = Path(__file__).with_name("opencode_progress_state.py")
    command = [
        sys.executable,
        str(helper),
        "snapshot",
        "--state-dir",
        str(state_dir),
        "--out",
        str(snapshot_path),
        "--limit",
        str(args.snapshot_limit),
        "--format",
        "json",
    ]
    try:
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return


def snapshot_is_stale(snapshot_path: Path, stamp_path: Path, refresh_seconds: int) -> bool:
    if refresh_seconds == 0:
        return True
    latest_mtime = latest_refresh_mtime(snapshot_path, stamp_path)
    if latest_mtime is None:
        return True
    return time.time() - latest_mtime >= refresh_seconds


def latest_refresh_mtime(snapshot_path: Path, stamp_path: Path) -> float | None:
    mtimes = []
    for path in (snapshot_path, stamp_path):
        try:
            mtimes.append(path.stat().st_mtime)
        except OSError:
            continue
    return max(mtimes) if mtimes else None


def mark_refresh_attempt(stamp_path: Path) -> None:
    try:
        stamp_path.parent.mkdir(parents=True, exist_ok=True)
        stamp_path.touch()
    except OSError:
        return


def render(state: dict[str, Any], args: argparse.Namespace) -> str:
    entries = [scrub_entry(entry) for entry in merge_entries(list(state.get("entries") or []))]
    if not args.show_stale:
        entries = [entry for entry in entries if not is_stale_tool_diagnostic(entry)]
    width = max(MIN_WIDTH, args.width)

    if args.mode == "board":
        summary = summarize_entries(entries)
        return render_board(entries, summary, state, args.limit, width, args.ascii)

    entries = [entry for entry in entries if is_current(entry)]
    if not entries and not args.show_empty:
        return ""
    summary = summarize_entries(entries)
    return render_statusline(entries, summary, width, args.ascii)


def is_stale_tool_diagnostic(entry: dict[str, Any]) -> bool:
    return bool(
        entry.get("source") == "stale_tools" and (entry.get("stale") or entry.get("status") == "stale")
    )


def render_statusline(
    entries: list[dict[str, Any]],
    summary: dict[str, Any],
    width: int,
    ascii_only: bool,
) -> str:
    if not entries and not summary["active"] and not summary["stale"]:
        return "OC idle"

    separator = " | " if ascii_only else " · "
    warning = "!" if ascii_only else "⚠"
    pieces = [f"OC active={summary['active']} stale={summary['stale']}"]
    if summary["stale"]:
        pieces[0] = f"{pieces[0]} {warning}"

    entry = top_entry(entries)
    if entry:
        pieces.extend(statusline_entry_pieces(entry, width, len(separator.join(pieces)), ascii_only))
    return fit(separator.join(piece for piece in pieces if piece), width)


def render_board(
    entries: list[dict[str, Any]],
    summary: dict[str, Any],
    state: dict[str, Any],
    limit: int,
    width: int,
    ascii_only: bool,
) -> str:
    separator = " | " if ascii_only else " · "
    warning = "!" if ascii_only else "⚠"
    updated = update_age(state.get("generated_at"))
    header_pieces = [
        f"OpenCode progress: active={summary['active']}",
        f"stale={summary['stale']}",
        f"total={summary['total']}",
    ]
    if summary["stale"]:
        header_pieces.append(f"{warning} stale progress")
    if updated:
        header_pieces.append(f"updated {updated} ago")
    lines = [fit(separator.join(header_pieces), width)]

    if not entries:
        lines.append("- none")
        return "\n".join(lines)

    for index, entry in enumerate(entries[:limit], start=1):
        line = f"{index}. " + separator.join(entry_pieces(entry, ascii_only))
        lines.append(fit(line, width))
        for path_detail in path_pieces(entry, width=max(20, width - 12)):
            lines.append(f"   {fit(path_detail, width - 3)}")
    hidden = len(entries) - limit
    if hidden > 0:
        lines.append(f"- ... {hidden} more")
    return "\n".join(lines)


def top_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in entries:
        if is_current(entry):
            return entry
    return entries[0] if entries else None


def is_current(entry: dict[str, Any]) -> bool:
    return bool(entry.get("stale") or entry.get("status") in ACTIVE_STATUSES)


def statusline_entry_pieces(
    entry: dict[str, Any],
    width: int,
    used_width: int,
    ascii_only: bool,
) -> list[str]:
    separator_width = 3
    time_piece = elapsed_piece(entry)
    path_piece = first_path_piece(entry, width=14)
    tail_pieces = [piece for piece in (time_piece, path_piece) if piece]
    tail_width = sum(len(piece) for piece in tail_pieces) + separator_width * len(tail_pieces)
    headline_width = max(18, width - used_width - tail_width - separator_width)
    return [entry_headline(entry, ascii_only, headline_width), *tail_pieces]


def entry_pieces(entry: dict[str, Any], ascii_only: bool) -> list[str]:
    pieces = [entry_headline(entry, ascii_only, width=90)]
    time_piece = elapsed_piece(entry)
    if time_piece:
        pieces.append(time_piece)
    return pieces


def entry_headline(entry: dict[str, Any], ascii_only: bool, width: int) -> str:
    separator = " - " if ascii_only else " — "
    status = str(entry.get("status") or "unknown")
    goal = shorten(entry.get("goal") or entry.get("label") or entry.get("id") or "progress", 44)
    current = shorten(entry.get("current") or entry.get("phase") or "", 46)
    headline = f"[{status}] {goal}"
    if current and current != goal:
        headline = f"{headline}{separator}{current}"
    return fit(headline, width)


def elapsed_piece(entry: dict[str, Any]) -> str | None:
    if entry.get("elapsed"):
        return f"elapsed={entry['elapsed']}"
    if entry.get("age"):
        return f"age={entry['age']}"
    updated = update_age(entry.get("updated_at"))
    if updated:
        return f"updated={updated} ago"
    return None


def first_path_piece(entry: dict[str, Any], width: int) -> str | None:
    pieces = path_pieces(entry, width=width)
    return pieces[0] if pieces else None


def path_pieces(entry: dict[str, Any], width: int = 48) -> list[str]:
    pieces = []
    if entry.get("log_path"):
        pieces.append(f"log={shorten(entry['log_path'], width)}")
    if entry.get("status_path"):
        pieces.append(f"status={shorten(entry['status_path'], width)}")
    return pieces


def update_age(raw_timestamp: object) -> str | None:
    if not raw_timestamp:
        return None
    try:
        updated_at = parse_datetime(str(raw_timestamp))
    except ValueError:
        return None
    return duration_label((datetime.now(timezone.utc) - updated_at).total_seconds())


def parse_datetime(raw_timestamp: str) -> datetime:
    normalized = raw_timestamp.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fit(value: str, width: int) -> str:
    return shorten(value, max(MIN_WIDTH, width))


def main() -> int:
    args = parse_args()
    state_dir = expand_path(args.state_dir) or Path(default_state_dir())
    refresh_snapshot_if_needed(args, state_dir)
    try:
        state = load_state(args.target, str(state_dir))
        output = render(state, args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"OpenCode progress unavailable: {exc}", file=sys.stderr)
        return 2

    if output:
        print(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
