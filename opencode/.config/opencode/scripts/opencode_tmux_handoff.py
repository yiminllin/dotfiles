#!/usr/bin/env python3
"""Dry-run-first path/link/S3 handoff packet helper with optional tmux copy."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote


S3_RE = re.compile(r"^s3://([^/\s]+)(?:/(.*))?$")
URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


@dataclass
class CommandResult:
    command: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": shlex.join(self.command),
            "exit_code": self.exit_code,
            "stdout": self.stdout.strip(),
            "stderr": self.stderr.strip(),
            "timed_out": self.timed_out,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a compact handoff packet for local paths, S3 URIs, URLs, and optional tmux buffer copy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              opencode_tmux_handoff.py packet --path /tmp --format markdown --dry-run
              opencode_tmux_handoff.py packet --s3 s3://bucket/prefix --copy-tmux --dry-run
              opencode_tmux_handoff.py packet --s3 s3://bucket/prefix --copy-tmux
              opencode_tmux_handoff.py packet --stdin --format json --dry-run

            Default behavior is no mutation because --copy-tmux is false. If
            --copy-tmux --dry-run is passed, the helper reports the planned tmux
            command without copying. Only --copy-tmux without --dry-run writes to
            the tmux buffer, and it never performs network/S3 calls.
            """
        ).strip(),
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    packet = subparsers.add_parser("packet", help="collect handoff context")
    packet.add_argument("--path", action="append", default=[], help="local path to include; may repeat")
    packet.add_argument("--s3", action="append", default=[], help="S3 URI to include; may repeat")
    packet.add_argument("--url", action="append", default=[], help="HTTP(S) URL to include; may repeat")
    packet.add_argument("--stdin", action="store_true", help="read newline-separated paths/URLs/S3 URIs from stdin")
    packet.add_argument("--copy-tmux", action="store_true", help="explicitly copy the primary item to the tmux buffer")
    packet.add_argument("--dry-run", action="store_true", help="with --copy-tmux, report the planned tmux command without copying")
    packet.add_argument("--format", choices=("json", "markdown"), default="json", help="output format")
    packet.add_argument("--timeout", type=int, default=5, help="tmux command timeout seconds")
    return parser.parse_args()


def run_command(command: list[str], timeout: int) -> CommandResult:
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return CommandResult(command, None, stdout, stderr or f"timed out after {timeout}s", True)
    return CommandResult(command, result.returncode, result.stdout, result.stderr)


def main() -> int:
    args = parse_args()
    items = collect_items(args)
    packet = build_packet(items, args.copy_tmux, args.dry_run, args.timeout)
    if args.format == "markdown":
        print(render_markdown(packet))
    else:
        print(json.dumps(packet, indent=2, sort_keys=True))
    return 0 if not packet.get("fatal") else 1


def collect_items(args: argparse.Namespace) -> list[dict[str, Any]]:
    raw: list[tuple[str, str]] = []
    raw.extend(("path", value) for value in args.path)
    raw.extend(("s3", value) for value in args.s3)
    raw.extend(("url", value) for value in args.url)
    if args.stdin:
        raw.extend(("auto", line.strip()) for line in sys.stdin if line.strip())
    return [classify_item(kind, value) for kind, value in raw]


def classify_item(kind: str, value: str) -> dict[str, Any]:
    if kind == "auto":
        if S3_RE.match(value):
            kind = "s3"
        elif URL_RE.match(value):
            kind = "url"
        else:
            kind = "path"
    if kind == "s3":
        return classify_s3(value)
    if kind == "url":
        return classify_url(value)
    return classify_path(value)


def classify_path(value: str) -> dict[str, Any]:
    expanded = Path(value).expanduser()
    exists = expanded.exists()
    info: dict[str, Any] = {
        "kind": "path",
        "input": value,
        "path": str(expanded),
        "exists": exists,
        "role": opencode_path_role(expanded),
    }
    if exists:
        try:
            stat = expanded.stat()
            info.update({"type": "dir" if expanded.is_dir() else "file", "size_bytes": None if expanded.is_dir() else stat.st_size})
        except OSError as exc:
            info.update({"type": "unknown", "error": str(exc)})
    return info


def classify_s3(value: str) -> dict[str, Any]:
    match = S3_RE.match(value)
    if not match:
        return {"kind": "s3", "input": value, "valid": False, "error": "expected s3://bucket[/prefix]"}
    bucket = match.group(1)
    prefix = match.group(2) or ""
    console = f"https://s3.console.aws.amazon.com/s3/buckets/{quote(bucket)}"
    if prefix:
        console += f"?prefix={quote(prefix)}"
    return {"kind": "s3", "input": value, "valid": True, "bucket": bucket, "prefix": prefix, "console_url": console}


