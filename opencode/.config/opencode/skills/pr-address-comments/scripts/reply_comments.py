#!/usr/bin/env python3
"""Reply to PR comments and review threads using a JSON input file.

Supports:
  - Issue or PR conversation comments (creates a new comment on the PR)
  - Review thread replies (reply to an existing inline review comment)

By default, each reply body must start with "__Comment by Robot__".

Input JSON shape:
  - Either a list of reply objects, or {"replies": [ ... ]}
  - Each reply object:
      {
        "kind": "issue_comment" | "review_comment",
        "body": "__Comment by Robot__\ntext",
        "in_reply_to": "<review_comment_id>",  # required for review_comment
        "resolve_thread_id": "<thread_id>"     # optional for review_comment
      }
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REQUIRED_PREFIX = "__Comment by Robot__"

REPLY_MUTATION = """\
mutation($body: String!, $inReplyTo: ID!) {
  addPullRequestReviewComment(input: {body: $body, inReplyTo: $inReplyTo}) {
    comment { id url }
  }
}
"""

REVIEW_COMMENT_DB_ID_QUERY = """\
query($id: ID!) {
  node(id: $id) {
    ... on PullRequestReviewComment {
      id
      databaseId
      replyTo { id }
      pullRequest { number url }
    }
  }
}
"""

THREAD_CONTEXT_QUERY = """\
query($id: ID!) {
  node(id: $id) {
    ... on PullRequestReviewThread {
      id
      pullRequest { number url }
      comments(first: 100) {
        nodes {
          id
        }
      }
    }
  }
}
"""

RESOLVE_MUTATION = """\
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { id isResolved }
  }
}
"""


@dataclass(frozen=True)
class RepoContext:
    hostname: str
    owner: str
    repo: str
    number: int


def _run(cmd: list[str], stdin: str | None = None) -> str:
    result = subprocess.run(cmd, input=stdin, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout


def _run_json(cmd: list[str], stdin: str | None = None) -> Any:
    output = _run(cmd, stdin=stdin)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Failed to parse JSON from command output: {exc}\nRaw:\n{output}"
        ) from exc


def _expect_graphql_success(result: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RuntimeError(f"{context}: expected object from GraphQL API")
    if result.get("errors"):
        raise RuntimeError(f"{context}:\n{json.dumps(result['errors'], indent=2)}")
    return result


def _expect_graphql_node(result: Any, *, context: str) -> dict[str, Any]:
    payload = _expect_graphql_success(result, context=context)
    node = payload.get("data", {}).get("node")
    if not isinstance(node, dict):
        raise RuntimeError(f"{context}: target node not found")
    return node


def _normalize_hostname(hostname: str | None) -> str | None:
    if not hostname:
        return None
    if hostname == "api.github.com":
        return "github.com"
    return hostname


def _parse_pr_ref_from_url(url: str) -> tuple[str, str, str, int] | None:
    parsed = urlparse(url)
    hostname = _normalize_hostname(parsed.hostname)
    if not hostname:
        return None

    html_match = re.match(r"^/([^/]+)/([^/]+)/pull/(\d+)(?:/.*)?$", parsed.path)
    if html_match:
        owner, repo, number = html_match.groups()
        return hostname, owner, repo, int(number)

    api_match = re.match(r"^/(?:api/v3/)?repos/([^/]+)/([^/]+)/pulls/(\d+)(?:/.*)?$", parsed.path)
    if api_match:
        owner, repo, number = api_match.groups()
        return hostname, owner, repo, int(number)

    return None


def _parse_repo_arg(repo: str | None) -> tuple[str | None, str, str] | None:
    if not repo:
        return None
    parts = repo.split("/")
    if len(parts) == 2:
        owner, name = parts
        return None, owner, name
    if len(parts) == 3:
        hostname, owner, name = parts
        return _normalize_hostname(hostname), owner, name
    return None


def _ensure_target_matches_pr(
    ctx: RepoContext,
    *,
    pr_url: str | None,
    pr_number: int | None,
    target_kind: str,
    target_id: str,
) -> None:
    if pr_number != ctx.number:
        raise RuntimeError(
            f"{target_kind} {target_id} belongs to PR #{pr_number}, not {ctx.owner}/{ctx.repo}#{ctx.number}"
        )
    if not pr_url:
        raise RuntimeError(f"Unable to verify PR ownership for {target_kind} {target_id}")

    parsed = _parse_pr_ref_from_url(pr_url)
    if not parsed:
        raise RuntimeError(f"Unable to parse PR URL for {target_kind} {target_id}: {pr_url}")

    hostname, owner, repo, number = parsed
    if (hostname, owner, repo, number) != (ctx.hostname, ctx.owner, ctx.repo, ctx.number):
        raise RuntimeError(
            f"{target_kind} {target_id} belongs to {hostname}/{owner}/{repo}#{number}, not "
            f"{ctx.hostname}/{ctx.owner}/{ctx.repo}#{ctx.number}"
        )


def _ensure_gh_authenticated() -> None:
    try:
        _run(["gh", "auth", "status"])
    except RuntimeError:
        print("run `gh auth login` to authenticate the GitHub CLI", file=sys.stderr)
        raise RuntimeError(
            "gh auth status failed; run `gh auth login` to authenticate the GitHub CLI"
        ) from None


def _maybe_emit_permissions_hint(error: str, *, context: str) -> None:
    lowered = error.lower()
    if "forbidden" in lowered or "permission" in lowered:
        print(
            f"{context}: If this is a permissions error, run `gh auth refresh -s repo` "
            "or `gh auth login` with `repo` scope, and ensure any required org SSO is authorized.",
            file=sys.stderr,
        )


def _load_replies(path: str) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)

    replies = data["replies"] if isinstance(data, dict) and "replies" in data else data
    if not isinstance(replies, list):
        raise TypeError("replies JSON must be a list or an object with a 'replies' list")
    return replies


def _validate_reply(reply: dict[str, Any], *, allow_unprefixed: bool) -> None:
    if not isinstance(reply, dict):
        raise TypeError("each reply must be an object")

    kind = reply.get("kind")
    if kind not in {"issue_comment", "review_comment"}:
        raise ValueError(f"unsupported reply kind: {kind}")

    body = reply.get("body")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("reply body must be a non-empty string")
    if not allow_unprefixed and not body.lstrip().startswith(REQUIRED_PREFIX):
        raise ValueError(f"reply body must start with {REQUIRED_PREFIX!r}")

    if kind == "review_comment":
        in_reply_to = reply.get("in_reply_to")
        if not isinstance(in_reply_to, str) or not in_reply_to.strip():
            raise ValueError("review_comment replies require in_reply_to")


def _gh_pr_view_json(fields: str, pr: str | None, repo: str | None) -> dict[str, Any]:
    cmd = ["gh", "pr", "view"]
    if pr:
        cmd.append(pr)
    if repo:
        cmd += ["--repo", repo]
    cmd += ["--json", fields]
    payload = _run_json(cmd)
    if not isinstance(payload, dict):
        raise RuntimeError("Expected object from `gh pr view --json`")
    return payload


def _get_pr_ref(pr: str | None, repo: str | None) -> RepoContext:
    pr_meta = _gh_pr_view_json("number,url,headRepositoryOwner,headRepository", pr, repo)
    number = int(pr_meta["number"])
    hostname = None
    owner = None
    name = None

    url = pr_meta.get("url") or ""
    parsed = _parse_pr_ref_from_url(url)
    if parsed:
        hostname, owner, name, parsed_number = parsed
        if parsed_number != number:
            raise RuntimeError(f"PR URL number mismatch: expected {number}, got {parsed_number}")

    repo_parts = _parse_repo_arg(repo)
    if repo_parts:
        repo_hostname, repo_owner, repo_name = repo_parts
        hostname = hostname or repo_hostname
        owner = owner or repo_owner
        name = name or repo_name

    if not owner or not name:
        owner = (pr_meta.get("headRepositoryOwner") or {}).get("login")
        name = (pr_meta.get("headRepository") or {}).get("name")

    if not owner or not name:
        raise RuntimeError("Unable to resolve PR repository owner/name.")
    return RepoContext(hostname=hostname or "github.com", owner=owner, repo=name, number=number)


def _post_issue_comment(ctx: RepoContext, body: str, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {
            "kind": "issue_comment",
            "status": "dry-run",
            "owner": ctx.owner,
            "repo": ctx.repo,
            "number": ctx.number,
        }

    result = _run_json(
        [
            "gh",
            "api",
            "--hostname",
            ctx.hostname,
            "-X",
            "POST",
            f"repos/{ctx.owner}/{ctx.repo}/issues/{ctx.number}/comments",
            "-f",
            f"body={body}",
        ]
    )
    if not isinstance(result, dict):
        raise RuntimeError("Expected object from issue comment create API")
    return {"kind": "issue_comment", "status": "posted", "url": result.get("html_url")}


def _resolve_review_comment_db_id(hostname: str, in_reply_to: str) -> int:
    if in_reply_to.isdigit():
        return int(in_reply_to)

    node = _expect_graphql_node(
        _run_json(
            [
                "gh",
                "api",
                "--hostname",
                hostname,
                "graphql",
                "-F",
                "query=@-",
                "-F",
                f"id={in_reply_to}",
            ],
            stdin=REVIEW_COMMENT_DB_ID_QUERY,
        ),
        context="Review comment lookup failed",
    )
    db_id = node.get("databaseId")
    if not db_id:
        raise RuntimeError(f"Unable to resolve databaseId for review comment: {in_reply_to}")
    return int(db_id)


def _fetch_review_comment_rest(ctx: RepoContext, comment_id: int) -> dict[str, Any]:
    result = _run_json(
        [
            "gh",
            "api",
            "--hostname",
            ctx.hostname,
            f"repos/{ctx.owner}/{ctx.repo}/pulls/comments/{comment_id}",
        ]
    )
    if not isinstance(result, dict):
        raise RuntimeError("Expected object from review comment lookup API")
    _ensure_target_matches_pr(
        ctx,
        pr_url=result.get("pull_request_url"),
        pr_number=ctx.number,
        target_kind="review comment",
        target_id=str(comment_id),
    )
    return result


def _resolve_root_review_comment_id(ctx: RepoContext, in_reply_to: str) -> str:
    if in_reply_to.isdigit():
        current_id = int(in_reply_to)
        for _ in range(25):
            comment = _fetch_review_comment_rest(ctx, current_id)
            reply_to_id = comment.get("in_reply_to_id")
            if not reply_to_id:
                node_id = comment.get("node_id")
                if not node_id:
                    raise RuntimeError(f"Unable to resolve node_id for review comment {current_id}")
                return str(node_id)
            current_id = int(reply_to_id)
        raise RuntimeError(f"Review comment reply chain too deep for comment {in_reply_to}")

    current_id = in_reply_to
    for _ in range(25):
        node = _expect_graphql_node(
            _run_json(
                [
                    "gh",
                    "api",
                    "--hostname",
                    ctx.hostname,
                    "graphql",
                    "-F",
                    "query=@-",
                    "-F",
                    f"id={current_id}",
                ],
                stdin=REVIEW_COMMENT_DB_ID_QUERY,
            ),
            context="Review comment root lookup failed",
        )
        pull_request = node.get("pullRequest") or {}
        _ensure_target_matches_pr(
            ctx,
            pr_url=pull_request.get("url"),
            pr_number=pull_request.get("number"),
            target_kind="review comment",
            target_id=current_id,
        )
        reply_to = (node.get("replyTo") or {}).get("id")
        if not reply_to:
            resolved_id = node.get("id")
            if not resolved_id:
                raise RuntimeError(f"Unable to resolve root review comment for {in_reply_to}")
            return str(resolved_id)
        current_id = str(reply_to)
    raise RuntimeError(f"Review comment reply chain too deep for comment {in_reply_to}")


def _fetch_thread_node(ctx: RepoContext, thread_id: str) -> dict[str, Any]:
    node = _expect_graphql_node(
        _run_json(
            [
                "gh",
                "api",
                "--hostname",
                ctx.hostname,
                "graphql",
                "-F",
                "query=@-",
                "-F",
                f"id={thread_id}",
            ],
            stdin=THREAD_CONTEXT_QUERY,
        ),
        context="Review thread lookup failed",
    )
    pull_request = node.get("pullRequest") or {}
    _ensure_target_matches_pr(
        ctx,
        pr_url=pull_request.get("url"),
        pr_number=pull_request.get("number"),
        target_kind="review thread",
        target_id=thread_id,
    )
    return node


def _ensure_thread_matches_comment(ctx: RepoContext, thread_id: str, reply_target_id: str) -> None:
    node = _fetch_thread_node(ctx, thread_id)
    thread_comment_ids = {
        str(comment.get("id"))
        for comment in (node.get("comments") or {}).get("nodes") or []
        if comment.get("id")
    }
    if reply_target_id not in thread_comment_ids:
        raise RuntimeError(
            f"Review thread {thread_id} does not contain reply target {reply_target_id}"
        )


def _post_review_reply(
    ctx: RepoContext,
    in_reply_to: str,
    body: str,
    resolve_thread_id: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        normalized_reply_target = in_reply_to
        if in_reply_to.isdigit():
            normalized_reply_target = str(in_reply_to)
        return {
            "kind": "review_comment",
            "status": "dry-run",
            "in_reply_to": in_reply_to,
            "normalized_in_reply_to": normalized_reply_target,
            "resolve_thread_id": resolve_thread_id,
        }

    root_reply_target = _resolve_root_review_comment_id(ctx, in_reply_to)
    payload: dict[str, Any] = {"kind": "review_comment", "status": "posted"}
    try:
        reply = _expect_graphql_success(
            _run_json(
                [
                    "gh",
                    "api",
                    "--hostname",
                    ctx.hostname,
                    "graphql",
                    "-F",
                    "query=@-",
                    "-F",
                    f"body={body}",
                    "-F",
                    f"inReplyTo={root_reply_target}",
                ],
                stdin=REPLY_MUTATION,
            ),
            context="GraphQL review reply failed",
        )
        comment = reply.get("data", {}).get("addPullRequestReviewComment", {}).get("comment", {})
        payload["url"] = comment.get("url")
    except RuntimeError as exc:
        db_id = _resolve_review_comment_db_id(ctx.hostname, root_reply_target)
        print(
            f"GraphQL review reply failed; falling back to REST for comment {db_id}: {exc}",
            file=sys.stderr,
        )
        _maybe_emit_permissions_hint(str(exc), context="GraphQL review reply failed")
        try:
            rest = _run_json(
                [
                    "gh",
                    "api",
                    "--hostname",
                    ctx.hostname,
                    "-X",
                    "POST",
                    f"repos/{ctx.owner}/{ctx.repo}/pulls/{ctx.number}/comments",
                    "-F",
                    f"in_reply_to={db_id}",
                    "-F",
                    f"body={body}",
                ]
            )
        except RuntimeError as exc:
            _maybe_emit_permissions_hint(str(exc), context="REST review reply failed")
            raise
        if not isinstance(rest, dict):
            raise RuntimeError("Expected object from REST review reply API")
        payload["url"] = rest.get("html_url")
        payload["fallback"] = "rest"

    if resolve_thread_id:
        try:
            _ensure_thread_matches_comment(ctx, resolve_thread_id, root_reply_target)
            resolved = _expect_graphql_success(
                _run_json(
                    [
                        "gh",
                        "api",
                        "--hostname",
                        ctx.hostname,
                        "graphql",
                        "-F",
                        "query=@-",
                        "-F",
                        f"threadId={resolve_thread_id}",
                    ],
                    stdin=RESOLVE_MUTATION,
                ),
                context="Resolve review thread failed",
            )
            thread = resolved.get("data", {}).get("resolveReviewThread", {}).get("thread", {})
            payload["resolved"] = bool(thread.get("isResolved"))
        except RuntimeError as exc:
            payload["resolved"] = False
            payload["resolve_error"] = str(exc)
            print(f"Failed to resolve review thread {resolve_thread_id}: {exc}", file=sys.stderr)

    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Reply to PR comments and review threads.")
    parser.add_argument("--replies", required=True, help="Path to replies JSON file")
    parser.add_argument("--pr", help="PR number or URL (defaults to current branch PR)")
    parser.add_argument("--repo", help="Override repo for gh commands (e.g. org/name)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print planned actions without posting"
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    parser.add_argument(
        "--allow-unprefixed",
        action="store_true",
        help=f"Allow reply bodies that do not start with {REQUIRED_PREFIX!r}",
    )
    args = parser.parse_args()

    replies = _load_replies(args.replies)
    for reply in replies:
        _validate_reply(reply, allow_unprefixed=args.allow_unprefixed)

    needs_pr_ref = any(
        reply.get("kind") in {"issue_comment", "review_comment"} for reply in replies
    )

    if not args.dry_run:
        _ensure_gh_authenticated()

    hostname = owner = repo = None
    number = None
    if needs_pr_ref and not args.dry_run:
        pr_ref = _get_pr_ref(args.pr, args.repo)
        hostname = pr_ref.hostname
        owner = pr_ref.owner
        repo = pr_ref.repo
        number = pr_ref.number
    elif needs_pr_ref and args.dry_run:
        hostname = owner = repo = "dry-run"
        number = 0

    results: list[dict[str, Any]] = []
    for reply in replies:
        ctx = RepoContext(hostname=hostname, owner=owner, repo=repo, number=number)
        kind = reply["kind"]
        body = reply["body"]
        if kind == "issue_comment":
            assert (
                hostname is not None
                and owner is not None
                and repo is not None
                and number is not None
            )
            results.append(_post_issue_comment(ctx, body, args.dry_run))
            continue

        assert (
            hostname is not None and owner is not None and repo is not None and number is not None
        )
        results.append(
            _post_review_reply(
                ctx=ctx,
                in_reply_to=reply["in_reply_to"],
                body=body,
                resolve_thread_id=reply.get("resolve_thread_id"),
                dry_run=args.dry_run,
            )
        )

    if args.json:
        print(json.dumps(results, indent=2))
        return

    for result in results:
        if result["kind"] == "issue_comment":
            url = result.get("url") or "(no url)"
            print(f"issue_comment: {result['status']} {url}")
            continue
        url = result.get("url") or "(no url)"
        resolved = result.get("resolved")
        suffix = f" resolved={resolved}" if resolved is not None else ""
        print(f"review_comment: {result['status']} {url}{suffix}")


if __name__ == "__main__":
    main()
