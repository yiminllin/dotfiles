#!/usr/bin/env python3
"""Fetch pull request conversation comments, reviews, and review threads.

Supports either the PR associated with the current branch or an explicit PR
number or URL.

The output includes helper lists for filtering resolved, outdated, and
dismissed feedback.

Usage examples:
  python fetch_comments.py > pr_comments.json
  python fetch_comments.py --pr 123 > pr_comments.json
  python fetch_comments.py --pr https://github.com/org/repo/pull/123 > pr_comments.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

QUERY = """\
query(
  $owner: String!,
  $repo: String!,
  $number: Int!,
  $commentsCursor: String,
  $reviewsCursor: String,
  $threadsCursor: String
) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      number
      url
      title
      state

      comments(first: 100, after: $commentsCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          body
          createdAt
          updatedAt
          author {
            __typename
            login
          }
        }
      }

      reviews(first: 100, after: $reviewsCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          state
          body
          submittedAt
          author {
            __typename
            login
          }
        }
      }

      reviewThreads(first: 100, after: $threadsCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          diffSide
          startLine
          startDiffSide
          originalLine
          originalStartLine
          resolvedBy {
            __typename
            login
          }
          comments(first: 100) {
            nodes {
              id
              replyTo { id }
              body
              createdAt
              updatedAt
              author {
                __typename
                login
              }
            }
          }
        }
      }
    }
  }
}
"""


@dataclass
class GraphQLCursors:
    comments: str | None = None
    reviews: str | None = None
    threads: str | None = None


@dataclass(frozen=True)
class PullRequestRef:
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


def _ensure_gh_authenticated() -> None:
    try:
        _run(["gh", "auth", "status"])
    except RuntimeError:
        print("run `gh auth login` to authenticate the GitHub CLI", file=sys.stderr)
        raise RuntimeError(
            "gh auth status failed; run `gh auth login` to authenticate the GitHub CLI"
        ) from None


def _normalize_hostname(hostname: str | None) -> str | None:
    if not hostname:
        return None
    if hostname == "api.github.com":
        return "github.com"
    return hostname


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


def _parse_pull_request_url(url: str) -> tuple[str, str, str, int] | None:
    parsed = urlparse(url)
    hostname = _normalize_hostname(parsed.hostname)
    if not hostname:
        return None

    match = re.match(r"^/([^/]+)/([^/]+)/pull/(\d+)(?:/.*)?$", parsed.path)
    if not match:
        return None
    owner, repo, number = match.groups()
    return hostname, owner, repo, int(number)


def _get_pr_ref(pr: str | None, repo: str | None) -> PullRequestRef:
    pr_meta = _gh_pr_view_json(
        "number,url,headRepositoryOwner,headRepository",
        pr,
        repo,
    )
    number = int(pr_meta["number"])
    hostname = None
    owner = None
    name = None

    url = pr_meta.get("url") or ""
    parsed = _parse_pull_request_url(url)
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
    return PullRequestRef(
        hostname=hostname or "github.com",
        owner=owner,
        repo=name,
        number=number,
    )


def _gh_api_graphql(
    pr_ref: PullRequestRef,
    cursors: GraphQLCursors,
) -> dict[str, Any]:
    cmd = [
        "gh",
        "api",
        "--hostname",
        pr_ref.hostname,
        "graphql",
        "-F",
        "query=@-",
        "-F",
        f"owner={pr_ref.owner}",
        "-F",
        f"repo={pr_ref.repo}",
        "-F",
        f"number={pr_ref.number}",
    ]
    if cursors.comments:
        cmd += ["-F", f"commentsCursor={cursors.comments}"]
    if cursors.reviews:
        cmd += ["-F", f"reviewsCursor={cursors.reviews}"]
    if cursors.threads:
        cmd += ["-F", f"threadsCursor={cursors.threads}"]
    payload = _run_json(cmd, stdin=QUERY)
    if not isinstance(payload, dict):
        raise RuntimeError("Expected object from `gh api graphql`")
    return payload


def _fetch_rest_paginated(hostname: str, path: str, per_page: int = 100) -> list[dict[str, Any]]:
    page = 1
    items: list[dict[str, Any]] = []
    while True:
        page_items = _run_json(
            [
                "gh",
                "api",
                "--hostname",
                hostname,
                f"{path}?per_page={per_page}&page={page}",
            ]
        )
        if not isinstance(page_items, list):
            raise RuntimeError(f"Expected list from gh api for path: {path}")
        if not page_items:
            break
        items.extend(page_items)
        if len(page_items) < per_page:
            break
        page += 1
    return items


def _fetch_review_comments_rest(pr_ref: PullRequestRef) -> list[dict[str, Any]]:
    comments = _fetch_rest_paginated(
        pr_ref.hostname,
        f"repos/{pr_ref.owner}/{pr_ref.repo}/pulls/{pr_ref.number}/comments",
    )
    return [_annotate_rest_author(comment) for comment in comments]


def _fetch_reviews_rest(pr_ref: PullRequestRef) -> list[dict[str, Any]]:
    reviews = _fetch_rest_paginated(
        pr_ref.hostname,
        f"repos/{pr_ref.owner}/{pr_ref.repo}/pulls/{pr_ref.number}/reviews",
    )
    return [_annotate_rest_author(review) for review in reviews]


def _author_type(author: dict[str, Any] | None) -> str | None:
    if not isinstance(author, dict):
        return None
    type_name = author.get("__typename")
    return type_name if isinstance(type_name, str) else None


def _author_login(author: dict[str, Any] | None) -> str | None:
    if not isinstance(author, dict):
        return None
    login = author.get("login")
    return login if isinstance(login, str) else None


def _author_kind(author: dict[str, Any] | None) -> str:
    type_name = _author_type(author)
    login = _author_login(author) or ""
    if type_name == "Bot" or login.endswith("[bot]"):
        return "bot"
    if type_name == "User":
        return "human"
    if type_name:
        return type_name.lower()
    return "unknown"


def _annotate_graphql_author(item: dict[str, Any]) -> dict[str, Any]:
    author = item.get("author")
    return {
        **item,
        "author_type": _author_type(author),
        "author_kind": _author_kind(author),
        "author_is_bot": _author_kind(author) == "bot",
    }


def _annotate_rest_author(item: dict[str, Any]) -> dict[str, Any]:
    user = item.get("user") if isinstance(item, dict) else None
    login = user.get("login") if isinstance(user, dict) else None
    user_type = user.get("type") if isinstance(user, dict) else None
    author_kind = "unknown"
    if isinstance(user_type, str):
        if user_type.lower() == "bot" or (isinstance(login, str) and login.endswith("[bot]")):
            author_kind = "bot"
        elif user_type.lower() == "user":
            author_kind = "human"
        else:
            author_kind = user_type.lower()
    return {
        **item,
        "author_type": user_type,
        "author_kind": author_kind,
        "author_is_bot": author_kind == "bot",
    }


def _thread_comment_nodes(thread: dict[str, Any]) -> list[dict[str, Any]]:
    return (thread.get("comments") or {}).get("nodes") or []


def _reply_target_id(thread: dict[str, Any]) -> str | None:
    comment_nodes = _thread_comment_nodes(thread)
    for comment in comment_nodes:
        if not (comment.get("replyTo") or {}).get("id"):
            comment_id = comment.get("id")
            return str(comment_id) if comment_id else None
    if not comment_nodes:
        return None
    fallback_id = comment_nodes[0].get("id")
    return str(fallback_id) if fallback_id else None


def _annotate_threads(review_threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated_threads: list[dict[str, Any]] = []
    for thread in review_threads:
        comment_nodes = [
            _annotate_graphql_author(comment) for comment in _thread_comment_nodes(thread)
        ]
        thread_author = comment_nodes[0].get("author") if comment_nodes else None
        annotated_threads.append(
            {
                **thread,
                "comments": {**(thread.get("comments") or {}), "nodes": comment_nodes},
                "reply_target_id": _reply_target_id(
                    {**thread, "comments": {"nodes": comment_nodes}}
                ),
                "thread_author_type": _author_type(thread_author),
                "thread_author_kind": _author_kind(thread_author),
            }
        )
    return annotated_threads


def fetch_all(pr_ref: PullRequestRef) -> dict[str, Any]:
    conversation_comments: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    review_threads: list[dict[str, Any]] = []
    cursors = GraphQLCursors()
    comments_done = False
    reviews_done = False
    threads_done = False
    pr_meta: dict[str, Any] | None = None

    while True:
        payload = _gh_api_graphql(pr_ref=pr_ref, cursors=cursors)
        if payload.get("errors"):
            raise RuntimeError(f"GitHub GraphQL errors:\n{json.dumps(payload['errors'], indent=2)}")

        pr = payload["data"]["repository"]["pullRequest"]
        if pr_meta is None:
            pr_meta = {
                "number": pr["number"],
                "url": pr["url"],
                "title": pr["title"],
                "state": pr["state"],
                "hostname": pr_ref.hostname,
                "owner": pr_ref.owner,
                "repo": pr_ref.repo,
            }

        comments_payload = pr["comments"]
        reviews_payload = pr["reviews"]
        threads_payload = pr["reviewThreads"]

        if not comments_done:
            conversation_comments.extend(
                [_annotate_graphql_author(node) for node in (comments_payload.get("nodes") or [])]
            )
            comments_done = not comments_payload["pageInfo"]["hasNextPage"]
            cursors.comments = None if comments_done else comments_payload["pageInfo"]["endCursor"]

        if not reviews_done:
            reviews.extend(
                [_annotate_graphql_author(node) for node in (reviews_payload.get("nodes") or [])]
            )
            reviews_done = not reviews_payload["pageInfo"]["hasNextPage"]
            cursors.reviews = None if reviews_done else reviews_payload["pageInfo"]["endCursor"]

        if not threads_done:
            review_threads.extend(threads_payload.get("nodes") or [])
            threads_done = not threads_payload["pageInfo"]["hasNextPage"]
            cursors.threads = None if threads_done else threads_payload["pageInfo"]["endCursor"]

        if comments_done and reviews_done and threads_done:
            break

    if pr_meta is None:
        raise RuntimeError("Failed to fetch PR metadata.")

    review_threads = _annotate_threads(review_threads)
    review_comments = _fetch_review_comments_rest(pr_ref)
    reviews_rest = _fetch_reviews_rest(pr_ref)
    review_threads_unresolved = [
        thread
        for thread in review_threads
        if not thread.get("isResolved") and not thread.get("isOutdated")
    ]
    review_threads_resolved = [thread for thread in review_threads if thread.get("isResolved")]
    review_threads_outdated = [thread for thread in review_threads if thread.get("isOutdated")]
    review_comments_outdated = [
        comment for thread in review_threads_outdated for comment in _thread_comment_nodes(thread)
    ]
    reviews_dismissed = [review for review in reviews_rest if review.get("state") == "DISMISSED"]
    reviews_active = [review for review in reviews_rest if review.get("state") != "DISMISSED"]

    return {
        "pull_request": pr_meta,
        "conversation_comments": conversation_comments,
        "reviews": reviews,
        "review_threads": review_threads,
        "review_comments": review_comments,
        "reviews_rest": reviews_rest,
        "review_threads_unresolved": review_threads_unresolved,
        "review_threads_resolved": review_threads_resolved,
        "review_threads_outdated": review_threads_outdated,
        "review_comments_outdated": review_comments_outdated,
        "reviews_dismissed": reviews_dismissed,
        "reviews_active": reviews_active,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch pull request comments, reviews, and review threads."
    )
    parser.add_argument("--pr", help="PR number or URL (defaults to current branch PR)")
    parser.add_argument("--repo", help="Override repo for gh commands (e.g. org/name)")
    args = parser.parse_args()

    _ensure_gh_authenticated()
    pr_ref = _get_pr_ref(args.pr, args.repo)
    result = fetch_all(pr_ref)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
