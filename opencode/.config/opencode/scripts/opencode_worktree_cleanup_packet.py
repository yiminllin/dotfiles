#!/usr/bin/env python3
"""Read-only git worktree cleanup decision packet helper."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
        description="Build a read-only cleanup packet for git worktrees.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              opencode_worktree_cleanup_packet.py packet --repo . --format markdown
              opencode_worktree_cleanup_packet.py packet --repo . --format json

            This helper never removes, prunes, stashes, resets, or moves worktrees.
            Cleanup commands in the packet are suggested_only and require a human decision.
            """
        ).strip(),
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    packet = subparsers.add_parser("packet", help="collect worktree cleanup context")
    packet.add_argument("--repo", default=".", help="repository/worktree path, default: .")
    packet.add_argument("--format", choices=("json", "markdown"), default="json", help="output format")
    packet.add_argument("--timeout", type=int, default=20, help="per-git-command timeout seconds")
    return parser.parse_args()


def run_command(command: list[str], timeout: int, cwd: str | None = None) -> CommandResult:
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return CommandResult(command, None, stdout, stderr or f"timed out after {timeout}s", True)
    return CommandResult(command, result.returncode, result.stdout, result.stderr)


def main() -> int:
    args = parse_args()
    packet = build_packet(Path(args.repo), args.timeout)
    if args.format == "markdown":
        print(render_markdown(packet))
    else:
        print(json.dumps(packet, indent=2, sort_keys=True))
    return 0 if not packet.get("fatal") else 1


def build_packet(repo: Path, timeout: int) -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    root_result = run_command(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], timeout)
    commands.append(root_result.as_dict())
    if root_result.exit_code != 0:
        return {
            "kind": "opencode_worktree_cleanup_packet",
            "fatal": True,
            "repo_input": str(repo),
            "blockers": ["not a git worktree or git unavailable"],
            "commands": commands,
        }

    repo_root = Path(root_result.stdout.strip())
    list_result = run_command(["git", "-C", str(repo_root), "worktree", "list", "--porcelain"], timeout)
    commands.append(list_result.as_dict())
    entries = parse_worktree_porcelain(list_result.stdout) if list_result.exit_code == 0 else []

    worktrees = []
    for entry in entries:
        detail, results = classify_worktree(repo_root, entry, timeout)
        worktrees.append(detail)
        commands.extend(result.as_dict() for result in results)

    return {
        "kind": "opencode_worktree_cleanup_packet",
        "fatal": False,
        "repo_root": str(repo_root),
        "current_worktree": str(repo_root),
        "counts": count_classes(worktrees),
        "worktrees": worktrees,
        "safe_choices": build_safe_choices(worktrees),
        "commands": commands,
        "notes": [
            "read-only packet; no cleanup was executed",
            "suggested commands are examples for a human to review, not automatic actions",
        ],
    }


