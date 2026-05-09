#!/usr/bin/env python3
"""Build a deterministic GitHub PR context packet for OpenCode review skills.

Output shape, in JSON by default:
{
  "schema_version": 1,
  "dry_run": false,
  "target": {"kind": "pr-number|pr-url|current-branch", "input": "..."},
  "commands": ["gh ..."],
  "pr": {metadata, refs, draft/review state, additions/deletions},
  "files": [{"path": "...", "additions": 1, "deletions": 0, ...}],
  "commits": [{"oid": "...", "message_headline": "...", ...}],
  "checks": {"command_exit_code": 0, "items": [{"name": "...", "state": "...", ...}]},
  "comments": {"comments": [...], "reviews": [...], "latest_reviews": [...]}  # optional; no GraphQL reviewThreads
}

Dry-run and print-commands modes only plan commands; they never invoke gh,
network, or auth. Real mode shells out to gh and reports command failures with
the exact command, stderr, and a non-interactive auth-refresh hint.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
from typing import Any


PR_FIELDS = (
    "number",
    "url",
    "title",
    "body",
    "author",
    "baseRefName",
    "headRefName",
    "isDraft",
    "mergeStateStatus",
    "reviewDecision",
    "state",
    "additions",
    "deletions",
    "changedFiles",
    "commits",
    "files",
    "statusCheckRollup",
)
COMMENT_FIELDS = ("comments", "reviews", "latestReviews")
PR_URL_RE = re.compile(r"^https?://github\.com/[^/\s]+/[^/\s]+/pull/\d+/?$")
PR_NUMBER_RE = re.compile(r"^\d+$")


class CommandFailure(Exception):
    def __init__(self, command: list[str], returncode: int, stdout: str, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(shlex.join(command))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a deterministic GitHub PR context packet for human-review preparation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Output includes:
              schema_version, dry_run, target, exact gh commands, PR metadata,
              files/additions/deletions, commits, checks, and optional comments/reviews.

            Examples:
              github_pr_context.py 52370
              github_pr_context.py https://github.com/OWNER/REPO/pull/52370 --format markdown
              github_pr_context.py --dry-run 123 --format json
              github_pr_context.py --print-commands --include-comments

            Dry-run and --print-commands do not invoke gh, network, or auth.
            """
        ).strip(),
    )
    parser.add_argument(
        "pr",
        nargs="?",
        help="PR number or GitHub PR URL. Omit to target the current branch PR.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the deterministic packet with planned commands only; never invoke gh.",
    )
    parser.add_argument(
        "--print-commands",
        action="store_true",
        help="Print planned gh commands and exit without invoking gh.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format for the context packet (default: json).",
    )
    parser.add_argument(
        "--include-comments",
        action="store_true",
        help="Also fetch PR comments, reviews, and latest reviews. Does not fetch or resolve GraphQL review threads.",
    )
    args = parser.parse_args()
    if args.pr and not (PR_NUMBER_RE.match(args.pr) or PR_URL_RE.match(args.pr)):
        parser.error("pr must be a PR number or a GitHub PR URL")
    return args


def target_info(raw_pr: str | None) -> dict[str, Any]:
    if raw_pr is None:
        return {"kind": "current-branch", "input": None, "display": "current branch"}
    if PR_NUMBER_RE.match(raw_pr):
        return {"kind": "pr-number", "input": raw_pr, "display": f"PR #{raw_pr}"}
    return {"kind": "pr-url", "input": raw_pr, "display": raw_pr}


def target_args(target: dict[str, Any]) -> list[str]:
    return [] if target["input"] is None else [target["input"]]


def planned_commands(target: dict[str, Any], include_comments: bool) -> list[list[str]]:
    selector = target_args(target)
    commands = [
        ["gh", "pr", "view", *selector, "--json", ",".join(PR_FIELDS)],
    ]
    if include_comments:
        commands.append(["gh", "pr", "view", *selector, "--json", ",".join(COMMENT_FIELDS)])
    return commands


