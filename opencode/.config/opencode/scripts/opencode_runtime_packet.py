#!/usr/bin/env python3
"""Read-only dotfiles/OpenCode/tmux runtime context packet helper."""

from __future__ import annotations

import argparse
import json
import os
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
        description="Build a read-only runtime packet for dotfiles OpenCode config and tmux context.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              opencode_runtime_packet.py packet --repo . --format markdown --dry-run
              opencode_runtime_packet.py packet --repo . --format json --dry-run
              opencode_runtime_packet.py packet --repo . --run-opencode-config

            Default behavior is read-only/dry-run and does not restart or reload OpenCode/tmux.
            """
        ).strip(),
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    packet = subparsers.add_parser("packet", help="collect runtime context")
    packet.add_argument("--repo", default=".", help="dotfiles repository path, default: .")
    packet.add_argument("--runtime", default=str(Path.home() / ".config/opencode"), help="runtime OpenCode config path")
    packet.add_argument("--format", choices=("json", "markdown"), default="json", help="output format")
    packet.add_argument("--dry-run", action="store_true", help="with --run-opencode-config, report the planned command without running it")
    packet.add_argument("--run-opencode-config", action="store_true", help="run local opencode --pure debug config smoke")
    packet.add_argument("--timeout", type=int, default=15, help="per-command timeout seconds")
    return parser.parse_args()


def run_command(command: list[str], timeout: int, cwd: str | None = None, env: dict[str, str] | None = None) -> CommandResult:
    try:
        result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return CommandResult(command, None, stdout, stderr or f"timed out after {timeout}s", True)
    return CommandResult(command, result.returncode, result.stdout, result.stderr)


def main() -> int:
    args = parse_args()
    packet = build_packet(Path(args.repo), Path(args.runtime).expanduser(), args.run_opencode_config and not args.dry_run, args.dry_run, args.timeout)
    if args.format == "markdown":
        print(render_markdown(packet))
    else:
        print(json.dumps(packet, indent=2, sort_keys=True))
    return 0 if not packet.get("fatal") else 1


def build_packet(repo: Path, runtime_path: Path, run_opencode_config: bool, dry_run: bool, timeout: int) -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    root_result = run_command(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], timeout)
    commands.append(root_result.as_dict())
    if root_result.exit_code != 0:
        return {
            "kind": "opencode_runtime_packet",
            "fatal": True,
            "repo_input": str(repo),
            "blockers": ["not a git worktree or git unavailable"],
            "commands": commands,
        }
    repo_root = Path(root_result.stdout.strip())
    source_path = repo_root / "opencode/.config/opencode"
    status_result = run_command(["git", "-C", str(repo_root), "status", "--short", "--", "opencode/.config/opencode"], timeout)
    commands.append(status_result.as_dict())

    opencode_smoke = opencode_config_smoke(repo_root, run_opencode_config, timeout)
    commands.extend(opencode_smoke.pop("commands"))
    tmux = tmux_context(timeout)
    commands.extend(tmux.pop("commands"))

    return {
        "kind": "opencode_runtime_packet",
        "fatal": False,
        "repo_root": str(repo_root),
        "source_path": str(source_path),
        "runtime_path": str(runtime_path),
        "source_exists": source_path.exists(),
        "runtime_exists": runtime_path.exists(),
        "dry_run": dry_run,
        "runtime_link": link_info(runtime_path, source_path),
        "sample_links": sample_link_info(source_path, runtime_path),
        "changed_source_files": [line for line in status_result.stdout.splitlines() if line.strip()],
        "opencode": opencode_smoke,
        "tmux": tmux,
        "agent_board_hints": agent_board_hints(repo_root),
        "restart_caveats": [
            "OpenCode prompt/config/agent/skill/plugin changes load at startup; quit and restart OpenCode before judging runtime behavior.",
            "Tmux config changes need source-file/reload or a new session depending on the changed file.",
            "This packet does not restart, reload, or mutate tmux/OpenCode state.",
        ],
        "commands": commands,
    }


def link_info(runtime_path: Path, source_path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"path": str(runtime_path), "exists": runtime_path.exists(), "is_symlink": runtime_path.is_symlink()}
    if runtime_path.is_symlink():
        target = runtime_path.readlink()
        resolved = runtime_path.resolve()
        info.update({"target": str(target), "resolved": str(resolved), "points_into_source": str(resolved).startswith(str(source_path))})
    return info


def sample_link_info(source_path: Path, runtime_path: Path) -> list[dict[str, Any]]:
    samples = ["agents/orchestrator.md", "commands/insights.md", "user-profile.yaml"]
    result = []
    for sample in samples:
        source = source_path / sample
        runtime = runtime_path / sample
        item: dict[str, Any] = {"relative": sample, "source_exists": source.exists(), "runtime_exists": runtime.exists(), "runtime_is_symlink": runtime.is_symlink()}
        if runtime.is_symlink():
            item["runtime_target"] = str(runtime.readlink())
            item["runtime_resolved"] = str(runtime.resolve())
        result.append(item)
    return result


def opencode_config_smoke(repo_root: Path, should_run: bool, timeout: int) -> dict[str, Any]:
    if shutil.which("opencode") is None:
        return {"available": False, "smoke": "skipped", "reason": "opencode executable not found", "commands": []}
    command = ["opencode", "--pure", "debug", "config"]
    if not should_run:
        return {
            "available": True,
            "smoke": "not-run",
            "planned_command": f'XDG_CONFIG_HOME="{repo_root / "opencode/.config"}" {shlex.join(command)}',
            "commands": [],
        }
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(repo_root / "opencode/.config")
    result = run_command(command, timeout, cwd=str(repo_root), env=env)
    return {"available": True, "smoke": "run", "result": result.as_dict(include_stdout=False), "commands": [result.as_dict(include_stdout=False)]}


def tmux_context(timeout: int) -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    if shutil.which("tmux") is None:
        return {"available": False, "reason": "tmux executable not found", "commands": commands}
    if not os.environ.get("TMUX"):
        return {"available": False, "reason": "TMUX environment variable is not set", "commands": commands}
    result = run_command(["tmux", "display-message", "-p", "#S:#I.#P #{pane_current_path}"], timeout)
    commands.append(result.as_dict())
    if result.exit_code != 0:
        return {"available": False, "reason": result.stderr.strip() or "tmux display-message failed", "commands": commands}
    parts = result.stdout.strip().split(" ", 1)
    return {"available": True, "target": parts[0], "pane_current_path": parts[1] if len(parts) > 1 else None, "commands": commands}


def agent_board_hints(repo_root: Path) -> dict[str, Any]:
    board = repo_root / "tmux/.tmux/opencode-agent-board"
    renderer = repo_root / "opencode/.config/opencode/scripts/opencode_progress_render.py"
    return {
        "agent_board_script": str(board),
        "agent_board_exists": board.exists(),
        "progress_renderer": str(renderer),
        "progress_renderer_exists": renderer.exists(),
        "hint": "Agent Board/progress UI state may require a tmux reload or new pane depending on the changed tmux files.",
    }


def render_markdown(packet: dict[str, Any]) -> str:
    lines = ["# OpenCode Runtime Packet", ""]
    if packet.get("fatal"):
        lines.append("Fatal blocker: " + "; ".join(packet.get("blockers", [])))
        return "\n".join(lines)
    lines.extend(
        [
            f"- repo root: `{packet['repo_root']}`",
            f"- stowed source: `{packet['source_path']}` exists={packet['source_exists']}",
            f"- runtime path: `{packet['runtime_path']}` exists={packet['runtime_exists']}",
            f"- runtime symlink: {packet['runtime_link'].get('is_symlink')}",
            f"- changed source files: {len(packet['changed_source_files'])}",
            "",
            "## OpenCode",
            f"- available: {packet['opencode'].get('available')}",
            f"- smoke: {packet['opencode'].get('smoke')}",
        ]
    )
    if packet["opencode"].get("planned_command"):
        lines.append(f"- planned smoke: `{packet['opencode']['planned_command']}`")
    lines.extend(["", "## Stow / symlink samples"])
    for sample in packet["sample_links"]:
        target = f" target=`{sample.get('runtime_target')}`" if sample.get("runtime_target") else ""
        lines.append(
            f"- `{sample['relative']}` source={sample['source_exists']} runtime={sample['runtime_exists']} "
            f"runtime_symlink={sample['runtime_is_symlink']}{target}"
        )
    hints = packet["agent_board_hints"]
    lines.extend(
        [
            "",
            "## Agent Board hints",
            f"- board script: `{hints['agent_board_script']}` exists={hints['agent_board_exists']}",
            f"- progress renderer: `{hints['progress_renderer']}` exists={hints['progress_renderer_exists']}",
            f"- caveat: {hints['hint']}",
        ]
    )
    lines.extend(["", "## Tmux", f"- available: {packet['tmux'].get('available')}"])
    if packet["tmux"].get("target"):
        lines.append(f"- target: `{packet['tmux']['target']}`")
    elif packet["tmux"].get("reason"):
        lines.append(f"- reason: {packet['tmux']['reason']}")
    lines.extend(["", "## Restart / reload caveats"])
    for caveat in packet["restart_caveats"]:
        lines.append(f"- {caveat}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
