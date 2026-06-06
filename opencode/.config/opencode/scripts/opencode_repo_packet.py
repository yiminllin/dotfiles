#!/usr/bin/env python3
"""Generic read-only local repo and optional stack status packet helper."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
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

    def as_dict(self, include_stdout: bool = True) -> dict[str, Any]:
        return {
            "command": shlex.join(self.command),
            "exit_code": self.exit_code,
            "stdout": self.stdout.strip() if include_stdout else None,
            "stderr": self.stderr.strip(),
            "timed_out": self.timed_out,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a generic read-only git/git-spice/optional-gh repo packet.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              opencode_repo_packet.py packet --repo . --format markdown --no-gh
              opencode_repo_packet.py packet --repo . --format json
              opencode_repo_packet.py packet --repo . --gh
              opencode_repo_packet.py packet --repo . --include-gh

            Default behavior is local-only and read-only. gh is skipped unless --gh or --include-gh is passed.
            """
        ).strip(),
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    packet = subparsers.add_parser("packet", help="collect local repo/stack context")
    packet.add_argument("--repo", default=".", help="repository/worktree path, default: .")
    packet.add_argument("--format", choices=("json", "markdown"), default="json", help="output format")
    packet.add_argument("--base", help="base branch/ref for merge-base and diff basis")
    packet.add_argument("--gh", action="store_true", help="opt in to read-only gh context")
    packet.add_argument("--include-gh", action="store_true", help="alias for --gh")
    packet.add_argument("--no-gh", action="store_true", help="explicitly skip gh context; this is the default")
    packet.add_argument("--timeout", type=int, default=20, help="per-command timeout seconds")
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
    packet = build_packet(Path(args.repo), args.base, (args.gh or args.include_gh) and not args.no_gh, args.timeout)
    if args.format == "markdown":
        print(render_markdown(packet))
    else:
        print(json.dumps(packet, indent=2, sort_keys=True))
    return 0 if not packet.get("fatal") else 1


def build_packet(repo: Path, base_hint: str | None, use_gh: bool, timeout: int) -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    root_result = run_command(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], timeout)
    commands.append(root_result.as_dict())
    if root_result.exit_code != 0:
        return {
            "kind": "opencode_repo_packet",
            "fatal": True,
            "repo_input": str(repo),
            "blockers": ["not a git worktree or git unavailable"],
            "commands": commands,
        }
    root = Path(root_result.stdout.strip())
    git, git_commands = collect_git(root, base_hint, timeout)
    spice, spice_commands = collect_git_spice(root, timeout)
    gh, gh_commands = collect_gh(root, use_gh, timeout)
    commands.extend(command.as_dict(include_stdout=command.exit_code != 0) for command in git_commands)
    commands.extend(command.as_dict(include_stdout=True) for command in spice_commands)
    commands.extend(command.as_dict(include_stdout=False) for command in gh_commands)

    return {
        "kind": "opencode_repo_packet",
        "fatal": False,
        "repo_root": str(root),
        "git": git,
        "git_spice": spice,
        "gh": gh,
        "next_safe_commands": next_safe_commands(git, use_gh),
        "blockers": blockers(git, spice, gh),
        "commands": commands,
        "notes": ["read-only packet; no fetch, push, PR mutation, checkout, stash, reset, or cleanup was attempted"],
    }


def collect_git(root: Path, base_hint: str | None, timeout: int) -> tuple[dict[str, Any], list[CommandResult]]:
    command_specs = {
        "branch": ["git", "branch", "--show-current"],
        "head": ["git", "rev-parse", "--short", "HEAD"],
        "upstream": ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        "status": ["git", "status", "--porcelain=v1"],
        "recent": ["git", "log", "--oneline", "-5"],
        "diff_stat": ["git", "diff", "--stat"],
        "staged_diff_stat": ["git", "diff", "--cached", "--stat"],
    }
    results = {name: run_command(command, timeout, cwd=str(root)) for name, command in command_specs.items()}
    base = resolve_base(root, base_hint, timeout)
    base_commands = base.pop("commands")
    merge_base = None
    if base["ref"]:
        merge = run_command(["git", "merge-base", "HEAD", base["ref"]], timeout, cwd=str(root))
        results["merge_base"] = merge
        merge_base = merge.stdout.strip() if merge.exit_code == 0 else None
    status_lines = [line for line in results["status"].stdout.splitlines() if line.strip()]
    return (
        {
            "branch": clean_stdout(results["branch"]),
            "head": clean_stdout(results["head"]),
            "upstream": clean_stdout(results["upstream"]) if results["upstream"].exit_code == 0 else None,
            "dirty": bool(status_lines),
            "dirty_entries": len(status_lines),
            "untracked_entries": sum(1 for line in status_lines if line.startswith("??")),
            "recent_commits": split_lines(results["recent"].stdout),
            "diff_stat": split_lines(results["diff_stat"].stdout),
            "staged_diff_stat": split_lines(results["staged_diff_stat"].stdout),
            "base": base,
            "merge_base": merge_base,
        },
        list(results.values()) + base_commands,
    )