def command_lines(commands: list[list[str]]) -> list[str]:
    return [shlex.join(command) for command in commands]


def run_json_command(
    command: list[str],
) -> tuple[Any, int]:
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode == 0:
        return parse_json_stdout(command, result.stdout, result.stderr, result.returncode), result.returncode
    raise CommandFailure(command, result.returncode, result.stdout, result.stderr)


def parse_json_stdout(command: list[str], stdout: str, stderr: str, returncode: int) -> Any:
    try:
        return json.loads(stdout or "null")
    except json.JSONDecodeError as exc:
        raise CommandFailure(command, returncode, stdout, stderr or f"failed to parse JSON stdout: {exc}") from exc


def normalize_author(author: Any) -> dict[str, Any] | None:
    if not isinstance(author, dict):
        return None
    return {key: author.get(key) for key in ("login", "name", "email") if author.get(key)}


def normalize_pr(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": raw.get("number"),
        "url": raw.get("url"),
        "title": raw.get("title"),
        "body": raw.get("body"),
        "author": normalize_author(raw.get("author")),
        "base_ref": raw.get("baseRefName"),
        "head_ref": raw.get("headRefName"),
        "is_draft": raw.get("isDraft"),
        "merge_state_status": raw.get("mergeStateStatus"),
        "review_decision": raw.get("reviewDecision"),
        "state": raw.get("state"),
        "additions": raw.get("additions"),
        "deletions": raw.get("deletions"),
        "changed_files": raw.get("changedFiles"),
    }


def normalize_files(files: Any) -> list[dict[str, Any]]:
    if not isinstance(files, list):
        return []
    normalized = []
    for item in files:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "path": item.get("path"),
                "additions": item.get("additions"),
                "deletions": item.get("deletions"),
                "change_type": item.get("changeType"),
            }
        )
    return sorted(normalized, key=lambda item: item.get("path") or "")


def normalize_commits(commits: Any) -> list[dict[str, Any]]:
    if not isinstance(commits, list):
        return []
    normalized = []
    for item in commits:
        if not isinstance(item, dict):
            continue
        authors = item.get("authors") if isinstance(item.get("authors"), list) else []
        normalized.append(
            {
                "oid": item.get("oid"),
                "abbreviated_oid": item.get("abbreviatedOid"),
                "message_headline": item.get("messageHeadline"),
                "authored_date": item.get("authoredDate"),
                "committed_date": item.get("committedDate"),
                "authors": [normalize_author(author) for author in authors if isinstance(author, dict)],
            }
        )
    return sorted(normalized, key=lambda item: (item.get("committed_date") or "", item.get("oid") or ""))


def first_non_blank(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, (dict, list)) or value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def nested_text(item: dict[str, Any], *path: str) -> str | None:
    value: Any = item
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return first_non_blank(value)


def check_display_name(item: dict[str, Any]) -> str:
    return (
        first_non_blank(
            item.get("name"),
            item.get("context"),
            item.get("title"),
            item.get("workflowName"),
            nested_text(item, "workflow", "name"),
            nested_text(item, "app", "name"),
            nested_text(item, "checkSuite", "workflowRun", "workflow", "name"),
            item.get("__typename"),
        )
        or "_unnamed check_"
    )


def check_workflow_name(item: dict[str, Any]) -> str | None:
    return first_non_blank(
        item.get("workflow"),
        item.get("workflowName"),
        nested_text(item, "workflow", "name"),
        nested_text(item, "checkSuite", "workflowRun", "workflow", "name"),
    )


def check_status_label(item: dict[str, Any]) -> str:
    return first_non_blank(item.get("conclusion"), item.get("state"), item.get("status")) or "_unknown status_"


