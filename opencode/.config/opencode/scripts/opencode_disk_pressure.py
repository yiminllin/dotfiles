#!/usr/bin/env python3
"""Read-only disk/cache/log pressure report for OpenCode workflows."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BYTES_PER_MIB = 1024 * 1024
BYTES_PER_GIB = 1024 * 1024 * 1024


@dataclass
class WalkLimits:
    max_depth: int
    max_entries: int
    max_candidates: int
    large_file_bytes: int
    stale_days: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report disk, cache, and log pressure without deleting anything.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              opencode_disk_pressure.py report --format markdown
              opencode_disk_pressure.py report --format json
              opencode_disk_pressure.py report --path /tmp/opencode --print-cleanup-plan

            Default behavior is read-only. This helper never deletes, prunes, clears
            caches, starts daemons, authenticates, or uses the network.
            """
        ).strip(),
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    report = subparsers.add_parser("report", help="collect a read-only pressure report")
    report.add_argument("--repo", default=".", help="repo/current path to include, default: .")
    report.add_argument("--path", action="append", default=[], help="extra explicit path to inspect; may be repeated")
    report.add_argument("--format", choices=("markdown", "text", "json"), default="markdown", help="output format")
    report.add_argument("--json", action="store_true", help="alias for --format json")
    report.add_argument("--warn-percent", type=float, default=80.0, help="filesystem use percent that marks warning")
    report.add_argument("--critical-percent", type=float, default=90.0, help="filesystem use percent that marks critical")
    report.add_argument("--large-file-mib", type=int, default=256, help="candidate file size threshold in MiB")
    report.add_argument("--stale-days", type=int, default=14, help="candidate age threshold in days")
    report.add_argument("--max-depth", type=int, default=2, help="maximum directory depth per bounded root")
    report.add_argument("--max-entries", type=int, default=2000, help="maximum directory entries visited per bounded root")
    report.add_argument("--max-candidates", type=int, default=10, help="maximum largest/stale candidates retained per root")
    report.add_argument("--print-cleanup-plan", action="store_true", help="print suggested cleanup actions; never execute them")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.json:
        args.format = "json"
    report = build_report(args)
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.format == "text":
        print(render_text(report))
    else:
        print(render_markdown(report))
    return 0


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    repo_input = Path(args.repo).expanduser()
    repo_root, repo_reason = find_repo_root(repo_input)
    extra_paths = [Path(item).expanduser() for item in args.path]
    limits = WalkLimits(
        max_depth=max(args.max_depth, 0),
        max_entries=max(args.max_entries, 1),
        max_candidates=max(args.max_candidates, 1),
        large_file_bytes=max(args.large_file_mib, 1) * BYTES_PER_MIB,
        stale_days=max(args.stale_days, 0),
    )

    filesystem_targets = ordered_paths(
        [
            ("repo/current", repo_root),
            ("home", Path.home()),
            ("tmp", Path("/tmp")),
        ]
        + [("extra", path) for path in extra_paths]
    )
    detail_roots = ordered_paths(default_detail_roots(repo_root) + [("extra", path) for path in extra_paths])
    filesystems = [filesystem_usage(label, path, args.warn_percent, args.critical_percent) for label, path in filesystem_targets]
    roots = [summarize_root(label, path, limits) for label, path in detail_roots]

    cleanup_plan = build_cleanup_plan(repo_root, roots, filesystems, limits)
    return {
        "kind": "opencode_disk_pressure",
        "mode": "report",
        "read_only": True,
        "cleanup_executed": False,
        "print_cleanup_plan": bool(args.print_cleanup_plan),
        "repo_input": str(repo_input),
        "repo_root": str(repo_root),
        "repo_resolution": repo_reason,
        "thresholds": {
            "warn_percent": args.warn_percent,
            "critical_percent": args.critical_percent,
            "large_file_mib": args.large_file_mib,
            "stale_days": limits.stale_days,
            "max_depth": limits.max_depth,
            "max_entries": limits.max_entries,
            "max_candidates": limits.max_candidates,
        },
        "filesystems": filesystems,
        "bounded_roots": roots,
        "cleanup_plan": cleanup_plan,
        "notes": [
            "read-only report; no files were deleted, truncated, pruned, or modified",
            "only configured safe roots and explicit --path values were traversed",
            "home and /tmp filesystem capacity is reported, but home is not broadly traversed by default",
        ],
    }


