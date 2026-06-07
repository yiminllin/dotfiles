#!/usr/bin/env python3
"""Read-only FlightSystems PR stack packet, draft, and PR-description audit helper."""

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


DEFAULT_REPO = "ZiplineTeam/FlightSystems"
TEMPLATE_SECTIONS = [
    "Reason for Change",
    "Description of Change",
    "Criticality of Change",
    "Verification",
    "Release Notes",
]
PR_FIELDS = [
    "number",
    "url",
    "title",
    "body",
    "state",
    "baseRefName",
    "headRefName",
    "isDraft",
    "author",
    "statusCheckRollup",
]
PR_LIST_FIELDS = ["number", "url", "title", "state", "baseRefName", "headRefName"]
DEFAULT_REASON = "TODO: Describe the bug or feature."
DEFAULT_DESCRIPTION = "TODO: Describe what changed and how it was implemented."
DEFAULT_VERIFICATION = "TODO: Add exact verification commands, links, logs, or artifacts."
DEFAULT_BASE_BRANCHES = ("develop", "main", "master")

PR_URL_RE = re.compile(r"^https?://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)/?$")
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
CHECKBOX_RE = re.compile(r"-\s*\[(?P<mark>[ xX])\]\s*(?P<label>.+)")
FSW_RE = re.compile(r"\bFSW-\d+\b", re.IGNORECASE)
JIRA_LINK_RE = re.compile(r"https?://[^\s)]+(?:jira|atlassian|browse/|FSW-)\S*", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s)>'\"]+")
S3_RE = re.compile(r"\bs3://[^\s)>'\"]+", re.IGNORECASE)
MARKDOWN_S3_LINK_RE = re.compile(r"\[S3\]\(\s*(?P<url>s3://[^\s)]+)\s*\)", re.IGNORECASE)
VERIFICATION_PLACEHOLDER_RE = re.compile(r"\bTODO\b|Empty query results|add exact verification|how have you proven|template placeholder", re.IGNORECASE)
PHOENIX_LOG_RE = re.compile(r"(?:^|[\s`'\"])(?P<path>(?:/[^\s`'\"]*)?(?:phoenix|hil|sil)[^\s`'\"]*\.(?:log|txt|jsonl?))", re.IGNORECASE)
ZML_PATH_RE = re.compile(r"(?:^|[\s`'\"])(?P<path>[^\s`'\"]*\.zml(?:\.[^\s`'\"]+)?)", re.IGNORECASE)
OUTPUT_PATH_RE = re.compile(r"(?:^|[\s`'\"])(?P<path>(?:/tmp/|/var/|~/|\./|bazel-)[^\s`'\"]*(?:out|output|outputs|artifacts?|plots?|csv|logs?)[^\s`'\"]*)", re.IGNORECASE)
BAZEL_RE = re.compile(r"(?:^|[`$>\s])(?P<cmd>bazel\s+(?:test|run|build|query|cquery|aquery)\b[^`\n]*)", re.IGNORECASE)
COMMAND_LINE_RE = re.compile(r"^\s*(?:\$\s*)?(?P<cmd>(?:python3?|scripts/[^\s]+|\./[^\s]+|fish\s+[^\n]+)\s+[^\n]+)", re.IGNORECASE)
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass
class CommandResult:
    command: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    def as_dict(self, include_stdout: bool = True) -> dict[str, Any]:
        stdout = self.stdout.strip()
        return {
            "command": shlex.join(self.command),
            "exit_code": self.exit_code,
            "stdout": stdout if include_stdout else None,
            "stdout_chars": len(stdout),
            "stderr": self.stderr.strip(),
            "timed_out": self.timed_out,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build read-only FlightSystems PR stack packets, local drafts, and PR-description audits.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            f"""
            Examples:
              opencode_pr_stack_packet.py packet 54318 54351 --repo {DEFAULT_REPO} --format markdown
              opencode_pr_stack_packet.py packet --from-git-spice --format markdown
              opencode_pr_stack_packet.py draft branch-a branch-b --current branch-a --criticality todo
              opencode_pr_stack_packet.py draft --from-git-spice --criticality todo
              opencode_pr_stack_packet.py audit 54318 54351 --repo {DEFAULT_REPO}
              opencode_pr_stack_packet.py audit --body-file /tmp/pr.md --title "[FSW-12345] [Phoenix] Foo Bar"
              opencode_pr_stack_packet.py packet --no-gh --body-file /tmp/pr.md --title "[FSW-12345] [Phoenix] Foo Bar"

            This helper is read-only: packet/audit run only git, git-spice/gs, and gh inspection commands;
            draft writes nothing unless the caller redirects stdout.
            It never edits PRs, posts comments, logs in, retargets, submits, or writes git state.
            """
        ).strip(),
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    packet = subparsers.add_parser("packet", help="collect PR/stack context packet")
    add_common_args(packet)
    packet.add_argument("targets", nargs="*", help="PR numbers or GitHub PR URLs; omit for current branch PR")
    packet.add_argument("--from-git-spice", action="store_true", help="collect a local stack from git-spice log long without requiring gh")
    packet.add_argument("--base", help="base branch for the first local stack entry when git-spice output does not expose one")
    packet.add_argument("--format", choices=("json", "markdown"), default="json", help="packet output format")

    draft = subparsers.add_parser("draft", help="generate local markdown PR body drafts without mutating GitHub")
    draft.add_argument("branches", nargs="*", help="branch names/labels in stack order; used as PR Tree placeholders")
    draft.add_argument("--from-git-spice", action="store_true", help="derive branch placeholders and local diff context from git-spice log long")
    draft.add_argument("--current", help="branch/label to mark as current; omit to generate one draft per branch")
    draft.add_argument("--base", help="base branch for the first local stack entry when git-spice output does not expose one")
    draft.add_argument("--timeout", type=int, default=20, help="per-command timeout in seconds for --from-git-spice, default: 20")
    draft.add_argument("--format", choices=("markdown",), default="markdown", help="draft output format, default: markdown")
    draft.add_argument("--criticality", choices=("L1", "L2", "L3", "todo"), default="todo", help="criticality checkbox selection, default: todo")
    draft.add_argument("--release-notes-required", action="store_true", help="check the Release Notes required checkbox")
    draft.add_argument("--reason", default=DEFAULT_REASON, help="Reason for Change draft text")
    draft.add_argument("--description", default=DEFAULT_DESCRIPTION, help="Description of Change draft text")
    draft.add_argument("--verification", default=DEFAULT_VERIFICATION, help="Verification draft text")

    audit = subparsers.add_parser("audit", help="audit PR body template/style without mutating GitHub")
    add_common_args(audit)
    audit.add_argument("targets", nargs="*", help="PR numbers or GitHub PR URLs; omit for current branch PR unless --body-file is set")
    audit.add_argument("--format", choices=("text", "json", "markdown"), default="text", help="audit output format")
    audit.add_argument("--fail-on", choices=("error", "warning"), help="return exit code 1 when findings meet this threshold")

    return parser.parse_args()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub repo, default: {DEFAULT_REPO}")
    parser.add_argument("--no-gh", action="store_true", help="skip live gh calls and use only local body files/git context")
    parser.add_argument("--timeout", type=int, default=20, help="per-command timeout in seconds, default: 20")
    parser.add_argument("--body-file", action="append", default=[], help="local PR body file to include/audit; may be repeated")
    parser.add_argument("--title", action="append", default=[], help="title for a local --body-file; may be repeated")
    parser.add_argument("--number", action="append", default=[], help="PR number for a local --body-file; may be repeated")