def normalize_checks(checks: Any, exit_code: int) -> dict[str, Any]:
    rows = checks if isinstance(checks, list) else []
    normalized = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        display_name = check_display_name(item)
        display_status = check_status_label(item)
        normalized.append(
            {
                "typename": item.get("__typename"),
                "bucket": item.get("bucket"),
                "workflow": check_workflow_name(item),
                "name": item.get("name"),
                "context": item.get("context"),
                "title": item.get("title"),
                "display_name": display_name,
                "display_status": display_status,
                "state": item.get("state") or item.get("status"),
                "status": item.get("status"),
                "conclusion": item.get("conclusion"),
                "started_at": item.get("startedAt"),
                "completed_at": item.get("completedAt"),
                "details_url": item.get("detailsUrl") or item.get("targetUrl"),
            }
        )
    normalized.sort(
        key=lambda item: (item.get("workflow") or "", item.get("display_name") or "", item.get("bucket") or "")
    )
    return {"command_exit_code": exit_code, "items": normalized}


def normalize_comment_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "id": item.get("id"),
        "author": normalize_author(item.get("author")),
        "state": item.get("state"),
        "submitted_at": item.get("submittedAt"),
        "created_at": item.get("createdAt"),
        "updated_at": item.get("updatedAt"),
        "body": item.get("body"),
    }


def normalize_comments(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    output: dict[str, Any] = {}
    for source_key, output_key in (
        ("comments", "comments"),
        ("reviews", "reviews"),
        ("latestReviews", "latest_reviews"),
    ):
        items = raw.get(source_key) if isinstance(raw.get(source_key), list) else []
        normalized = []
        for item in items:
            normalized_item = normalize_comment_item(item)
            if normalized_item is not None:
                normalized.append(normalized_item)
        normalized.sort(key=lambda item: (item.get("created_at") or item.get("submitted_at") or "", item.get("id") or ""))
        output[output_key] = normalized
    return output


def dry_run_packet(target: dict[str, Any], commands: list[list[str]], include_comments: bool) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dry_run": True,
        "target": target,
        "commands": command_lines(commands),
        "planned_sections": [
            "pr metadata/base/head/draft/review status",
            "files/additions/deletions",
            "commits",
            "checks",
            *(["comments/reviews"] if include_comments else []),
        ],
        "pr": {},
        "files": [],
        "commits": [],
        "checks": {"command_exit_code": None, "items": []},
        "comments": None if not include_comments else {"comments": [], "reviews": [], "latest_reviews": []},
    }


def real_packet(target: dict[str, Any], commands: list[list[str]], include_comments: bool) -> dict[str, Any]:
    if shutil.which("gh") is None:
        raise CommandFailure(commands[0], 127, "", "gh executable not found on PATH")

    pr_raw, _ = run_json_command(commands[0])
    comments_raw = None
    if include_comments:
        comments_raw, _ = run_json_command(commands[1])

    return {
        "schema_version": 1,
        "dry_run": False,
        "target": target,
        "commands": command_lines(commands),
        "pr": normalize_pr(pr_raw if isinstance(pr_raw, dict) else {}),
        "files": normalize_files(pr_raw.get("files") if isinstance(pr_raw, dict) else []),
        "commits": normalize_commits(pr_raw.get("commits") if isinstance(pr_raw, dict) else []),
        "checks": normalize_checks(pr_raw.get("statusCheckRollup") if isinstance(pr_raw, dict) else [], 0),
        "comments": normalize_comments(comments_raw) if include_comments else None,
    }


def markdown_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def format_check_item(item: dict[str, Any]) -> str:
    workflow = first_non_blank(item.get("workflow"))
    name = (
        first_non_blank(
            item.get("display_name"),
            item.get("name"),
            item.get("context"),
            item.get("title"),
            item.get("typename"),
        )
        or "_unnamed check_"
    )
    status = first_non_blank(
        item.get("display_status"),
        item.get("conclusion"),
        item.get("state"),
        item.get("status"),
    ) or "_unknown status_"
    if workflow and workflow != name:
        return f"- {markdown_escape(workflow)}: {markdown_escape(name)} — {markdown_escape(status)}"
    return f"- {markdown_escape(name)} — {markdown_escape(status)}"