def find_repo_root(repo_input: Path) -> tuple[Path, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_input), "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return repo_input.resolve(), "not a git repo or git unavailable; using resolved input path"
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()), "git rev-parse --show-toplevel"
    return repo_input.resolve(), "not a git repo or git unavailable; using resolved input path"


def default_detail_roots(repo_root: Path) -> list[tuple[str, Path]]:
    home = Path.home()
    candidates = [
        ("repo/.git", repo_root / ".git"),
        ("repo/logs", repo_root / "logs"),
        ("repo/.logs", repo_root / ".logs"),
        ("repo/tmp", repo_root / "tmp"),
        ("repo/.tmp", repo_root / ".tmp"),
        ("opencode cache", home / ".cache/opencode"),
        ("opencode state", home / ".local/state/opencode"),
        ("opencode data", home / ".local/share/opencode"),
        ("opencode runtime logs", home / ".config/opencode/logs"),
        ("opencode runtime log", home / ".config/opencode/log"),
        ("tmp/opencode", Path("/tmp/opencode")),
    ]
    return candidates


def ordered_paths(items: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
    seen: set[str] = set()
    result: list[tuple[str, Path]] = []
    for label, path in items:
        key = str(path.resolve() if path.exists() else path)
        if key in seen:
            continue
        seen.add(key)
        result.append((label, path))
    return result


def filesystem_usage(label: str, path: Path, warn_percent: float, critical_percent: float) -> dict[str, Any]:
    target = nearest_existing_path(path)
    if target is None:
        return {"label": label, "path": str(path), "exists": False, "error": "no existing parent for disk usage"}
    try:
        usage = shutil.disk_usage(target)
    except OSError as exc:
        return {"label": label, "path": str(path), "usage_path": str(target), "exists": path.exists(), "error": str(exc)}
    percent_used = (usage.used / usage.total * 100.0) if usage.total else 0.0
    status = "critical" if percent_used >= critical_percent else "warning" if percent_used >= warn_percent else "ok"
    return {
        "label": label,
        "path": str(path),
        "usage_path": str(target),
        "exists": path.exists(),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "percent_used": round(percent_used, 1),
        "status": status,
    }


def nearest_existing_path(path: Path) -> Path | None:
    current = path
    while True:
        if current.exists():
            return current
        if current == current.parent:
            return None
        current = current.parent


def summarize_root(label: str, root: Path, limits: WalkLimits) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "label": label,
        "path": str(root),
        "exists": root.exists(),
        "is_dir": root.is_dir(),
        "total_bytes_seen": 0,
        "entries_seen": 0,
        "files_seen": 0,
        "dirs_seen": 0,
        "symlinks_seen": 0,
        "largest_files": [],
        "stale_or_large_candidates": [],
        "skipped": [],
    }
    if not root.exists():
        summary["skipped"].append("path does not exist")
        return summary
    if not root.is_dir():
        summary["entries_seen"] = 1
        summary["files_seen"] = 1
        add_file_candidate(summary, root, limits)
        return summary

    stack: list[tuple[Path, int]] = [(root, 0)]
    stopped_by_count = False
    while stack and summary["entries_seen"] < limits.max_entries:
        directory, depth = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except PermissionError as exc:
            summary["skipped"].append(f"permission denied: {directory}: {exc}")
            continue
        except OSError as exc:
            summary["skipped"].append(f"scan failed: {directory}: {exc}")
            continue

        for entry in entries:
            if summary["entries_seen"] >= limits.max_entries:
                stopped_by_count = True
                break
            summary["entries_seen"] += 1
            entry_path = Path(entry.path)
            try:
                if entry.is_symlink():
                    summary["symlinks_seen"] += 1
                    continue
                if entry.is_file(follow_symlinks=False):
                    summary["files_seen"] += 1
                    add_file_candidate(summary, entry_path, limits)
                elif entry.is_dir(follow_symlinks=False):
                    summary["dirs_seen"] += 1
                    if depth < limits.max_depth:
                        stack.append((entry_path, depth + 1))
                    else:
                        summary["skipped"].append(f"max depth reached: {entry_path}")
            except PermissionError as exc:
                summary["skipped"].append(f"permission denied: {entry_path}: {exc}")
            except OSError as exc:
                summary["skipped"].append(f"stat failed: {entry_path}: {exc}")
    if stopped_by_count or stack:
        summary["skipped"].append(f"max entries reached: {limits.max_entries}")
    summary["largest_files"] = sorted(summary["largest_files"], key=lambda item: item["size_bytes"], reverse=True)[: limits.max_candidates]
    summary["stale_or_large_candidates"] = sorted(
        summary["stale_or_large_candidates"], key=lambda item: (item["size_bytes"], item["age_days"]), reverse=True
    )[: limits.max_candidates]
    return summary