def run_command(command: list[str], timeout: int, cwd: str | None = None) -> CommandResult:
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return CommandResult(command, None, stdout, stderr or f"timed out after {timeout}s", timed_out=True)
    return CommandResult(command, result.returncode, result.stdout, result.stderr)


def parse_json_result(result: CommandResult) -> Any:
    if result.exit_code != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "command failed")
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to parse JSON stdout: {exc}") from exc


def command_lines(results: list[CommandResult]) -> list[dict[str, Any]]:
    records = []
    for result in results:
        include_stdout = bool(result.timed_out or result.exit_code not in (0, None))
        records.append(result.as_dict(include_stdout=include_stdout))
    return records


def gh_error_message(result: CommandResult) -> str:
    if result.timed_out:
        return f"gh command timed out: {shlex.join(result.command)}"
    detail = result.stderr.strip() or result.stdout.strip() or "unknown gh failure"
    return f"gh command failed ({result.exit_code}): {shlex.join(result.command)}; {detail}. This helper will not start gh auth login."


def normalize_target(raw: str | None, default_repo: str) -> dict[str, Any]:
    if raw is None:
        return {"kind": "current-branch", "input": None, "repo": default_repo, "number": None, "display": "current branch"}
    match = PR_URL_RE.match(raw)
    if match:
        repo = f"{match.group(1)}/{match.group(2)}"
        number = int(match.group(3))
        return {"kind": "pr-url", "input": raw, "repo": repo, "number": number, "display": f"{repo}#{number}"}
    if raw.isdigit():
        return {"kind": "pr-number", "input": raw, "repo": default_repo, "number": int(raw), "display": f"{default_repo}#{raw}"}
    raise ValueError(f"target must be a PR number or GitHub PR URL: {raw}")


def gh_selector(target: dict[str, Any]) -> list[str]:
    return [] if target["input"] is None else [str(target["input"])]


def collect_git_context(timeout: int) -> tuple[dict[str, Any], list[CommandResult]]:
    results: list[CommandResult] = []
    inside = run_command(["git", "rev-parse", "--is-inside-work-tree"], timeout)
    results.append(inside)
    if inside.exit_code != 0 or inside.stdout.strip() != "true":
        return {"inside_work_tree": False}, results

    top = run_command(["git", "rev-parse", "--show-toplevel"], timeout)
    branch = run_command(["git", "branch", "--show-current"], timeout)
    status = run_command(["git", "status", "--porcelain=v1"], timeout)
    results.extend([top, branch, status])
    status_lines = [line for line in status.stdout.splitlines() if line.strip()]
    return {
        "inside_work_tree": True,
        "root": top.stdout.strip() or None,
        "branch": branch.stdout.strip() or None,
        "dirty": bool(status_lines),
        "dirty_entries": len(status_lines),
    }, results


def collect_git_spice(timeout: int, inside_git: bool) -> tuple[dict[str, Any], list[CommandResult]]:
    if not inside_git:
        return {"available": False, "reason": "not inside a git worktree"}, []
    executable = shutil.which("gs") or shutil.which("git-spice")
    if executable is None:
        return {"available": False, "reason": "git-spice/gs executable not found"}, []

    candidates = [[executable, "log", "--no-interactive"], [executable, "log"], [executable, "stack", "log", "--no-interactive"], [executable, "stack", "log"]]
    results: list[CommandResult] = []
    for command in candidates:
        result = run_command(command, timeout)
        results.append(result)
        if result.exit_code == 0:
            return {"available": True, "command": shlex.join(command), "raw_order": command_output_text(result).strip()}, results
    return {
        "available": True,
        "error": "git-spice was found, but known read-only stack log commands failed",
        "attempts": [result.as_dict() for result in results],
    }, results