def resolve_base(root: Path, base_hint: str | None, timeout: int) -> dict[str, Any]:
    commands: list[CommandResult] = []
    candidates = [base_hint] if base_hint else ["origin/main", "origin/master", "origin/develop", "main", "master", "develop"]
    for candidate in [item for item in candidates if item]:
        result = run_command(["git", "rev-parse", "--verify", candidate], timeout, cwd=str(root))
        commands.append(result)
        if result.exit_code == 0:
            return {"ref": candidate, "source": "hint" if candidate == base_hint else "local-candidate", "commands": commands}
    return {"ref": None, "source": "not-found", "commands": commands}


def collect_git_spice(root: Path, timeout: int) -> tuple[dict[str, Any], list[CommandResult]]:
    executable = shutil.which("gs") or shutil.which("git-spice")
    if executable is None:
        return {"available": False, "reason": "git-spice/gs executable not found"}, []
    candidates = [
        [executable, "log", "short"],
        [executable, "log", "long"],
        [executable, "log", "--no-interactive"],
        [executable, "log"],
        [executable, "stack", "log", "--no-interactive"],
        [executable, "stack", "log"],
    ]
    results: list[CommandResult] = []
    for command in candidates:
        result = run_command(command, timeout, cwd=str(root))
        results.append(result)
        if result.exit_code == 0:
            return {"available": True, "command": shlex.join(command), "summary": split_lines(result.stdout)}, results
    return {"available": True, "error": "git-spice found, but known read-only log commands failed"}, results


def collect_gh(root: Path, use_gh: bool, timeout: int) -> tuple[dict[str, Any], list[CommandResult]]:
    if not use_gh:
        return {"enabled": False, "reason": "skipped by default; pass --gh to opt in"}, []
    if shutil.which("gh") is None:
        return {"enabled": True, "available": False, "reason": "gh executable not found"}, []
    result = run_command(["gh", "pr", "status"], timeout, cwd=str(root))
    if result.exit_code != 0:
        return {"enabled": True, "available": True, "error": result.stderr.strip() or result.stdout.strip(), "note": "helper did not start gh auth login"}, [result]
    return {"enabled": True, "available": True, "pr_status": split_lines(result.stdout)}, [result]


def split_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def clean_stdout(result: CommandResult) -> str | None:
    text = result.stdout.strip()
    return text or None


def next_safe_commands(git: dict[str, Any], use_gh: bool) -> list[str]:
    commands = ["git status --short", "git diff --stat", "git diff --cached --stat"]
    if git.get("base", {}).get("ref"):
        commands.append(f"git diff --stat {git['base']['ref']}...HEAD")
    if not use_gh:
        commands.append("python3 opencode/.config/opencode/scripts/opencode_repo_packet.py packet --repo . --format markdown --no-gh")
    return commands


def blockers(git: dict[str, Any], spice: dict[str, Any], gh: dict[str, Any]) -> list[str]:
    items: list[str] = []
    if git.get("dirty"):
        items.append(f"working tree has {git.get('dirty_entries')} dirty/untracked entries")
    if not git.get("base", {}).get("ref"):
        items.append("no local base ref found for merge-base/diff-basis")
    if spice.get("error"):
        items.append(str(spice["error"]))
    if gh.get("error"):
        items.append("gh context failed; do not start auth automatically")
    return items


def render_markdown(packet: dict[str, Any]) -> str:
    lines = ["# OpenCode Repo Packet", ""]
    if packet.get("fatal"):
        lines.append("Fatal blocker: " + "; ".join(packet.get("blockers", [])))
        return "\n".join(lines)
    git = packet["git"]
    lines.extend(
        [
            f"- repo root: `{packet['repo_root']}`",
            f"- branch: `{git.get('branch')}` upstream=`{git.get('upstream')}` head=`{git.get('head')}`",
            f"- dirty: {git.get('dirty')} entries={git.get('dirty_entries')} untracked={git.get('untracked_entries')}",
            f"- base: `{git.get('base', {}).get('ref')}` source={git.get('base', {}).get('source')}",
            f"- gh: {packet['gh'].get('reason') or ('enabled' if packet['gh'].get('enabled') else 'disabled')}",
            "",
            "## Recent commits",
        ]
    )
    lines.extend(f"- `{line}`" for line in git.get("recent_commits", []))
    lines.extend(["", "## Staged diff stat"])
    lines.extend(f"- {line}" for line in (git.get("staged_diff_stat") or ["no staged diff stat output"]))
    lines.extend(["", "## Unstaged diff stat"])
    lines.extend(f"- {line}" for line in (git.get("diff_stat") or ["no unstaged diff stat output"]))
    lines.extend(["", "## Git-spice"])
    spice = packet["git_spice"]
    if spice.get("available") and spice.get("summary"):
        lines.extend(f"- {line}" for line in spice["summary"][:20])
    elif spice.get("available"):
        lines.append("- available; no stack entries reported by read-only log command")
    else:
        lines.append(f"- unavailable/error: {spice.get('reason') or spice.get('error')}")
    lines.extend(["", "## Blockers"])
    if packet["blockers"]:
        lines.extend(f"- {item}" for item in packet["blockers"])
    else:
        lines.append("- none detected by read-only packet")
    lines.extend(["", "## Next safe commands"])
    lines.extend(f"- `{command}`" for command in packet["next_safe_commands"])
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
