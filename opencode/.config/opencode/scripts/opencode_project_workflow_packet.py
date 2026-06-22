#!/usr/bin/env python3
"""Read-only Jira/GitHub project workflow status packet helper."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_STATE_ROOT = Path("~/.local/state/opencode-project-workflow").expanduser()
JIRA_KEY_RE = re.compile(r"\b(?:FSW-\d+|[A-Z][A-Z0-9]+-\d+)\b", re.IGNORECASE)
PR_URL_RE = re.compile(r"^https?://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)/?$")
SECRET_KEY_RE = re.compile(r"token|secret|password|credential|authorization|cookie", re.IGNORECASE)
SECRET_VALUE_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|[A-Za-z0-9+/]{32,}={0,2})\b"
)
MAX_EXCERPT_CHARS = 1200
MAX_STATE_STRING_CHARS = 2000
MAX_STATE_LIST_ITEMS = 25
MAX_STATE_DEPTH = 5
PENDING_SYNC_KIND_DELEGATES = (
    ("Jira status move", "jira-ticket"),
    ("Jira comment", "jira-ticket"),
    ("Jira description update", "jira-ticket"),
    ("Jira link update", "jira-ticket"),
    ("PR body refresh", "pr-description-chain-writer"),
    ("stack submit", "stacked-pr-workflow"),
    ("stack restack", "stacked-pr-workflow"),
    ("worktree action", "stacked-pr-workflow"),
    ("review reply", "pr-address-comments"),
    ("review resolution", "pr-address-comments"),
)
ALLOWED_PENDING_SYNC_KINDS = {kind.lower(): kind for kind, _ in PENDING_SYNC_KIND_DELEGATES}
DELEGATE_SKILL_BY_KIND = dict(PENDING_SYNC_KIND_DELEGATES)
VAGUE_PROPOSED_ACTION_RE = re.compile(
    r"\b(?:inspect .*read-only|review existing pending state|create or update local workflow state|"
    r"account for dirty|missing context)\b",
    re.IGNORECASE,
)


@dataclass
class CommandResult:
    command: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    def as_dict(self, include_stdout: bool = False) -> dict[str, Any]:
        stdout = self.stdout.strip()
        stderr = self.stderr.strip()
        record: dict[str, Any] = {
            "command": shlex.join(self.command),
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "stdout_chars": len(stdout),
            "stderr_chars": len(stderr),
        }
        if include_stdout and stdout:
            record["stdout"] = redact_text(truncate_text(stdout))
        if stderr and (self.timed_out or self.exit_code not in (0, None)):
            record["stderr"] = redact_text(truncate_text(stderr))
        return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a read-only Jira/GitHub project workflow status packet.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              opencode_project_workflow_packet.py packet --repo . --format markdown
              opencode_project_workflow_packet.py packet --repo . --format json --jira-key FSW-12345 --pivot

            Local-only and read-only by default; GitHub CLI reads require --gh.
            Never writes Jira, GitHub, auth, git, worktree, or external state.
            """
        ).strip(),
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    packet = subparsers.add_parser("packet", help="collect project workflow context")
    packet.add_argument("--repo", default=".", help="repository/worktree path, default: .")
    packet.add_argument("--format", choices=("markdown", "json"), default="json", help="output format")
    packet.add_argument("--timeout", type=int, default=20, help="per-command timeout seconds")
    packet.add_argument("--jira-key", help="known Jira key hint, e.g. FSW-12345")
    packet.add_argument("--project-id", help="local project workflow id/state filename stem")
    packet.add_argument("--pr", help="GitHub PR number or URL hint")
    packet.add_argument("--state-file", help="explicit local project workflow state JSON file")
    packet.add_argument("--state-dir", help="local project workflow state directory")
    packet.add_argument("--gh", action="store_true", help="opt in to read-only gh auth status and PR view probes")
    packet.add_argument("--no-gh", action="store_true", help="skip gh reads; this is the default")
    packet.add_argument("--pivot", action="store_true", help="include read-only freeze-write pivot context")
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
    packet = build_packet(args)
    if args.format == "markdown":
        print(render_markdown(packet))
    else:
        print(json.dumps(packet, indent=2, sort_keys=True))
    return 0 if not packet.get("fatal") else 1