def collect_local_stack_from_git_spice(timeout: int, git_context: dict[str, Any], base_hint: str | None) -> tuple[dict[str, Any], list[CommandResult]]:
    if not git_context.get("inside_work_tree"):
        return {"available": False, "error": "not inside a git worktree", "entries": []}, []

    executable = shutil.which("git-spice") or shutil.which("gs")
    if executable is None:
        return {"available": False, "error": "git-spice/gs executable not found", "entries": []}, []

    commands: list[CommandResult] = []
    local_branches_result = run_command(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"], timeout)
    commands.append(local_branches_result)
    local_branches = [line.strip() for line in local_branches_result.stdout.splitlines() if line.strip()] if local_branches_result.exit_code == 0 else []
    if not local_branches:
        return {"available": True, "error": "no local branches were found to match against git-spice log long", "entries": []}, commands

    spice_log, spice_commands = run_git_spice_log_long(executable, timeout)
    commands.extend(spice_commands)
    if spice_log.exit_code != 0:
        return {
            "available": True,
            "error": "git-spice log long failed",
            "attempts": [result.as_dict() for result in spice_commands],
            "entries": [],
        }, commands

    raw_order = command_output_text(spice_log)
    parsed = parse_git_spice_log_long(raw_order, local_branches, git_context.get("branch"))
    branch_order = parsed["branches"]
    base_branch, base_command = resolve_local_stack_base(branch_order, local_branches, base_hint)
    if base_command is not None:
        commands.append(base_command)
    stack_branches = local_stack_branch_order(branch_order, base_branch)
    if not stack_branches:
        return {
            "available": True,
            "error": "could not parse stack branches from git-spice log long",
            "raw_order": raw_order.strip(),
            "parsed_order": branch_order,
            "entries": [],
        }, commands

    entries: list[dict[str, Any]] = []
    parent = base_branch
    for branch in stack_branches:
        entry, entry_commands = collect_local_stack_entry(branch, parent, timeout)
        commands.extend(entry_commands)
        entry["current"] = branch == git_context.get("branch") or branch in parsed["current_candidates"]
        entries.append(entry)
        parent = branch

    warnings = []
    if git_context.get("dirty"):
        warnings.append(
            "worktree is dirty; local stack packets and drafts use committed branch diffs only and do not include uncommitted changes"
        )

    return {
        "available": True,
        "source": "git-spice log long",
        "command": shlex.join(spice_log.command),
        "raw_order": raw_order.strip(),
        "parsed_order": branch_order,
        "stack_order": stack_branches,
        "base": base_branch,
        "current_branch": git_context.get("branch"),
        "current_in_stack": any(entry.get("current") for entry in entries),
        "dirty": bool(git_context.get("dirty")),
        "warnings": warnings,
        "entries": entries,
    }, commands


def run_git_spice_log_long(executable: str, timeout: int) -> tuple[CommandResult, list[CommandResult]]:
    candidates = [[executable, "log", "long", "--no-interactive"], [executable, "log", "long"]]
    results: list[CommandResult] = []
    for command in candidates:
        result = run_command(command, timeout)
        results.append(result)
        if result.exit_code == 0:
            return result, results
    return results[-1], results


def command_output_text(result: CommandResult) -> str:
    return result.stdout if result.stdout.strip() else result.stderr


def parse_git_spice_log_long(raw_output: str, local_branches: list[str], current_branch: str | None) -> dict[str, Any]:
    branches: list[str] = []
    current_candidates: set[str] = set()
    branches_by_length = sorted(local_branches, key=len, reverse=True)
    for raw_line in raw_output.splitlines():
        line = ANSI_RE.sub("", raw_line).rstrip()
        match = match_branch_in_line(line, branches_by_length)
        if not match:
            continue
        branch, start = match
        if branch not in branches:
            branches.append(branch)
        prefix = line[:start]
        if branch == current_branch or re.search(r"(?:^|\s|[│┃├└┌┬─])(?:\*|>|●|◉)\s*$", prefix):
            current_candidates.add(branch)
    return {"branches": branches, "current_candidates": sorted(current_candidates)}


def match_branch_in_line(line: str, branches_by_length: list[str]) -> tuple[str, int] | None:
    for branch in branches_by_length:
        pattern = rf"(?<![A-Za-z0-9._/-]){re.escape(branch)}(?![A-Za-z0-9._/-])"
        match = re.search(pattern, line)
        if match:
            return branch, match.start()
    return None


def resolve_local_stack_base(branch_order: list[str], local_branches: list[str], base_hint: str | None) -> tuple[str, CommandResult | None]:
    if base_hint:
        return base_hint, None
    if branch_order and branch_order[0] in DEFAULT_BASE_BRANCHES:
        return branch_order[0], None
    for branch in DEFAULT_BASE_BRANCHES:
        if branch in local_branches:
            return branch, None
    origin_head = run_command(["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], 5)
    if origin_head.exit_code == 0 and origin_head.stdout.strip().startswith("origin/"):
        return origin_head.stdout.strip().removeprefix("origin/"), origin_head
    return (branch_order[0] if branch_order else "HEAD"), origin_head


def local_stack_branch_order(branch_order: list[str], base_branch: str) -> list[str]:
    if base_branch in branch_order:
        base_index = branch_order.index(base_branch)
        if base_index == 0:
            return branch_order[1:]
        return list(reversed(branch_order[:base_index]))
    return branch_order


def collect_local_stack_entry(branch: str, parent: str, timeout: int) -> tuple[dict[str, Any], list[CommandResult]]:
    commits_result = run_command(["git", "log", "--reverse", "--format=%h%x09%s", f"{parent}..{branch}"], timeout)
    diff_stat_result = run_command(["git", "diff", "--stat", f"{parent}...{branch}"], timeout)
    changed_files_result = run_command(["git", "diff", "--name-status", f"{parent}...{branch}"], timeout)
    commands = [commits_result, diff_stat_result, changed_files_result]
    commits = parse_commit_summary(commits_result.stdout) if commits_result.exit_code == 0 else []
    changed_files = parse_changed_files(changed_files_result.stdout) if changed_files_result.exit_code == 0 else []
    return {
        "branch": branch,
        "parent": parent,
        "commit_range": f"{parent}..{branch}",
        "diff_range": f"{parent}...{branch}",
        "commits": commits,
        "diff_stat": diff_stat_result.stdout.strip() if diff_stat_result.exit_code == 0 else "",
        "changed_files": changed_files,
        "title_suggestion": suggest_title(commits, branch),
        "errors": local_entry_errors(commands),
    }, commands


def parse_commit_summary(stdout: str) -> list[dict[str, str]]:
    commits = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        commits.append({"hash": parts[0], "subject": parts[1] if len(parts) > 1 else ""})
    return commits


def parse_changed_files(stdout: str) -> list[dict[str, Any]]:
    files = []
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].startswith(("R", "C")):
            files.append({"status": parts[0], "path": parts[2], "old_path": parts[1]})
        elif len(parts) >= 2:
            files.append({"status": parts[0], "path": parts[1]})
    return files


def suggest_title(commits: list[dict[str, str]], branch: str) -> str:
    if commits and commits[0].get("subject"):
        return commits[0]["subject"]
    leaf = branch.rsplit("/", 1)[-1]
    words = re.sub(r"[-_]+", " ", leaf).strip()
    return words[:1].upper() + words[1:] if words else branch


def local_entry_errors(results: list[CommandResult]) -> list[dict[str, Any]]:
    return [result.as_dict() for result in results if result.exit_code not in (0, None) or result.timed_out]


def collect_branch_prs(repo: str, branch: str | None, timeout: int, no_gh: bool) -> tuple[list[dict[str, Any]], list[CommandResult], dict[str, Any] | None]:
    if no_gh or not branch:
        return [], [], None
    if shutil.which("gh") is None:
        return [], [], {"message": "gh executable not found on PATH"}
    command = ["gh", "pr", "list", "--repo", repo, "--head", branch, "--state", "all", "--json", ",".join(PR_LIST_FIELDS)]
    result = run_command(command, timeout)
    if result.exit_code != 0:
        return [], [result], {"message": gh_error_message(result)}
    try:
        raw = parse_json_result(result)
    except RuntimeError as exc:
        return [], [result], {"message": str(exc)}
    return [normalize_pr_summary(item) for item in raw if isinstance(item, dict)], [result], None


def collect_live_pr(target: dict[str, Any], timeout: int) -> tuple[dict[str, Any] | None, CommandResult, str | None]:
    command = ["gh", "pr", "view", *gh_selector(target), "--repo", target["repo"], "--json", ",".join(PR_FIELDS)]
    result = run_command(command, timeout)
    if result.exit_code != 0:
        return None, result, gh_error_message(result)
    try:
        raw = parse_json_result(result)
    except RuntimeError as exc:
        return None, result, str(exc)
    if not isinstance(raw, dict):
        return None, result, "gh returned non-object JSON for PR view"
    return normalize_pr(raw, target["repo"]), result, None


def normalize_author(author: Any) -> dict[str, Any] | None:
    if not isinstance(author, dict):
        return None
    return {key: author.get(key) for key in ("login", "name", "email") if author.get(key)}


def normalize_pr_summary(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": raw.get("number"),
        "url": raw.get("url"),
        "title": raw.get("title"),
        "state": raw.get("state"),
        "base_ref": raw.get("baseRefName"),
        "head_ref": raw.get("headRefName"),
    }


def normalize_pr(raw: dict[str, Any], repo: str) -> dict[str, Any]:
    body = raw.get("body") or ""
    summary = normalize_pr_summary(raw)
    summary.update(
        {
            "repo": repo,
            "body": body,
            "is_draft": raw.get("isDraft"),
            "author": normalize_author(raw.get("author")),
            "sections": extract_sections(body),
            "pr_tree": extract_pr_tree(body),
            "verification_artifacts": extract_verification_artifacts(body, raw.get("statusCheckRollup")),
        }
    )
    return summary


def local_pr_from_file(path: str, index: int, args: argparse.Namespace) -> dict[str, Any]:
    body_path = Path(path)
    body = body_path.read_text()
    title = args.title[index] if index < len(args.title) else None
    raw_number = args.number[index] if index < len(args.number) else None
    number = int(raw_number) if raw_number and raw_number.isdigit() else None
    return {
        "source": "body-file",
        "path": str(body_path),
        "repo": args.repo,
        "number": number,
        "url": None,
        "title": title,
        "state": None,
        "base_ref": None,
        "head_ref": None,
        "body": body,
        "sections": extract_sections(body),
        "pr_tree": extract_pr_tree(body),
        "verification_artifacts": extract_verification_artifacts(body, None),
    }


def extract_sections(body: str) -> dict[str, Any]:
    lines = body.splitlines()
    headings: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        match = SECTION_RE.match(line.strip())
        if match:
            headings.append((match.group(1).strip(), index))

    content: dict[str, str] = {}
    for index, (name, start) in enumerate(headings):
        end = headings[index + 1][1] if index + 1 < len(headings) else len(lines)
        content[name] = "\n".join(lines[start + 1 : end]).strip()

    canonical = {name: content.get(name, "") for name in TEMPLATE_SECTIONS}
    return {
        "order": [name for name, _ in headings],
        "template_order": [name for name, _ in headings if name in TEMPLATE_SECTIONS],
        "content": canonical,
        "extra_headings": [name for name, _ in headings if name not in TEMPLATE_SECTIONS],
    }


def extract_pr_tree(body: str) -> dict[str, Any]:
    reason = extract_sections(body)["content"].get("Reason for Change", "")
    lines = reason.splitlines()
    tree_start: int | None = None
    for index, line in enumerate(lines):
        if "pr tree" in line.lower():
            tree_start = index
            break
    if tree_start is None:
        return {"present": False, "entries": [], "current_marker_count": body.count("◀")}

    entries: list[dict[str, Any]] = []
    for line in lines[tree_start + 1 :]:
        stripped = line.strip()
        if not stripped and entries:
            break
        if not stripped:
            continue
        if not re.match(r"^(?:[-*+]\s+|\d+[.)]\s+|>)", stripped) and not re.search(r"(?:#|/pull/)\d+", stripped):
            if entries:
                break
            continue
        entries.append(
            {
                "text": stripped,
                "numbers": extract_pr_numbers(stripped),
                "current": "◀" in stripped,
            }
        )
    return {
        "present": True,
        "entries": entries,
        "current_marker_count": sum(1 for entry in entries if entry["current"]),
        "body_current_marker_count": body.count("◀"),
    }


def extract_pr_numbers(text: str) -> list[int]:
    numbers = set(int(match) for match in re.findall(r"#(\d+)\b", text))
    numbers.update(int(match) for match in re.findall(r"/pull/(\d+)\b", text))
    return sorted(numbers)


def extract_verification_artifacts(body: str, status_rollup: Any) -> dict[str, Any]:
    sections = extract_sections(body)["content"]
    verification = sections.get("Verification", "")
    text = verification or body
    urls = URL_RE.findall(text)
    status_urls = extract_status_urls(status_rollup)
    all_urls = stable_unique([*urls, *status_urls])
    commands = stable_unique([match.group("cmd").strip() for match in BAZEL_RE.finditer(text)])
    for line in text.splitlines():
        match = COMMAND_LINE_RE.match(line)
        if match:
            commands.append(match.group("cmd").strip())
    commands = stable_unique(commands)
    return {
        "bazel_commands": [command for command in commands if command.lower().startswith("bazel ")],
        "commands": commands,
        "baraza_links": [url for url in all_urls if "baraza" in url.lower()],
        "s3_links": stable_unique([*S3_RE.findall(text), *[url for url in all_urls if "s3" in url.lower()]]),
        "phoenix_log_paths": stable_unique(match.group("path") for match in PHOENIX_LOG_RE.finditer(text)),
        "zml_paths": stable_unique(match.group("path") for match in ZML_PATH_RE.finditer(text)),
        "output_paths": stable_unique(match.group("path") for match in OUTPUT_PATH_RE.finditer(text)),
        "gha_links": [url for url in all_urls if "github.com" in url.lower() and ("/actions/" in url.lower() or "/checks" in url.lower())],
        "aspect_links": [url for url in all_urls if "aspect" in url.lower()],
        "all_links": all_urls,
    }


def extract_status_urls(status_rollup: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(status_rollup, list):
        for item in status_rollup:
            if isinstance(item, dict):
                for key in ("detailsUrl", "targetUrl"):
                    value = item.get(key)
                    if isinstance(value, str) and value:
                        urls.append(value)
    return urls


def stable_unique(items: Any) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        text = str(item).strip().rstrip(".,")
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def build_packet(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    targets = [normalize_target(raw, args.repo) for raw in args.targets]
    if not targets and not args.body_file:
        targets = [normalize_target(None, args.repo)]

    git_context, git_commands = collect_git_context(args.timeout)
    if getattr(args, "from_git_spice", False):
        local_stack, local_stack_commands = collect_local_stack_from_git_spice(args.timeout, git_context, args.base)
        packet = {
            "schema_version": 1,
            "mode": "packet",
            "repo": args.repo,
            "read_only": True,
            "git": git_context,
            "git_spice": {
                "available": local_stack.get("available"),
                "command": local_stack.get("command"),
                "raw_order": local_stack.get("raw_order"),
                "error": local_stack.get("error"),
            },
            "local_stack": local_stack,
            "branch_prs": [],
            "gh": {"enabled": False, "reason": "--from-git-spice local stack mode"},
            "gh_errors": [],
            "commands": command_lines([*git_commands, *local_stack_commands]),
            "prs": [local_pr_from_file(path, index, args) for index, path in enumerate(args.body_file)],
        }
        return packet, 2 if local_stack.get("error") else 0

    spice_context, spice_commands = collect_git_spice(args.timeout, bool(git_context.get("inside_work_tree")))
    branch_prs, branch_commands, branch_error = collect_branch_prs(args.repo, git_context.get("branch"), args.timeout, args.no_gh)

    commands = [*git_commands, *spice_commands, *branch_commands]
    gh_errors: list[dict[str, Any]] = []
    fatal_gh_errors: list[dict[str, Any]] = []
    prs = [local_pr_from_file(path, index, args) for index, path in enumerate(args.body_file)]
    if branch_error:
        gh_errors.append({"target": "current branch mapping", **branch_error})

    if args.no_gh:
        gh_status = {"enabled": False, "reason": "--no-gh set"}
    elif shutil.which("gh") is None:
        gh_status = {"enabled": False, "reason": "gh executable not found on PATH"}
        if targets:
            error = {"target": "live PR fetch", "message": gh_status["reason"]}
            gh_errors.append(error)
            fatal_gh_errors.append(error)
    else:
        gh_status = {"enabled": True}
        for target in targets:
            pr, result, error = collect_live_pr(target, args.timeout)
            commands.append(result)
            if error:
                record = {"target": target["display"], "message": error}
                gh_errors.append(record)
                fatal_gh_errors.append(record)
            elif pr:
                prs.append(pr)

    packet = {
        "schema_version": 1,
        "mode": "packet",
        "repo": args.repo,
        "read_only": True,
        "git": git_context,
        "git_spice": spice_context,
        "branch_prs": branch_prs,
        "gh": gh_status,
        "gh_errors": gh_errors,
        "commands": command_lines(commands),
        "prs": prs,
    }
    return packet, 2 if fatal_gh_errors else 0


def build_draft_output(args: argparse.Namespace) -> str:
    branches, local_entries = resolve_draft_stack(args)
    current_indices = draft_current_indices(branches, args.current)
    drafts = [(branches[index], format_pr_body_draft(args, branches, index, local_entries)) for index in current_indices]
    if len(drafts) == 1:
        return drafts[0][1]

    lines: list[str] = []
    for label, body in drafts:
        if lines:
            lines.append("")
        lines.extend([f"<!-- BEGIN PR body draft: {label} -->", "", body.rstrip(), "", f"<!-- END PR body draft: {label} -->"])
    return "\n".join(lines) + "\n"


def resolve_draft_stack(args: argparse.Namespace) -> tuple[list[str], dict[str, dict[str, Any]]]:
    if not args.from_git_spice:
        if not args.branches:
            raise ValueError("draft requires branch labels unless --from-git-spice is set")
        return args.branches, {}
    if args.branches:
        raise ValueError("pass either explicit draft branch labels or --from-git-spice, not both")

    git_context, git_commands = collect_git_context(args.timeout)
    local_stack, local_stack_commands = collect_local_stack_from_git_spice(args.timeout, git_context, args.base)
    if local_stack.get("error"):
        commands = command_lines([*git_commands, *local_stack_commands])
        raise RuntimeError(f"failed to collect local git-spice stack: {local_stack['error']}; commands={json.dumps(commands)}")
    warnings = local_stack.get("warnings") or []
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    entries = local_stack.get("entries") or []
    branches = [entry["branch"] for entry in entries]
    if not branches:
        raise RuntimeError("git-spice local stack produced no branch entries")
    return branches, {entry["branch"]: entry for entry in entries}


def draft_current_indices(branches: list[str], current: str | None) -> list[int]:
    if current is None:
        return list(range(len(branches)))
    try:
        return [branches.index(current)]
    except ValueError as exc:
        raise ValueError(f"--current must match one of the branch labels: {current}") from exc


def format_pr_body_draft(args: argparse.Namespace, branches: list[str], current_index: int, local_entries: dict[str, dict[str, Any]]) -> str:
    branch = branches[current_index]
    description = args.description.strip()
    if local_entries and args.description == DEFAULT_DESCRIPTION:
        description = format_local_description_summary(local_entries[branch])
    return "\n".join(
        [
            "## Reason for Change",
            "",
            "<!-- Describe the bug or feature -->",
            args.reason.strip(),
            "",
            "PR Tree (branch placeholders until PR numbers exist)",
            "",
            *format_pr_tree_placeholders(branches, current_index),
            "",
            "## Description of Change",
            "",
            "<!-- What actually changed and how was it implemented? -->",
            description,
            "",
            "## Criticality of Change",
            "",
            *format_criticality_checkboxes(args.criticality),
            "",
            "## Verification",
            "",
            "<!-- How have you proven this change works?-->",
            args.verification.strip(),
            "",
            "## Release Notes",
            "",
            f"- [{'x' if args.release_notes_required else ' '}] Release Notes or Upgrade Instructions required",
            "",
            "<!-- If checked, replace this line with your release notes or upgrade instructions -->",
        ]
    ) + "\n"


def format_local_description_summary(entry: dict[str, Any]) -> str:
    lines = [
        "TODO: Convert this committed-diff summary into reviewer-facing prose.",
        "",
        f"Local committed diff: `{entry['diff_range']}` (does not include uncommitted worktree changes)",
        "",
        "Commits:",
    ]
    commits = entry.get("commits") or []
    if commits:
        lines.extend(f"- `{commit['hash']}` {commit['subject']}" for commit in commits[:8])
        if len(commits) > 8:
            lines.append(f"- ... {len(commits) - 8} more commit(s)")
    else:
        lines.append("- TODO: No committed changes found in this branch range.")

    files = entry.get("changed_files") or []
    lines.extend(["", "Changed files:"])
    if files:
        lines.extend(f"- `{item.get('status')}` {item.get('path')}" for item in files[:12])
        if len(files) > 12:
            lines.append(f"- ... {len(files) - 12} more file(s)")
    else:
        lines.append("- TODO: No changed files found in this branch range.")
    return "\n".join(lines)


def format_pr_tree_placeholders(branches: list[str], current_index: int) -> list[str]:
    return [f"- `{branch}`{' ◀' if index == current_index else ''}" for index, branch in enumerate(branches)]


def format_criticality_checkboxes(criticality: str) -> list[str]:
    choices = [
        ("L1", "L1 Major <!-- Impacts critical safety systems (e.g. Paraland, DAA, fault mgmt) -->"),
        ("L2", "L2 Moderate <!-- Impacts production system, or safety-related testing -->"),
        ("L3", "L3 Nonfunctional <!-- Trivial to validate no impact on prod (e.g. docs, style, dev tool) -->"),
    ]
    lines = [f"- [{'x' if criticality == key else ' '}] {label}" for key, label in choices]
    if criticality == "todo":
        lines.extend(["", "TODO: Choose L1/L2/L3 criticality before posting."])
    return lines


def audit_packet(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    packet, packet_exit_code = build_packet(args)
    prs = packet["prs"]
    findings: list[dict[str, Any]] = []
    for index, pr in enumerate(prs):
        findings.extend(audit_one_pr(pr, len(prs), index))
    if len(prs) > 1:
        findings.extend(audit_stack_consistency(prs))

    errors = sum(1 for finding in findings if finding["severity"] == "error")
    warnings = sum(1 for finding in findings if finding["severity"] == "warning")
    result = {
        "schema_version": 1,
        "mode": "audit",
        "repo": args.repo,
        "summary": {"prs": len(prs), "errors": errors, "warnings": warnings},
        "gh": packet["gh"],
        "gh_errors": packet["gh_errors"],
        "findings": findings,
        "commands": packet["commands"],
    }
    exit_code = packet_exit_code
    if exit_code == 0 and args.fail_on == "error" and errors:
        exit_code = 1
    elif exit_code == 0 and args.fail_on == "warning" and (errors or warnings):
        exit_code = 1
    return result, exit_code


def pr_label(pr: dict[str, Any], fallback_index: int = 0) -> str:
    number = pr.get("number")
    if number:
        return f"PR #{number}"
    path = pr.get("path")
    if path:
        return path
    return f"body {fallback_index + 1}"


def finding(severity: str, pr: dict[str, Any] | None, code: str, message: str, detail: Any = None) -> dict[str, Any]:
    item: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if pr is not None:
        item["pr"] = pr_label(pr)
        if pr.get("url"):
            item["url"] = pr.get("url")
    if detail is not None:
        item["detail"] = detail
    return item


def audit_one_pr(pr: dict[str, Any], stack_size: int, index: int) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    sections = pr.get("sections", {})
    content = sections.get("content", {}) if isinstance(sections, dict) else {}
    order = sections.get("order", []) if isinstance(sections, dict) else []
    if order != TEMPLATE_SECTIONS:
        missing_sections = [section for section in TEMPLATE_SECTIONS if section not in order]
        findings.append(
            finding(
                "error",
                pr,
                "template-section-order",
                "FlightSystems template sections must appear exactly once in canonical order, including Criticality of Change and Release Notes.",
                {"expected": TEMPLATE_SECTIONS, "actual": order, "missing": missing_sections},
            )
        )
    extra = sections.get("extra_headings", []) if isinstance(sections, dict) else []
    if extra:
        findings.append(finding("warning", pr, "extra-section-headings", "PR body has extra level-2 headings outside the template.", extra))

    tree = pr.get("pr_tree", {})
    if stack_size > 1:
        if not tree.get("present"):
            findings.append(finding("error", pr, "missing-pr-tree", "Multi-PR stacks should include a PR Tree under Reason for Change."))
        marker_count = int(tree.get("current_marker_count") or tree.get("body_current_marker_count") or 0)
        if marker_count != 1:
            findings.append(finding("error", pr, "pr-tree-current-marker", "Each stacked PR body should have exactly one ◀ current marker.", {"count": marker_count}))

    title = pr.get("title") or ""
    findings.extend(audit_title(pr, title))
    if FSW_RE.search(title) and not (FSW_RE.search(pr.get("body") or "") or JIRA_LINK_RE.search(pr.get("body") or "")):
        findings.append(finding("warning", pr, "missing-fsw-reference", "Title has an FSW ticket, but the body lacks a Jira/FSW reference or link near Reason for Change."))

    findings.extend(audit_criticality(pr, content.get("Criticality of Change", "")))
    findings.extend(audit_release_notes(pr, content.get("Release Notes", "")))
    findings.extend(audit_verification(pr, content.get("Verification", ""), pr))
    return findings


def audit_stack_consistency(prs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [normalize_reason_for_chain(pr.get("sections", {}).get("content", {}).get("Reason for Change", "")) for pr in prs]
    non_empty = [text for text in normalized if text]
    if len(set(non_empty)) > 1:
        return [
            finding(
                "error",
                None,
                "stack-reason-consistency",
                "Stacked PRs should keep chain-level Reason for Change identical apart from PR Tree current-marker differences.",
                {pr_label(pr, index): normalized[index] for index, pr in enumerate(prs)},
            )
        ]
    return []


def normalize_reason_for_chain(reason: str) -> str:
    lines = reason.splitlines()
    output: list[str] = []
    for line in lines:
        if line.strip().startswith("<!--"):
            continue
        output.append(line.replace("◀", ""))
    return re.sub(r"\s+", " ", "\n".join(output)).strip()


def audit_title(pr: dict[str, Any], title: str) -> list[dict[str, Any]]:
    if not title:
        return [finding("warning", pr, "missing-title", "No title available for title-style audit.")]
    findings: list[dict[str, Any]] = []
    bracket_match = re.match(r"^\[([^\]]+)\]\s+\[([^\]]+)\]\s+(.+)$", title)
    if FSW_RE.search(title) and not bracket_match:
        findings.append(finding("warning", pr, "title-ticket-brackets", "Ticketed Phoenix titles usually start with [FSW-#####] [Phoenix] ...; use another readable domain bracket when Phoenix does not apply."))
    if bracket_match:
        ticket, domain, rest = bracket_match.groups()
        if not re.match(r"^[A-Z]+-\d+$", ticket):
            findings.append(finding("warning", pr, "title-ticket-format", "Ticket bracket should look like [FSW-#####] or another uppercase ticket key."))
        if not domain or not domain[0].isupper() or domain.isupper() or domain.islower():
            findings.append(finding("warning", pr, "title-domain-capitalization", "Domain bracket should use readable capitalization such as [Phoenix]."))
        if rest and rest[0].islower():
            findings.append(finding("warning", pr, "title-readable-capitalization", "Title text after brackets should start with a capitalized, readable phrase."))
    elif title and title[0].islower():
        findings.append(finding("warning", pr, "title-readable-capitalization", "Title should start with a readable capitalized phrase."))
    if re.search(r"\b(wip|todo|fix stuff|misc)\b", title, re.IGNORECASE):
        findings.append(finding("warning", pr, "title-readability", "Title contains placeholder or low-signal wording."))
    return findings


def audit_criticality(pr: dict[str, Any], section: str) -> list[dict[str, Any]]:
    selected = []
    for line in section.splitlines():
        match = CHECKBOX_RE.search(line)
        if match and match.group("mark").lower() == "x":
            selected.append(match.group("label").strip())
    if len(selected) != 1:
        return [finding("warning", pr, "criticality-checkbox", "Criticality should have exactly one selected checkbox.", {"selected": selected})]
    return []


def audit_release_notes(pr: dict[str, Any], section: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    selected = False
    for line in section.splitlines():
        match = CHECKBOX_RE.search(line)
        if match and "release notes" in match.group("label").lower() and match.group("mark").lower() == "x":
            selected = True
    if selected:
        non_comment = [line.strip() for line in section.splitlines() if line.strip() and not line.strip().startswith("<!--") and not CHECKBOX_RE.search(line)]
        if "replace this line" in section.lower() or not non_comment:
            findings.append(finding("warning", pr, "release-notes-placeholder", "Release Notes is checked but still appears to contain a placeholder or no release-note text."))
    return findings


def audit_verification(pr: dict[str, Any], section: str, full_pr: dict[str, Any]) -> list[dict[str, Any]]:
    text = section.strip()
    if not text:
        return [finding("warning", pr, "verification-missing", "Verification should contain exact evidence, not the template placeholder.")]

    findings: list[dict[str, Any]] = []
    if VERIFICATION_PLACEHOLDER_RE.search(text):
        findings.append(finding("warning", pr, "verification-placeholder", "Verification still contains a generated placeholder such as TODO, empty query results, or template text."))

    artifacts = full_pr.get("verification_artifacts", {})
    exact_count = sum(len(artifacts.get(key, [])) for key in ("commands", "baraza_links", "s3_links", "phoenix_log_paths", "zml_paths", "output_paths", "gha_links", "aspect_links"))
    if exact_count and not has_checked_verification_item(text):
        findings.append(finding("warning", pr, "verification-checklist", "Verification cites concrete evidence but should use checked checklist bullets such as `- [x] Manual Test [Baraza](...) [S3](...)`."))

    raw_s3_urls = raw_visible_s3_urls(text)
    if raw_s3_urls:
        findings.append(finding("warning", pr, "verification-raw-s3", "Use markdown `[S3](...)` links instead of raw visible `s3://...` paths in Verification.", raw_s3_urls))

    vague_ci = re.fullmatch(r"(?is)\s*(?:[-*]\s*)?(?:ci|gha|checks?)\s*(?:passes|passed|will pass|green)?\.?\s*", text) is not None
    l3_tiny = is_l3_tiny_nonfunctional(full_pr)
    if exact_count == 0 and (vague_ci or len(text) < 80) and not l3_tiny:
        findings.append(finding("warning", pr, "verification-vague", "Verification should cite exact commands, links, logs, ZML paths, or output folders instead of vague CI-only evidence."))
    return findings


def has_checked_verification_item(text: str) -> bool:
    for line in text.splitlines():
        match = CHECKBOX_RE.search(line)
        if match and match.group("mark").lower() == "x":
            return True
    return False


def raw_visible_s3_urls(text: str) -> list[str]:
    linked_urls = set(stable_unique(match.group("url") for match in MARKDOWN_S3_LINK_RE.finditer(text)))
    return [url for url in stable_unique(S3_RE.findall(text)) if url not in linked_urls]


def is_l3_tiny_nonfunctional(pr: dict[str, Any]) -> bool:
    sections = pr.get("sections", {}).get("content", {})
    criticality = sections.get("Criticality of Change", "")
    description = sections.get("Description of Change", "")
    l3_selected = any("[x]" in line.lower() and "l3" in line.lower() for line in criticality.splitlines())
    return l3_selected and len(description.strip()) < 600


def print_packet(packet: dict[str, Any], output_format: str) -> None:
    if output_format == "markdown":
        print(format_packet_markdown(packet), end="")
    else:
        print(json.dumps(packet, indent=2, sort_keys=True))


def print_audit(result: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    elif output_format == "markdown":
        print(format_audit_markdown(result), end="")
    else:
        print(format_audit_text(result), end="")


def format_packet_markdown(packet: dict[str, Any]) -> str:
    lines = ["# PR stack packet", "", f"- Repo: `{packet['repo']}`", "- Read-only: true"]
    git_context = packet.get("git", {})
    lines.extend(
        [
            f"- Git branch: `{git_context.get('branch') or 'unknown'}`",
            f"- Dirty: {git_context.get('dirty')} ({git_context.get('dirty_entries', 0)} entries)",
            f"- gh: {packet.get('gh')}",
        ]
    )
    if packet.get("git_spice", {}).get("raw_order"):
        lines.extend(["", "## git-spice stack", "", "```", packet["git_spice"]["raw_order"], "```"])
    if packet.get("local_stack"):
        lines.extend(format_local_stack_markdown(packet["local_stack"]))
    if packet.get("gh_errors"):
        lines.extend(["", "## gh errors", *[f"- {item.get('target')}: {item.get('message')}" for item in packet["gh_errors"]]])
    lines.extend(["", "## PRs"])
    for pr in packet.get("prs", []):
        lines.extend(format_pr_markdown(pr))
    return "\n".join(lines) + "\n"


def format_local_stack_markdown(local_stack: dict[str, Any]) -> list[str]:
    lines = ["", "## Local stack entries", ""]
    if local_stack.get("error"):
        lines.append(f"- Error: {local_stack['error']}")
        return lines
    lines.extend(
        [
            f"- Base: `{local_stack.get('base') or 'unknown'}`",
            f"- Current branch: `{local_stack.get('current_branch') or 'unknown'}`",
            f"- Current in stack: {local_stack.get('current_in_stack')}",
        ]
    )
    for warning in local_stack.get("warnings") or []:
        lines.append(f"- Warning: {warning}")
    entries = local_stack.get("entries") or []
    if not entries:
        lines.append("- No local stack entries parsed.")
        return lines

    for entry in entries:
        lines.extend(format_local_stack_entry_markdown(entry))
    return lines


def format_local_stack_entry_markdown(entry: dict[str, Any]) -> list[str]:
    marker = " ◀" if entry.get("current") else ""
    lines = ["", f"### `{entry['branch']}`{marker}", ""]
    lines.extend(
        [
            f"- Parent/base: `{entry['parent']}`",
            f"- Commit range: `{entry['commit_range']}`",
            f"- Diff range: `{entry['diff_range']}`",
            f"- Title suggestion: {entry.get('title_suggestion') or '_unknown_'}",
        ]
    )
    if entry.get("errors"):
        lines.append(f"- Command errors: {len(entry['errors'])}")
    commits = entry.get("commits") or []
    lines.append("- Commits: " + (", ".join(f"`{item['hash']}` {item['subject']}" for item in commits) if commits else "none"))
    files = entry.get("changed_files") or []
    lines.append("- Changed files: " + (", ".join(f"`{item.get('status')}` {item.get('path')}" for item in files[:20]) if files else "none"))
    if len(files) > 20:
        lines.append(f"- Changed files truncated: {len(files) - 20} more")
    if entry.get("diff_stat"):
        lines.extend(["", "```", entry["diff_stat"], "```"])
    return lines


def format_pr_markdown(pr: dict[str, Any]) -> list[str]:
    lines = ["", f"### {pr_label(pr)}", ""]
    lines.extend(
        [
            f"- Title: {pr.get('title') or '_unknown_' }",
            f"- State: {pr.get('state') or '_unknown_'}",
            f"- Refs: `{pr.get('base_ref') or '?'}` ← `{pr.get('head_ref') or '?'}`",
        ]
    )
    section_order = pr.get("sections", {}).get("template_order", [])
    lines.append("- Sections: " + (", ".join(section_order) if section_order else "none extracted"))
    tree = pr.get("pr_tree", {})
    lines.append(f"- PR Tree: present={tree.get('present')}, current markers={tree.get('current_marker_count')}")
    artifacts = pr.get("verification_artifacts", {})
    evidence = []
    for key in ("bazel_commands", "baraza_links", "s3_links", "phoenix_log_paths", "zml_paths", "output_paths", "gha_links", "aspect_links"):
        if artifacts.get(key):
            evidence.append(f"{key}={len(artifacts[key])}")
    lines.append("- Verification artifacts: " + (", ".join(evidence) if evidence else "none extracted"))
    return lines


def format_audit_text(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [f"Audit: {summary['prs']} PR body(s), {summary['errors']} error(s), {summary['warnings']} warning(s)"]
    if result.get("gh_errors"):
        lines.append("gh errors:")
        lines.extend(f"  - {item.get('target')}: {item.get('message')}" for item in result["gh_errors"])
    if result.get("findings"):
        lines.append("findings:")
        for item in result["findings"]:
            prefix = f"  - [{item['severity']}] {item['code']}"
            subject = f" ({item['pr']})" if item.get("pr") else ""
            lines.append(f"{prefix}{subject}: {item['message']}")
    else:
        lines.append("findings: none")
    return "\n".join(lines) + "\n"


def format_audit_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = ["# PR description audit", "", f"- PR bodies: {summary['prs']}", f"- Errors: {summary['errors']}", f"- Warnings: {summary['warnings']}"]
    if result.get("findings"):
        lines.extend(["", "## Findings"])
        for item in result["findings"]:
            subject = f" ({item['pr']})" if item.get("pr") else ""
            lines.append(f"- **{item['severity']}** `{item['code']}`{subject}: {item['message']}")
    else:
        lines.extend(["", "## Findings", "", "None."])
    return "\n".join(lines) + "\n"


def validate_body_file_args(args: argparse.Namespace) -> None:
    if len(args.title) > len(args.body_file):
        raise ValueError("--title may not be repeated more times than --body-file")
    if len(args.number) > len(args.body_file):
        raise ValueError("--number may not be repeated more times than --body-file")
    for path in args.body_file:
        if not Path(path).is_file():
            raise ValueError(f"body file does not exist: {path}")


def main() -> int:
    args = parse_args()
    if args.mode == "packet":
        validate_body_file_args(args)
        packet, exit_code = build_packet(args)
        print_packet(packet, args.format)
        return exit_code
    if args.mode == "draft":
        print(build_draft_output(args), end="")
        return 0
    validate_body_file_args(args)
    result, exit_code = audit_packet(args)
    print_audit(result, args.format)
    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"opencode_pr_stack_packet.py: {exc}", file=sys.stderr)
        raise SystemExit(2)