def classify_url(value: str) -> dict[str, Any]:
    kind = "url"
    if "github.com" in value and "/actions/" in value:
        kind = "gha-url"
    elif "baraza" in value.lower() or "logplots" in value.lower():
        kind = "baraza-url"
    return {"kind": kind, "input": value, "valid": bool(URL_RE.match(value))}


def opencode_path_role(path: Path) -> str:
    text = str(path.resolve() if path.exists() else path)
    home = str(Path.home())
    if "/dotfiles/opencode/.config/opencode" in text:
        return "stowed source config"
    if text.startswith(f"{home}/.config/opencode"):
        return "runtime config"
    return "local path"


def build_packet(items: list[dict[str, Any]], copy_tmux: bool, dry_run: bool, timeout: int) -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    tmux = tmux_status(timeout)
    commands.extend(tmux.pop("commands"))
    primary = primary_value(items)
    planned_command = ["tmux", "set-buffer", "--", primary] if primary is not None else None
    copy_result: dict[str, Any] = {
        "requested": copy_tmux,
        "performed": False,
        "dry_run": dry_run,
        "mode": "copy-dry-run" if copy_tmux and dry_run else ("copy" if copy_tmux else "no-copy-requested"),
    }
    if copy_tmux:
        if primary is None:
            copy_result["blocker"] = "no path, URL, or S3 URI provided"
        elif dry_run:
            copy_result.update(
                {
                    "planned_command": shlex.join(planned_command or []),
                    "target": tmux.get("target"),
                    "tmux_available": tmux.get("available"),
                }
            )
        elif not tmux.get("available"):
            copy_result["blocker"] = tmux.get("reason", "tmux unavailable")
        else:
            result = run_command(planned_command or ["tmux", "set-buffer", "--", primary], timeout)
            commands.append(result.as_dict())
            copy_result.update({"performed": result.exit_code == 0, "target": tmux.get("target"), "copied_value": primary})
            if result.exit_code != 0:
                copy_result["blocker"] = result.stderr.strip() or result.stdout.strip() or "tmux set-buffer failed"

    return {
        "kind": "opencode_tmux_handoff_packet",
        "fatal": False,
        "items": items,
        "primary": primary,
        "tmux": tmux,
        "copy": copy_result,
        "commands": commands,
        "notes": ["no network, S3 listing, upload, download, or auth was attempted"],
    }


def tmux_status(timeout: int) -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    if shutil.which("tmux") is None:
        return {"available": False, "reason": "tmux executable not found", "commands": commands}
    if not os.environ.get("TMUX"):
        return {"available": False, "reason": "TMUX environment variable is not set", "commands": commands}
    result = run_command(["tmux", "display-message", "-p", "#S:#I.#P"], timeout)
    commands.append(result.as_dict())
    if result.exit_code != 0:
        return {"available": False, "reason": result.stderr.strip() or "tmux display-message failed", "commands": commands}
    return {"available": True, "target": result.stdout.strip(), "commands": commands}


def primary_value(items: list[dict[str, Any]]) -> str | None:
    for item in items:
        if item.get("kind") == "s3" and item.get("valid"):
            return str(item["input"])
        if item.get("kind") in {"url", "gha-url", "baraza-url"} and item.get("valid"):
            return str(item["input"])
        if item.get("kind") == "path":
            return str(item["path"])
    return None


def render_markdown(packet: dict[str, Any]) -> str:
    lines = ["# OpenCode Tmux Handoff Packet", "", f"- primary: `{packet.get('primary')}`", "- mutation: none unless `--copy-tmux` is used without `--dry-run`"]
    tmux = packet["tmux"]
    lines.append(f"- tmux: {'available ' + tmux.get('target', '') if tmux.get('available') else 'unavailable: ' + tmux.get('reason', 'unknown')}")
    lines.extend(["", "## Items"])
    for item in packet["items"]:
        if item["kind"] == "path":
            lines.append(f"- path `{item['path']}` exists={item['exists']} role={item['role']}")
        elif item["kind"] == "s3":
            lines.append(f"- s3 `{item['input']}` valid={item['valid']} console=`{item.get('console_url')}`")
        else:
            lines.append(f"- {item['kind']} `{item['input']}` valid={item.get('valid')}")
    copy = packet["copy"]
    lines.extend(["", "## Copy result", f"- mode: {copy['mode']}", f"- requested: {copy['requested']}", f"- dry-run: {copy['dry_run']}", f"- performed: {copy['performed']}"])
    if copy.get("planned_command"):
        lines.append(f"- planned: `{copy['planned_command']}`")
    if copy.get("target"):
        lines.append(f"- target: `{copy['target']}`")
    if copy.get("blocker"):
        lines.append(f"- blocker: {copy['blocker']}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