def parse_worktree_porcelain(output: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in output.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key in {"bare", "detached"}:
            current[key] = True
        elif key == "prunable":
            current[key] = value or True
        else:
            current[key] = value
    if current:
        entries.append(current)
    return entries


def classify_worktree(repo_root: Path, entry: dict[str, Any], timeout: int) -> tuple[dict[str, Any], list[CommandResult]]:
    path = Path(str(entry.get("worktree", "")))
    detail: dict[str, Any] = {
        "path": str(path),
        "head": entry.get("HEAD"),
        "branch": entry.get("branch"),
        "detached": bool(entry.get("detached")),
        "bare": bool(entry.get("bare")),
        "prunable": entry.get("prunable"),
        "suggested_only": [],
        "blockers": [],
    }

    if not path.exists():
        detail.update({"class": "missing", "dirty": None, "status_entries": None})
        detail["blockers"].append("worktree path is missing; inspect ownership before pruning")
        detail["suggested_only"].append(f"git -C {shlex.quote(str(repo_root))} worktree prune --dry-run")
        return detail, []

    if not path.is_dir() or detail["bare"]:
        detail.update({"class": "unknown", "dirty": None, "status_entries": None})
        detail["blockers"].append("path is not a normal accessible worktree directory")
        return detail, []

    status = run_command(["git", "-C", str(path), "status", "--porcelain=v1"], timeout)
    if status.exit_code != 0:
        detail.update({"class": "unknown", "dirty": None, "status_entries": None})
        detail["blockers"].append("git status failed for this worktree")
        return detail, [status]

    status_lines = [line for line in status.stdout.splitlines() if line.strip()]
    untracked = sum(1 for line in status_lines if line.startswith("??"))
    detail.update(
        {
            "class": "dirty" if status_lines else "clean",
            "dirty": bool(status_lines),
            "status_entries": len(status_lines),
            "untracked_entries": untracked,
        }
    )
    if status_lines:
        detail["blockers"].append("worktree has local changes or untracked files")
    elif path.resolve() == repo_root.resolve():
        detail["blockers"].append("current worktree; do not remove from its own cleanup packet")
    else:
        merge_status, merge_result = merged_into_head(repo_root, detail.get("branch"), timeout)
        detail["merged_into_current_head"] = merge_status
        if merge_status is True:
            detail["suggested_only"].append(f"git worktree remove -- {shlex.quote(str(path))}")
        elif merge_status is False:
            detail["blockers"].append("branch is not merged into current HEAD")
        else:
            detail["blockers"].append("branch merge status is unknown")
    if detail["detached"]:
        detail["blockers"].append("detached worktree; verify ownership and desired HEAD before cleanup")
    results = [status]
    if not status_lines and path.resolve() != repo_root.resolve() and not detail["detached"]:
        results.append(merge_result)
    return detail, results


def merged_into_head(repo_root: Path, branch: Any, timeout: int) -> tuple[bool | None, CommandResult]:
    if not branch:
        return None, CommandResult(["git", "-C", str(repo_root), "merge-base", "--is-ancestor", "<unknown>", "HEAD"], None, "", "branch unknown")
    result = run_command(["git", "-C", str(repo_root), "merge-base", "--is-ancestor", str(branch), "HEAD"], timeout)
    if result.exit_code == 0:
        return True, result
    if result.exit_code == 1:
        return False, result
    return None, result


def count_classes(worktrees: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"clean": 0, "dirty": 0, "missing": 0, "unknown": 0}
    for worktree in worktrees:
        cls = str(worktree.get("class", "unknown"))
        counts[cls if cls in counts else "unknown"] += 1
    return counts


def build_safe_choices(worktrees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    for worktree in worktrees:
        cls = worktree.get("class")
        path = worktree.get("path")
        if cls == "clean" and worktree.get("suggested_only"):
            choices.append(
                {
                    "choice": len(choices) + 1,
                    "path": path,
                    "action": "review clean worktree removal",
                    "suggested_only": worktree.get("suggested_only", []),
                    "blockers": worktree.get("blockers", []),
                }
            )
        elif cls == "missing":
            choices.append(
                {
                    "choice": len(choices) + 1,
                    "path": path,
                    "action": "review prune dry-run for missing worktree metadata",
                    "suggested_only": worktree.get("suggested_only", []),
                    "blockers": worktree.get("blockers", []),
                }
            )
    if not choices:
        choices.append(
            {
                "choice": 1,
                "action": "no cleanup candidate",
                "suggested_only": [],
                "blockers": ["no clean or missing worktree candidates found"],
            }
        )
    return choices


def render_markdown(packet: dict[str, Any]) -> str:
    lines = ["# OpenCode Worktree Cleanup Packet", ""]
    if packet.get("fatal"):
        lines.append("Fatal blocker: " + "; ".join(packet.get("blockers", [])))
        return "\n".join(lines)
    lines.extend(
        [
            f"- repo root: `{packet['repo_root']}`",
            f"- current worktree: `{packet['current_worktree']}`",
            f"- counts: `{json.dumps(packet['counts'], sort_keys=True)}`",
            "- mutation: none; packet is read-only",
            "",
            "## Worktrees",
        ]
    )
    for worktree in packet["worktrees"]:
        branch = worktree.get("branch") or ("detached" if worktree.get("detached") else "unknown")
        lines.append(
            f"- `{worktree.get('class')}` `{worktree.get('path')}` branch=`{branch}` "
            f"dirty={worktree.get('dirty')} entries={worktree.get('status_entries')}"
        )
        if "merged_into_current_head" in worktree:
            lines.append(f"  - merged into current HEAD: {worktree['merged_into_current_head']}")
        for blocker in worktree.get("blockers", []):
            lines.append(f"  - blocker: {blocker}")
    lines.extend(["", "## Numbered safe choices"])
    for choice in packet["safe_choices"]:
        lines.append(f"{choice['choice']}. {choice['action']}")
        if choice.get("path"):
            lines.append(f"   - path: `{choice['path']}`")
        for command in choice.get("suggested_only", []):
            lines.append(f"   - suggested_only: `{command}`")
        for blocker in choice.get("blockers", []):
            lines.append(f"   - blocker: {blocker}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