def add_file_candidate(summary: dict[str, Any], path: Path, limits: WalkLimits) -> None:
    try:
        stat = path.stat()
    except OSError as exc:
        summary["skipped"].append(f"stat failed: {path}: {exc}")
        return
    size = int(stat.st_size)
    age_days = int(max(0, (time.time() - stat.st_mtime) // 86400))
    summary["total_bytes_seen"] += size
    file_info = {"path": str(path), "size_bytes": size, "age_days": age_days, "mtime": int(stat.st_mtime)}
    summary["largest_files"].append(file_info)
    reasons = []
    if size >= limits.large_file_bytes:
        reasons.append("large")
    if age_days >= limits.stale_days:
        reasons.append("stale")
    if reasons:
        candidate = dict(file_info)
        candidate["reasons"] = reasons
        summary["stale_or_large_candidates"].append(candidate)


def build_cleanup_plan(repo_root: Path, roots: list[dict[str, Any]], filesystems: list[dict[str, Any]], limits: WalkLimits) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    pressure = [fs for fs in filesystems if fs.get("status") in {"warning", "critical"}]
    if pressure:
        plan.append(
            {
                "title": "Review disk pressure before launching long runs",
                "target": ", ".join(f"{item['label']}={item['percent_used']}%" for item in pressure),
                "suggested_only": True,
                "requires_confirmation": False,
                "command": "python3 opencode/.config/opencode/scripts/opencode_disk_pressure.py report --format markdown --print-cleanup-plan",
                "reason": "one or more configured filesystems crossed the warning/critical threshold",
            }
        )
    for root in roots:
        if not root.get("exists") or not root.get("is_dir"):
            continue
        if root.get("label") == "repo/.git":
            continue
        large_candidates = [
            candidate for candidate in (root.get("stale_or_large_candidates") or []) if "large" in candidate.get("reasons", [])
        ]
        if not large_candidates and root.get("total_bytes_seen", 0) < limits.large_file_bytes:
            continue
        path = root["path"]
        plan.append(
            {
                "title": f"Manual review for {root['label']}",
                "target": path,
                "suggested_only": True,
                "requires_confirmation": True,
                "command": f"find {shlex.quote(path)} -maxdepth {limits.max_depth} -type f -mtime +{limits.stale_days} -print",
                "reason": "bounded scan found stale/large files or a sizable known cache/log root",
                "destructive_followup": "delete or clear only selected files after explicit human approval; this helper does not do it",
            }
        )
    git_root = repo_root / ".git"
    if git_root.exists():
        plan.append(
            {
                "title": "Optional git object-store maintenance",
                "target": str(git_root),
                "suggested_only": True,
                "requires_confirmation": True,
                "command": f"git -C {shlex.quote(str(repo_root))} gc --auto",
                "reason": "repo .git size is reported for awareness; maintenance mutates git metadata and should be a separate explicit action",
            }
        )
    if not plan:
        plan.append(
            {
                "title": "No cleanup pressure detected within configured bounds",
                "target": "configured safe roots",
                "suggested_only": True,
                "requires_confirmation": False,
                "command": None,
                "reason": "bounded read-only report did not find threshold-crossing candidates",
            }
        )
    return plan


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# OpenCode Disk Pressure Report", ""]
    lines.extend(render_common_lines(report, bullet="-"))
    lines.extend(["", "## Filesystems"])
    for fs in report["filesystems"]:
        lines.append(format_filesystem_line(fs, bullet="-"))
    lines.extend(["", "## Bounded roots"])
    for root in report["bounded_roots"]:
        lines.append(format_root_line(root, bullet="-"))
        for item in root.get("largest_files", [])[:3]:
            lines.append(f"  - largest: `{item['path']}` {format_bytes(item['size_bytes'])} age={item['age_days']}d")
        for skipped in root.get("skipped", [])[:3]:
            lines.append(f"  - skipped: {skipped}")
    lines.extend(["", "## Cleanup plan (suggested only; nothing executed)"])
    for item in report["cleanup_plan"]:
        lines.append(format_plan_line(item, bullet="-"))
    return "\n".join(lines)


def render_text(report: dict[str, Any]) -> str:
    lines = ["OpenCode Disk Pressure Report", "=============================", ""]
    lines.extend(render_common_lines(report, bullet="*"))
    lines.extend(["", "Filesystems:"])
    for fs in report["filesystems"]:
        lines.append(format_filesystem_line(fs, bullet="*"))
    lines.extend(["", "Bounded roots:"])
    for root in report["bounded_roots"]:
        lines.append(format_root_line(root, bullet="*"))
    lines.extend(["", "Cleanup plan (suggested only; nothing executed):"])
    for item in report["cleanup_plan"]:
        lines.append(format_plan_line(item, bullet="*"))
    return "\n".join(lines)


def render_common_lines(report: dict[str, Any], bullet: str) -> list[str]:
    thresholds = report["thresholds"]
    return [
        f"{bullet} repo: `{report['repo_root']}` ({report['repo_resolution']})",
        f"{bullet} read-only: {report['read_only']} cleanup_executed={report['cleanup_executed']}",
        f"{bullet} thresholds: warn={thresholds['warn_percent']}% critical={thresholds['critical_percent']}% "
        f"large={thresholds['large_file_mib']}MiB stale={thresholds['stale_days']}d "
        f"depth={thresholds['max_depth']} entries={thresholds['max_entries']}",
    ]


def format_filesystem_line(fs: dict[str, Any], bullet: str) -> str:
    if fs.get("error"):
        return f"{bullet} {fs['label']}: `{fs['path']}` error={fs['error']}"
    return (
        f"{bullet} {fs['label']}: `{fs['path']}` usage_path=`{fs['usage_path']}` "
        f"used={fs['percent_used']}% free={format_bytes(fs['free_bytes'])} status={fs['status']}"
    )


def format_root_line(root: dict[str, Any], bullet: str) -> str:
    return (
        f"{bullet} {root['label']}: `{root['path']}` exists={root['exists']} "
        f"entries={root['entries_seen']} files={root['files_seen']} dirs={root['dirs_seen']} "
        f"seen={format_bytes(root['total_bytes_seen'])} skipped={len(root['skipped'])}"
    )


def format_plan_line(item: dict[str, Any], bullet: str) -> str:
    command = f" command=`{item['command']}`" if item.get("command") else ""
    return (
        f"{bullet} {item['title']}: target=`{item['target']}` requires_confirmation={item['requires_confirmation']}"
        f" suggested_only={item['suggested_only']}{command}; reason={item['reason']}"
    )


def format_bytes(value: int) -> str:
    if value >= BYTES_PER_GIB:
        return f"{value / BYTES_PER_GIB:.1f}GiB"
    if value >= BYTES_PER_MIB:
        return f"{value / BYTES_PER_MIB:.1f}MiB"
    if value >= 1024:
        return f"{value / 1024:.1f}KiB"
    return f"{value}B"


if __name__ == "__main__":
    raise SystemExit(main())