def build_packet(args: argparse.Namespace) -> dict[str, Any]:
    commands: list[CommandResult] = []
    repo_input = Path(args.repo).expanduser()
    root_result = run_command(["git", "-C", str(repo_input), "rev-parse", "--show-toplevel"], args.timeout)
    commands.append(root_result)
    if root_result.exit_code != 0:
        detections = build_detection_index()
        if args.jira_key:
            add_jira_source(detections, args.jira_key, "input:--jira-key")
        packet = {
            "kind": "opencode_project_workflow_packet",
            "fatal": True,
            "generated_at": timestamp(),
            "repo_input": str(repo_input),
            "inputs": input_summary(args),
            "detections": finalize_detections(detections),
            "observed": {"git": {"inside_work_tree": False}},
            "pending_sync": [],
            "blockers": ["not a git worktree or git unavailable; read needed: git rev-parse --show-toplevel"],
            "command_trace": command_trace(commands),
            "notes": read_only_notes(),
        }
        if args.pivot:
            packet["pivot_context"] = build_pivot_context(
                packet.get("active_hints", {}), packet.get("observed", {}), [], packet.get("blockers", [])
            )
        return packet

    repo_root = Path(root_result.stdout.strip())
    git, git_commands = collect_git(repo_root, args.timeout)
    remotes, remote_commands = collect_remotes(repo_root, args.timeout)
    worktrees, worktree_commands = collect_worktrees(repo_root, args.timeout)
    git_spice, spice_commands = collect_git_spice(repo_root, args.timeout)
    commands.extend(git_commands + remote_commands + worktree_commands + spice_commands)

    repo_key = infer_repo_key(repo_root, remotes)
    github, gh_commands = collect_github(repo_root, args.pr, args.gh and not args.no_gh, args.timeout)
    commands.extend(gh_commands)

    detections = collect_local_detections(args, repo_root, git, worktrees, github)
    initial_project_id = infer_project_id(args.project_id, args.jira_key, args.pr, detections)
    state, state_detections, state_blockers = collect_state(args, repo_key, initial_project_id)
    merge_detections(detections, state_detections)
    project_id = infer_project_id(args.project_id, args.jira_key, args.pr, detections)

    active_hints = {
        "repo_root": str(repo_root),
        "repo_key": repo_key,
        "worktree_path": str(repo_root),
        "branch": git.get("branch"),
        "jira_keys": sorted(detections["jira_keys"]),
        "project_id": project_id,
        "pr": github.get("pr") or normalize_pr_hint(args.pr),
        "state_paths": state.get("paths_attempted", []),
    }
    blockers = build_blockers(github, state_blockers)
    pending_sync = build_pending_sync(detections, github, state)

    packet = {
        "kind": "opencode_project_workflow_packet",
        "fatal": False,
        "generated_at": timestamp(),
        "repo_input": str(repo_input),
        "repo_root": str(repo_root),
        "repo_key": repo_key,
        "inputs": input_summary(args),
        "active_hints": active_hints,
        "detections": finalize_detections(detections),
        "observed": {
            "git": git,
            "remotes": remotes,
            "worktrees": worktrees,
            "git_spice": git_spice,
            "github": github,
            "jira": {
                "inspected": False,
                "reason": "live Jira lookup omitted; helper performs key detection only",
                "detected_keys": sorted(detections["jira_keys"]),
            },
            "state": state,
        },
        "pending_sync": pending_sync,
        "blockers": blockers,
        "command_trace": command_trace(commands),
        "notes": read_only_notes(),
    }
    if args.pivot:
        packet["pivot_context"] = build_pivot_context(active_hints, packet["observed"], pending_sync, blockers)
    return packet


def collect_git(root: Path, timeout: int) -> tuple[dict[str, Any], list[CommandResult]]:
    specs = {
        "branch": ["git", "branch", "--show-current"],
        "head": ["git", "rev-parse", "--short", "HEAD"],
        "upstream": ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        "status": ["git", "status", "--porcelain=v1"],
    }
    results = {name: run_command(command, timeout, cwd=str(root)) for name, command in specs.items()}
    status_lines = split_lines(results["status"].stdout) if results["status"].exit_code == 0 else []
    return (
        {
            "inside_work_tree": True,
            "branch": clean_stdout(results["branch"]),
            "head": clean_stdout(results["head"]),
            "upstream": clean_stdout(results["upstream"]) if results["upstream"].exit_code == 0 else None,
            "dirty": bool(status_lines),
            "dirty_entries": len(status_lines),
            "untracked_entries": sum(1 for line in status_lines if line.startswith("??")),
        },
        list(results.values()),
    )