def format_markdown(packet: dict[str, Any]) -> str:
    pr = packet.get("pr") if isinstance(packet.get("pr"), dict) else {}
    checks = packet.get("checks") if isinstance(packet.get("checks"), dict) else {}
    lines = [
        "# GitHub PR context",
        "",
        f"- Target: {packet['target']['display']}",
        f"- Dry run: {str(packet['dry_run']).lower()}",
    ]
    if pr:
        lines.extend(
            [
                f"- PR: #{pr.get('number')} — {pr.get('title')}",
                f"- URL: {pr.get('url')}",
                f"- Refs: {pr.get('base_ref')} <- {pr.get('head_ref')}",
                f"- Status: draft={pr.get('is_draft')}, review={pr.get('review_decision')}, merge={pr.get('merge_state_status')}",
                f"- Size: +{pr.get('additions')} / -{pr.get('deletions')} across {pr.get('changed_files')} files",
            ]
        )
    lines.extend(["", "## Commands", *[f"- `{command}`" for command in packet["commands"]]])

    files = packet.get("files") if isinstance(packet.get("files"), list) else []
    lines.extend(["", "## Files", "| Path | + | - | Change |", "| --- | ---: | ---: | --- |"])
    lines.extend(
        f"| `{markdown_escape(item.get('path'))}` | {markdown_escape(item.get('additions'))} | {markdown_escape(item.get('deletions'))} | {markdown_escape(item.get('change_type'))} |"
        for item in files
    )
    if not files:
        lines.append("| _none in packet_ |  |  |  |")

    commits = packet.get("commits") if isinstance(packet.get("commits"), list) else []
    lines.extend(["", "## Commits"])
    lines.extend(f"- `{item.get('abbreviated_oid') or item.get('oid')}` {markdown_escape(item.get('message_headline'))}" for item in commits)
    if not commits:
        lines.append("- _none in packet_")

    check_items = checks.get("items") if isinstance(checks.get("items"), list) else []
    lines.extend(["", "## Checks", f"- source command exit code: {checks.get('command_exit_code')}"])
    lines.extend(format_check_item(item) for item in check_items if isinstance(item, dict))
    if not check_items:
        lines.append("- _none in packet_")

    comments = packet.get("comments") if isinstance(packet.get("comments"), dict) else None
    if comments is not None:
        lines.extend(
            [
                "",
                "## Comments/reviews",
                f"- comments: {len(comments.get('comments', []))}",
                f"- reviews: {len(comments.get('reviews', []))}",
                f"- latest reviews: {len(comments.get('latest_reviews', []))}",
            ]
        )
    return "\n".join(lines) + "\n"


def print_packet(packet: dict[str, Any], output_format: str) -> None:
    if output_format == "markdown":
        print(format_markdown(packet), end="")
        return
    print(json.dumps(packet, indent=2, sort_keys=True))


def print_failure(exc: CommandFailure) -> None:
    print("github_pr_context.py: gh command failed", file=sys.stderr)
    print(f"command: {shlex.join(exc.command)}", file=sys.stderr)
    print(f"exit code: {exc.returncode}", file=sys.stderr)
    print(f"stderr: {exc.stderr.strip() or '(empty)'}", file=sys.stderr)
    if exc.stdout.strip():
        print(f"stdout: {exc.stdout.strip()}", file=sys.stderr)
    print("Refresh GitHub auth with `gh auth refresh` or `gh auth login`; this helper will not start interactive auth.", file=sys.stderr)


def main() -> int:
    args = parse_args()
    target = target_info(args.pr)
    commands = planned_commands(target, args.include_comments)

    if args.print_commands:
        print("\n".join(command_lines(commands)))
        return 0

    packet = dry_run_packet(target, commands, args.include_comments) if args.dry_run else real_packet(target, commands, args.include_comments)
    print_packet(packet, args.format)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CommandFailure as exc:
        print_failure(exc)
        raise SystemExit(2)