def collect_remotes(root: Path, timeout: int) -> tuple[list[dict[str, str]], list[CommandResult]]:
    result = run_command(["git", "remote", "-v"], timeout, cwd=str(root))
    remotes: list[dict[str, str]] = []
    if result.exit_code == 0:
        for line in split_lines(result.stdout):
            name, _, rest = line.partition("\t")
            url, _, kind = rest.partition(" ")
            if name and url:
                remotes.append({"name": name, "url": url, "kind": kind.strip("()")})
    return remotes, [result]


def collect_worktrees(root: Path, timeout: int) -> tuple[list[dict[str, Any]], list[CommandResult]]:
    result = run_command(["git", "worktree", "list", "--porcelain"], timeout, cwd=str(root))
    if result.exit_code != 0:
        return [], [result]
    return parse_worktree_porcelain(result.stdout), [result]


def collect_git_spice(root: Path, timeout: int) -> tuple[dict[str, Any], list[CommandResult]]:
    executable = shutil.which("gs") or shutil.which("git-spice")
    if executable is None:
        return {"available": False, "reason": "git-spice/gs executable not found"}, []
    candidates = [
        [executable, "log", "long"],
        [executable, "log", "short"],
        [executable, "log", "long", "--no-interactive"],
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
            return {"available": True, "command": shlex.join(command), "summary": git_spice_summary(result)[:30]}, results
    return {"available": True, "error": "git-spice found, but known read-only log commands failed"}, results


def collect_github(root: Path, pr_hint: str | None, use_gh: bool, timeout: int) -> tuple[dict[str, Any], list[CommandResult]]:
    if not use_gh:
        return {
            "enabled": False,
            "inspected": False,
            "reason": "skipped by default; pass --gh to opt in after gh auth status is acceptable",
            "pr_hint": normalize_pr_hint(pr_hint),
        }, []
    if shutil.which("gh") is None:
        return {
            "enabled": True,
            "available": False,
            "inspected": False,
            "reason": "gh executable not found",
            "pr_hint": normalize_pr_hint(pr_hint),
        }, []

    auth = run_command(["gh", "auth", "status"], timeout, cwd=str(root))
    if auth.exit_code != 0:
        return {
            "enabled": True,
            "available": True,
            "auth_checked": True,
            "inspected": False,
            "reason": "gh auth status failed; helper did not run gh auth login or any PR read",
            "pr_hint": normalize_pr_hint(pr_hint),
        }, [auth]

    command = ["gh", "pr", "view"]
    if pr_hint:
        command.append(pr_hint)
    command.extend(["--json", "number,url,title,body,state,baseRefName,headRefName,isDraft"])
    view = run_command(command, timeout, cwd=str(root))
    if view.exit_code != 0:
        return {
            "enabled": True,
            "available": True,
            "auth_checked": True,
            "inspected": False,
            "reason": "gh PR view failed; no auth flow was launched",
            "pr_hint": normalize_pr_hint(pr_hint),
        }, [auth, view]
    try:
        pr = json.loads(view.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {
            "enabled": True,
            "available": True,
            "auth_checked": True,
            "inspected": False,
            "reason": f"gh PR JSON parse failed: {exc}",
            "pr_hint": normalize_pr_hint(pr_hint),
        }, [auth, view]
    return {"enabled": True, "available": True, "auth_checked": True, "inspected": True, "pr": sanitize_state(pr)}, [auth, view]


def collect_state(args: argparse.Namespace, repo_key: str, project_id: str | None) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    detections = build_detection_index()
    blockers: list[str] = []
    explicit_state_file = Path(args.state_file).expanduser() if args.state_file else None
    state_dir = Path(args.state_dir).expanduser() if args.state_dir else DEFAULT_STATE_ROOT / repo_key
    paths: list[Path] = []
    listed_candidates: list[str] = []

    if explicit_state_file:
        paths.append(explicit_state_file)
    elif project_id:
        paths.append(state_dir / f"{safe_filename(project_id)}.json")
    elif args.state_dir:
        if state_dir.is_dir():
            candidates = sorted(state_dir.glob("*.json"))
            listed_candidates = [str(path) for path in candidates[:MAX_STATE_LIST_ITEMS]]
            paths.extend(candidates[:MAX_STATE_LIST_ITEMS])
            if len(candidates) > MAX_STATE_LIST_ITEMS:
                blockers.append(f"state dir has {len(candidates)} JSON files; inspected first {MAX_STATE_LIST_ITEMS} sorted paths only")
        else:
            blockers.append(f"state dir not found; read needed: {state_dir}")

    files: list[dict[str, Any]] = []
    pending_items: list[dict[str, Any]] = []
    for path in unique_paths(paths):
        record: dict[str, Any] = {"path": str(path), "exists": path.exists()}
        if not path.exists():
            if explicit_state_file or args.state_dir:
                blockers.append(f"state file not found; read needed: {path}")
            files.append(record)
            continue
        if not path.is_file():
            record["error"] = "not a file"
            blockers.append(f"state path is not a file; read needed: {path}")
            files.append(record)
            continue
        try:
            data = json.loads(path.read_text())
        except OSError as exc:
            record["error"] = f"read failed: {exc}"
            blockers.append(f"state file read failed: {path}: {exc}")
            files.append(record)
            continue
        except json.JSONDecodeError as exc:
            record["error"] = f"JSON parse failed: {exc}"
            blockers.append(f"state file is not valid JSON; inspect/fix before trusting it: {path}: {exc}")
            files.append(record)
            continue
        add_jira_sources_from_value(detections, data, f"state:{path}")
        pending_items.extend(extract_pending_items(data, str(path)))
        record["content"] = sanitize_state(data)
        files.append(record)

    return (
        {
            "inspected": bool(paths),
            "state_dir": str(state_dir),
            "paths_attempted": [str(path) for path in unique_paths(paths)],
            "listed_candidates": listed_candidates,
            "files": files,
            "pending_items": pending_items,
        },
        detections,
        blockers,
    )


def collect_local_detections(args: argparse.Namespace, root: Path, git: dict[str, Any], worktrees: list[dict[str, Any]], github: dict[str, Any]) -> dict[str, Any]:
    detections = build_detection_index()
    add_jira_source(detections, args.jira_key, "input:--jira-key")
    add_jira_source(detections, str(root), "worktree:path")
    add_jira_source(detections, git.get("branch"), "git:branch")
    add_jira_source(detections, args.project_id, "input:--project-id")
    add_jira_source(detections, args.pr, "input:--pr")
    for worktree in worktrees:
        add_jira_source(detections, worktree.get("path"), "git:worktree:path")
        add_jira_source(detections, worktree.get("branch"), "git:worktree:branch")
    pr = github.get("pr") if isinstance(github.get("pr"), dict) else None
    if pr:
        add_jira_source(detections, pr.get("title"), "github:pr:title")
        add_jira_source(detections, pr.get("body"), "github:pr:body")
        add_jira_source(detections, pr.get("headRefName"), "github:pr:head")
    return detections


def build_pending_sync(detections: dict[str, Any], github: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    jira_keys = sorted(detections["jira_keys"])
    pr = github.get("pr") if isinstance(github.get("pr"), dict) else None

    for item in state.get("pending_items", []):
        suggestions.extend(normalize_state_pending_sync(item))

    if pr and jira_keys:
        pr_text = f"{pr.get('title') or ''}\n{pr.get('body') or ''}"
        pr_keys = set(find_jira_keys(pr_text))
        missing = [key for key in jira_keys if key not in pr_keys]
        if missing:
            suggestions.append(
                proposed_sync(
                    f"PR #{pr.get('number')}",
                    f"Add Jira key(s) {', '.join(missing)} to the PR title/body if this mapping is correct",
                    "pr-description-chain-writer",
                    "Jira key detected from local context but not from PR title/body",
                    kind="PR body refresh",
                )
            )

    return number_pending_sync(suggestions)


def build_pivot_context(
    active_hints: dict[str, Any], observed: dict[str, Any], pending_sync: list[dict[str, Any]], blockers: list[str]
) -> dict[str, Any]:
    git = observed.get("git", {}) if isinstance(observed.get("git"), dict) else {}
    github = observed.get("github", {}) if isinstance(observed.get("github"), dict) else {}
    state = observed.get("state", {}) if isinstance(observed.get("state"), dict) else {}
    worktrees = observed.get("worktrees", []) if isinstance(observed.get("worktrees"), list) else []
    jira_keys = active_hints.get("jira_keys") or []
    pr = github.get("pr") if isinstance(github.get("pr"), dict) else None

    return {
        "freeze_writes": True,
        "detected_pivot_hints": detect_pivot_hints(active_hints, git, github, state, pending_sync, blockers),
        "observed_state_summary": {
            "repo_key": active_hints.get("repo_key"),
            "branch": active_hints.get("branch") or git.get("branch"),
            "jira_keys": jira_keys,
            "pr": pivot_pr_summary(pr, active_hints.get("pr")),
            "dirty_worktree": git.get("dirty"),
            "worktree_count": len(worktrees),
            "state_files_read": sum(1 for file in state.get("files", []) if file.get("exists") and not file.get("error")),
            "pending_sync_items": len(pending_sync),
            "blocker_count": len(blockers),
        },
        "proposed_reconciliation_queue": [],
        "queue_placeholder": "helper snapshot only; project-workflow classifies pivots and builds Phase 3 action records after explicit user confirmation",
    }


def detect_pivot_hints(
    active_hints: dict[str, Any],
    git: dict[str, Any],
    github: dict[str, Any],
    state: dict[str, Any],
    pending_sync: list[dict[str, Any]],
    blockers: list[str],
) -> list[str]:
    hints: list[str] = []
    jira_keys = active_hints.get("jira_keys") or []
    if len(jira_keys) > 1:
        hints.append("multiple Jira keys detected; classify split/merge/shared-ticket mapping before writes")
    if git.get("dirty"):
        hints.append("dirty worktree detected; confirm scope before branch/worktree/topology actions")
    if pending_sync:
        hints.append(f"{len(pending_sync)} pending sync item(s) detected; classify stale sync vs pivot reconciliation")
    if state.get("pending_items"):
        hints.append("local state has pending items; reconcile against source systems before trusting state")
    if blockers:
        hints.append("missing context blockers present; resolve or accept evidence limits before writes")

    pr = github.get("pr") if isinstance(github.get("pr"), dict) else None
    if pr and jira_keys:
        pr_text = f"{pr.get('title') or ''}\n{pr.get('body') or ''}"
        pr_keys = set(find_jira_keys(pr_text))
        if any(key not in pr_keys for key in jira_keys):
            hints.append("PR text does not include every locally detected Jira key")
    pr_hint = active_hints.get("pr")
    if not pr and isinstance(pr_hint, dict) and pr_hint.get("input") and not github.get("inspected"):
        hints.append("PR hint provided but GitHub PR was not inspected")

    return hints


def pivot_pr_summary(pr: dict[str, Any] | None, pr_hint: Any) -> dict[str, Any] | str | None:
    if pr:
        return {"number": pr.get("number"), "state": pr.get("state"), "url": pr.get("url")}
    if pr_hint:
        return pr_hint
    return None


def normalize_state_pending_sync(item: dict[str, Any]) -> list[dict[str, Any]]:
    source = f"state pending item at {item.get('source')}"
    suggestions: list[dict[str, Any]] = []
    for raw in state_pending_records(item.get("item")):
        normalized = normalize_pending_sync_record(raw, source)
        if normalized:
            suggestions.append(normalized)
    return suggestions


def state_pending_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        records: list[dict[str, Any]] = []
        for item in value[:MAX_STATE_LIST_ITEMS]:
            records.extend(state_pending_records(item))
        return records
    if isinstance(value, dict):
        return [value]
    return []


def normalize_pending_sync_record(raw: dict[str, Any], fallback_reason: str) -> dict[str, Any] | None:
    kind = normalize_pending_sync_kind(raw.get("kind"))
    target = non_empty_string(raw.get("target"))
    proposal = non_empty_string(raw.get("proposed_action")) or non_empty_string(raw.get("proposal"))
    if not kind or not target or not proposal or not is_concrete_proposed_action(proposal):
        return None

    reason = non_empty_string(raw.get("reason")) or fallback_reason
    delegate_skill = (
        non_empty_string(raw.get("delegate_skill"))
        or non_empty_string(raw.get("owner_skill"))
        or DELEGATE_SKILL_BY_KIND[kind]
    )
    status = non_empty_string(raw.get("status")) or "proposed"
    return proposed_sync(target, proposal, delegate_skill, reason, kind=kind, details=raw.get("details"), status=status)


def normalize_pending_sync_kind(kind: Any) -> str | None:
    if kind is None:
        return None
    key = re.sub(r"[\s_-]+", " ", str(kind).strip().lower())
    return ALLOWED_PENDING_SYNC_KINDS.get(key)


def non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def is_concrete_proposed_action(proposal: str) -> bool:
    return not VAGUE_PROPOSED_ACTION_RE.search(proposal)


def proposed_sync(
    target: str,
    proposal: str,
    owner: str,
    reason: str,
    *,
    kind: str,
    details: Any = None,
    status: str = "proposed",
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": kind,
        "status": status,
        "executed": False,
        "target": target,
        "proposal": proposal,
        "proposed_action": proposal,
        "owner_skill": owner,
        "delegate_skill": owner,
        "confirmation_required": True,
        "requires_confirmation": True,
        "reason": reason,
    }
    if details is not None:
        item["details"] = details
    return item


def number_pending_sync(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, item in enumerate(items, start=1):
        item.setdefault("id", str(index))
    return items


def build_blockers(github: dict[str, Any], state_blockers: list[str]) -> list[str]:
    blockers = list(state_blockers)
    if github.get("enabled") and not github.get("available", True):
        blockers.append("gh executable not found; read needed: install/use gh or provide PR title/body in local state")
    if github.get("enabled") and github.get("auth_checked") and not github.get("inspected"):
        blockers.append("GitHub not inspected after gh auth status/read failure; helper did not run gh auth login")
    if not github.get("enabled") and (github.get("pr_hint") or {}).get("input"):
        blockers.append("PR hint was provided but gh reads are disabled; read needed: gh auth status, then rerun with --gh")
    return blockers


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
        else:
            current[key] = value
    if current:
        entries.append(current)
    return entries


def infer_repo_key(root: Path, remotes: list[dict[str, str]]) -> str:
    origin_urls = [remote["url"] for remote in remotes if remote.get("name") == "origin" and remote.get("kind") == "fetch"]
    urls = origin_urls or [remote["url"] for remote in remotes if remote.get("kind") == "fetch"]
    for url in urls:
        repo_name = url.rstrip("/").split(":")[-1].split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        if repo_name:
            return safe_filename(repo_name)
    return safe_filename(root.name)


def infer_project_id(explicit_project_id: str | None, explicit_jira_key: str | None, pr_hint: str | None, detections: dict[str, Any]) -> str | None:
    if explicit_project_id:
        return safe_filename(explicit_project_id)
    explicit_keys = find_jira_keys(explicit_jira_key or "")
    if explicit_keys:
        return explicit_keys[0]
    if detections["jira_keys"]:
        return sorted(detections["jira_keys"])[0]
    pr = normalize_pr_hint(pr_hint)
    if pr and pr.get("number"):
        return f"pr-{pr['number']}"
    return None


def normalize_pr_hint(pr_hint: str | None) -> dict[str, Any] | None:
    if not pr_hint:
        return None
    if pr_hint.isdigit():
        return {"input": pr_hint, "number": int(pr_hint), "kind": "number"}
    match = PR_URL_RE.match(pr_hint)
    if match:
        return {"input": pr_hint, "number": int(match.group(3)), "repo": f"{match.group(1)}/{match.group(2)}", "kind": "url"}
    return {"input": pr_hint, "kind": "unknown"}


def build_detection_index() -> dict[str, Any]:
    return {"jira_keys": set(), "sources": {}}


def add_jira_source(detections: dict[str, Any], value: Any, source: str) -> None:
    if value is None:
        return
    for key in find_jira_keys(str(value)):
        detections["jira_keys"].add(key)
        detections["sources"].setdefault(key, set()).add(source)


def add_jira_sources_from_value(detections: dict[str, Any], value: Any, source: str, path: str = "$", depth: int = 0) -> None:
    if depth > MAX_STATE_DEPTH:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            add_jira_source(detections, key, f"{source}:{path}.{key}")
            add_jira_sources_from_value(detections, item, source, f"{path}.{key}", depth + 1)
    elif isinstance(value, list):
        for index, item in enumerate(value[:MAX_STATE_LIST_ITEMS]):
            add_jira_sources_from_value(detections, item, source, f"{path}[{index}]", depth + 1)
    elif isinstance(value, (str, int, float)):
        add_jira_source(detections, value, f"{source}:{path}")


def merge_detections(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in source["jira_keys"]:
        target["jira_keys"].add(key)
        target["sources"].setdefault(key, set()).update(source["sources"].get(key, set()))


def finalize_detections(detections: dict[str, Any]) -> dict[str, Any]:
    return {
        "jira_keys": [
            {"key": key, "sources": sorted(detections["sources"].get(key, []))}
            for key in sorted(detections["jira_keys"])
        ]
    }


def find_jira_keys(text: str) -> list[str]:
    return sorted({match.group(0).upper() for match in JIRA_KEY_RE.finditer(text or "")})


def extract_pending_items(value: Any, source: str, path: str = "$", depth: int = 0) -> list[dict[str, Any]]:
    if depth > MAX_STATE_DEPTH:
        return []
    items: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if re.search(r"pending|proposed|sync_queue|pending_sync", str(key), re.IGNORECASE):
                items.append({"source": f"{source}:{child_path}", "item": sanitize_state(item)})
            items.extend(extract_pending_items(item, source, child_path, depth + 1))
    elif isinstance(value, list):
        for index, item in enumerate(value[:MAX_STATE_LIST_ITEMS]):
            items.extend(extract_pending_items(item, source, f"{path}[{index}]", depth + 1))
    return items


def sanitize_state(value: Any, depth: int = 0) -> Any:
    if depth > MAX_STATE_DEPTH:
        return "<max-depth>"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            key_text = str(key)
            sanitized[key_text] = "<redacted>" if SECRET_KEY_RE.search(key_text) else sanitize_state(item, depth + 1)
        return sanitized
    if isinstance(value, list):
        items = [sanitize_state(item, depth + 1) for item in value[:MAX_STATE_LIST_ITEMS]]
        if len(value) > MAX_STATE_LIST_ITEMS:
            items.append(f"<{len(value) - MAX_STATE_LIST_ITEMS} more items>")
        return items
    if isinstance(value, str):
        return redact_text(truncate_text(value, MAX_STATE_STRING_CHARS))
    return value


def command_trace(results: list[CommandResult]) -> list[dict[str, Any]]:
    return [result.as_dict(include_stdout=bool(result.timed_out or result.exit_code not in (0, None))) for result in results]


def input_summary(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "repo": args.repo,
        "jira_key": args.jira_key,
        "project_id": args.project_id,
        "pr": args.pr,
        "state_file": args.state_file,
        "state_dir": args.state_dir,
        "gh_enabled": bool(args.gh and not args.no_gh),
        "pivot": bool(args.pivot),
    }


def render_markdown(packet: dict[str, Any]) -> str:
    lines = ["# OpenCode Project Workflow Packet", ""]
    lines.extend(
        [
            f"- generated: `{packet.get('generated_at')}`",
            f"- mode: read-only; pending sync items are `proposed` and not executed",
        ]
    )
    if packet.get("fatal"):
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in packet.get("blockers", []))
        if packet.get("pivot_context"):
            lines.extend(render_pivot_context(packet["pivot_context"]))
        lines.extend(render_command_trace(packet.get("command_trace", [])))
        return "\n".join(lines)

    active = packet["active_hints"]
    observed = packet["observed"]
    git = observed["git"]
    github = observed["github"]
    state = observed["state"]
    lines.extend(
        [
            f"- repo: `{packet.get('repo_root')}` key=`{packet.get('repo_key')}`",
            f"- branch: `{git.get('branch')}` upstream=`{git.get('upstream')}` head=`{git.get('head')}` dirty={git.get('dirty')} entries={git.get('dirty_entries')}",
            f"- project id: `{active.get('project_id') or 'none inferred'}`",
            f"- Jira keys: {', '.join(active.get('jira_keys') or []) or 'none detected'}",
            f"- GitHub: {github_summary(github)}",
            f"- Jira: live lookup not inspected; key detection only",
            f"- state: {state_summary(state)}",
            "",
            "## Detected Jira keys",
        ]
    )
    detections = packet.get("detections", {}).get("jira_keys", [])
    if detections:
        lines.extend(["| Key | Sources |", "|---|---|"])
        for item in detections:
            lines.append(f"| `{item['key']}` | {', '.join(f'`{source}`' for source in item.get('sources', []))} |")
    else:
        lines.append("- none detected")

    lines.extend(["", "## Observed state"])
    lines.append(f"- worktrees: {len(observed.get('worktrees', []))} from `git worktree list --porcelain`")
    spice = observed.get("git_spice", {})
    if spice.get("available") and spice.get("summary"):
        lines.append(f"- git-spice: available via `{spice.get('command')}`; {len(spice.get('summary', []))} summary lines")
    elif spice.get("available"):
        lines.append(f"- git-spice: available but not summarized ({spice.get('error') or 'no output'})")
    else:
        lines.append(f"- git-spice: {spice.get('reason')}")
    pr = github.get("pr") if isinstance(github.get("pr"), dict) else None
    if pr:
        lines.append(f"- PR: #{pr.get('number')} `{pr.get('title')}` state={pr.get('state')} url={pr.get('url')}")
    if state.get("files"):
        for file in state["files"]:
            status = "ok" if file.get("exists") and not file.get("error") else file.get("error") or "missing"
            lines.append(f"- state file: `{file.get('path')}` {status}")
    else:
        lines.append("- state file: none inspected")

    if packet.get("pivot_context"):
        lines.extend(render_pivot_context(packet["pivot_context"]))

    lines.extend(["", "## Pending sync queue"])
    if packet.get("pending_sync"):
        lines.extend(
            [
                "| id | target | kind | reason | proposed_action | delegate_skill | requires_confirmation | status |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for index, item in enumerate(packet["pending_sync"], start=1):
            item_id = item.get("id") or str(index)
            kind = item.get("kind") or "unknown"
            proposed_action = item.get("proposed_action") or item["proposal"]
            delegate_skill = item.get("delegate_skill") or item["owner_skill"]
            requires_confirmation = item.get("requires_confirmation", item.get("confirmation_required", True))
            lines.append(
                f"| {escape_table(item_id)} | {escape_table(item['target'])} | {escape_table(kind)} | "
                f"{escape_table(item['reason'])} | {escape_table(proposed_action)} | `{delegate_skill}` | "
                f"{str(requires_confirmation).lower()} | `{item['status']}` |"
            )
    else:
        lines.append("Pending sync queue: empty")

    lines.extend(["", "## Blockers / missing context"])
    if packet.get("blockers"):
        lines.extend(f"- {item}" for item in packet["blockers"])
    else:
        lines.append("- none detected by read-only packet")
    lines.extend(render_command_trace(packet.get("command_trace", [])))
    return "\n".join(lines)


def render_pivot_context(context: dict[str, Any]) -> list[str]:
    lines = ["", "## Pivot context", f"- freeze_writes: {str(context.get('freeze_writes')).lower()}"]
    hints = context.get("detected_pivot_hints") or []
    if hints:
        lines.append("- detected pivot hints:")
        lines.extend(f"  - {hint}" for hint in hints)
    else:
        lines.append("- detected pivot hints: none from helper; use user-provided pivot details")

    summary = context.get("observed_state_summary") or {}
    lines.append("- observed state summary:")
    for key, value in summary.items():
        lines.append(f"  - {key}: `{escape_inline(json.dumps(value, sort_keys=True))}`")
    queue = context.get("proposed_reconciliation_queue") or []
    lines.append(f"- proposed reconciliation queue: {len(queue)} item(s); {context.get('queue_placeholder')}")
    return lines


def render_command_trace(trace: list[dict[str, Any]]) -> list[str]:
    lines = ["", "## Command trace"]
    if not trace:
        lines.append("- no read-only commands were run")
        return lines
    for entry in trace:
        line = f"- `{entry['command']}` -> exit={entry.get('exit_code')} timed_out={entry.get('timed_out')}"
        if entry.get("stderr"):
            line += f" stderr=`{escape_inline(entry['stderr'])}`"
        if entry.get("stdout"):
            line += f" stdout=`{escape_inline(entry['stdout'])}`"
        lines.append(line)
    return lines


def github_summary(github: dict[str, Any]) -> str:
    if github.get("inspected") and isinstance(github.get("pr"), dict):
        pr = github["pr"]
        return f"PR #{pr.get('number')} inspected read-only"
    return github.get("reason") or "not inspected"


def state_summary(state: dict[str, Any]) -> str:
    if state.get("files"):
        ok = sum(1 for file in state["files"] if file.get("exists") and not file.get("error"))
        return f"{ok}/{len(state['files'])} file(s) read from `{state.get('state_dir')}`"
    if state.get("paths_attempted"):
        return f"no state file found at `{state['paths_attempted'][0]}`"
    return f"not inspected; default dir `{state.get('state_dir')}`"


def read_only_notes() -> list[str]:
    return [
        "read-only packet; no Jira, GitHub, branch, worktree, commit, comment, label, status, auth, or external-state writes were attempted",
        "Jira live lookup is omitted; Jira coverage is key detection from local/PR/state hints only",
        "pending_sync entries are concrete allowed action proposals only and require explicit human confirmation plus owner-skill delegation before any write",
    ]


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def split_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def git_spice_summary(result: CommandResult) -> list[str]:
    text = result.stdout.strip() or result.stderr.strip()
    return [line for line in split_lines(text) if not line.startswith("WRN ")]


def clean_stdout(result: CommandResult) -> str | None:
    text = result.stdout.strip()
    return text or None


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return cleaned or "project"


def timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def truncate_text(text: str, limit: int = MAX_EXCERPT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"... <truncated {len(text) - limit} chars>"


def redact_text(text: str) -> str:
    return SECRET_VALUE_RE.sub("<redacted>", text)


def escape_inline(text: str) -> str:
    return str(text).replace("`", "'").replace("\n", " ")


def escape_table(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", "<br>")


if __name__ == "__main__":
    raise SystemExit(main())
