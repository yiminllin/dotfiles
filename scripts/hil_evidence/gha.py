from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from .models import DEFAULT_REPO, DEFAULT_WORKFLOW, DEFAULT_WORKFLOW_TITLE, JsonDict
from .presets import PRESET_CONFIGS, preset_matches, preset_test_record_query, resolve_preset


UTC = timezone.utc
DEFAULT_RECENT_LIMIT = 100
DEFAULT_RECENT_LOOKBACK_HOURS = 72.0
AUTOKIOSK_RECENT_LIMIT = 1000
AUTOKIOSK_RECENT_LOOKBACK_HOURS = 3000.0
HIL_TEST_JOB_MARKER = "HIL Test:"

RUN_FIELDS = (
    "conclusion",
    "createdAt",
    "databaseId",
    "displayTitle",
    "event",
    "headBranch",
    "headSha",
    "status",
    "updatedAt",
    "url",
    "workflowName",
)
RUN_VIEW_FIELDS = RUN_FIELDS + ("jobs",)

@dataclass
class CommandFailure(Exception):
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    def __str__(self) -> str:
        return f"{shlex.join(self.command)} exited {self.returncode}"


def effective_recent_limit(preset: str | None, limit: int | None) -> int:
    if limit is not None:
        return limit
    if is_autokiosk_preset(preset):
        return AUTOKIOSK_RECENT_LIMIT
    return DEFAULT_RECENT_LIMIT


def effective_recent_lookback_hours(preset: str | None, lookback_hours: float | None) -> float:
    if lookback_hours is not None:
        return lookback_hours
    if is_autokiosk_preset(preset):
        return AUTOKIOSK_RECENT_LOOKBACK_HOURS
    return DEFAULT_RECENT_LOOKBACK_HOURS


def is_autokiosk_preset(preset: str | None) -> bool:
    resolved = resolve_preset(preset)
    return bool(resolved and resolved.name == "zip_autokiosk")


def recent_since(lookback_hours: float) -> datetime:
    return datetime.now(UTC) - timedelta(hours=lookback_hours)


def list_recent_hil_candidates(
    *,
    repo: str = DEFAULT_REPO,
    preset: str | None = None,
    passing: bool = False,
    max_matches: int | None = None,
    limit: int | None = None,
    lookback_hours: float | None = None,
    job_name: str | None = None,
    title: str | None = None,
    branch: str | None = None,
    status: list[str] | None = None,
    conclusion: list[str] | None = None,
) -> tuple[list[JsonDict], list[JsonDict], JsonDict]:
    effective_limit = effective_recent_limit(preset, limit)
    effective_lookback = effective_recent_lookback_hours(preset, lookback_hours)
    query = {
        "repo": repo,
        "workflow": DEFAULT_WORKFLOW,
        "workflow_title": DEFAULT_WORKFLOW_TITLE,
        "preset": preset,
        "passing": passing,
        "limit": effective_limit,
        "lookback_hours": effective_lookback,
        "max_matches": max_matches,
        "job_name": job_name,
        "title": title,
        "branch": branch,
        "status": status or [],
        "conclusion": conclusion or [],
    }
    since = recent_since(effective_lookback)
    args = filter_args(
        preset=preset,
        passing=passing,
        limit=query["limit"],
        job_name=job_name,
        title=title,
        branch=branch,
        status=status,
        conclusion=conclusion,
    )
    try:
        runs = list_runs(repo, int(query["limit"]))
    except CommandFailure as exc:
        return [], [command_error("github", "gh run list failed", exc)], query

    matches: list[JsonDict] = []
    errors: list[JsonDict] = []
    for run in runs:
        if max_matches is not None and len(matches) >= max_matches:
            break
        if not isinstance(run, dict) or not run_matches(run, args, since):
            continue
        run_id = str(run.get("databaseId") or "")
        if not run_id:
            continue
        try:
            run_view = view_run(repo, run_id)
        except CommandFailure as exc:
            errors.append(command_error("github", f"gh run view {run_id} failed", exc))
            continue
        merged_run = {**run, **{key: value for key, value in run_view.items() if value is not None}}
        for job in run_view.get("jobs") or []:
            if max_matches is not None and len(matches) >= max_matches:
                break
            if isinstance(job, dict) and job_matches(job, args, None):
                matches.append(candidate_from_job(repo, merged_run, job))

    matches.sort(key=candidate_sort_key, reverse=True)
    query["candidate_count"] = len(matches)
    return matches, errors, query


def is_real_hil_job(job: JsonDict) -> bool:
    return is_real_hil_test_job(job)


def list_run_hil_candidates(run: JsonDict, repo: str, preset: str | None = None, passing: bool = False) -> list[JsonDict]:
    args = filter_args(preset=preset, passing=passing)
    candidates = []
    for job in run.get("jobs") or []:
        if isinstance(job, dict) and job_matches(job, args, None):
            candidates.append(candidate_from_job(repo, run, job))
    candidates.sort(key=candidate_sort_key, reverse=True)
    return candidates


def filter_args(
    preset: str | None = None,
    passing: bool = False,
    limit: int = DEFAULT_RECENT_LIMIT,
    job_name: str | None = None,
    title: str | None = None,
    branch: str | None = None,
    status: list[str] | None = None,
    conclusion: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        preset=preset,
        branch=branch,
        title=title,
        job_name=job_name,
        status=status or [],
        conclusion=conclusion or [],
        passing=passing,
        limit=limit,
    )


def run_matches(run: JsonDict, args: SimpleNamespace, since: datetime) -> bool:
    created_at = optional_datetime(run.get("createdAt"))
    if created_at is None or created_at < since:
        return False
    if args.preset and not preset_matches(run.get("displayTitle"), args.preset, "run_title_fragments"):
        return False
    if args.branch and not contains_case_insensitive(run.get("headBranch"), args.branch):
        return False
    if args.title and not contains_case_insensitive(run.get("displayTitle"), args.title):
        return False
    return True


def job_matches(job: JsonDict, args: SimpleNamespace, job_regex: re.Pattern[str] | None) -> bool:
    name_text = job_search_text(job)
    if not is_real_hil_test_job(job):
        return False
    if args.preset and not preset_matches(name_text, args.preset, "job_name_fragments"):
        return False
    if args.job_name and args.job_name.lower() not in name_text.lower():
        return False
    if job_regex and not job_regex.search(name_text):
        return False

    wanted_statuses = normalized_set(args.status)
    wanted_conclusions = normalized_set(args.conclusion)
    if args.passing:
        wanted_statuses.add("completed")
        wanted_conclusions.add("success")

    status = normalize(job.get("status"))
    conclusion = normalize(job.get("conclusion"))
    if wanted_statuses and status not in wanted_statuses:
        return False
    if wanted_conclusions and conclusion not in wanted_conclusions:
        return False
    return True


def is_real_hil_test_job(job: JsonDict) -> bool:
    name_text = job_search_text(job)
    if HIL_TEST_JOB_MARKER.lower() not in name_text.lower():
        return False
    if is_hil_meta_job_name(name_text):
        return False
    return normalize(job.get("status")) != "skipped" and normalize(job.get("conclusion")) != "skipped"


def candidate_from_job(repo: str, run: JsonDict, job: JsonDict) -> JsonDict:
    run_id = required_text(run, "databaseId", "run")
    job_id = required_text(job, "databaseId", "job")
    job_url = str(job.get("url") or f"https://github.com/{repo}/actions/runs/{run_id}/job/{job_id}")
    return {
        "job_url": job_url,
        "gha_url": job_url,
        "run_id": run_id,
        "attempt": run.get("attempt"),
        "job_id": job_id,
        "job_name": job.get("name"),
        "job_status": job.get("status"),
        "job_conclusion": job.get("conclusion"),
        "branch": run.get("headBranch"),
        "title": run.get("displayTitle"),
        "event": run.get("event"),
        "workflow": run.get("workflowName"),
        "head_sha": run.get("headSha"),
        "run_status": run.get("status"),
        "run_conclusion": run.get("conclusion"),
        "run_created_at": run.get("createdAt"),
        "run_updated_at": run.get("updatedAt"),
        "run_url": run.get("url"),
        "job_started_at": job.get("startedAt"),
        "job_completed_at": job.get("completedAt"),
    }


def candidate_sort_key(candidate: JsonDict) -> tuple[str, str, str]:
    return (
        str(candidate.get("run_created_at") or ""),
        str(candidate.get("job_started_at") or ""),
        str(candidate.get("job_id") or ""),
    )


def job_search_text(job: JsonDict) -> str:
    return " ".join(str(value) for value in job_name_values(job) if value not in (None, ""))


def job_name_values(job: JsonDict) -> tuple[Any, ...]:
    return (job.get("name"), job_display_name(job))


def job_display_name(job: JsonDict) -> str | None:
    for key in ("displayName", "display_name", "displayTitle"):
        value = job.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def is_hil_meta_job_name(name: str) -> bool:
    after_marker = name.lower().split(HIL_TEST_JOB_MARKER.lower(), 1)[-1]
    return bool(re.search(r"\bmeta(?:[-_ ]?job)?\b", after_marker))


def optional_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value)
    normalized = f"{raw[:-1]}+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def required_text(data: JsonDict, key: str, label: str) -> str:
    value = data.get(key)
    if value in (None, ""):
        raise CommandFailure([], 1, "", f"malformed GitHub {label}: missing {key}")
    return str(value)


def normalized_set(values: list[str]) -> set[str]:
    return {normalize(value) for value in values if normalize(value)}


def normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def contains_case_insensitive(value: Any, query: str) -> bool:
    return query.lower() in str(value or "").lower()


def list_runs(repo: str, limit: int) -> list[JsonDict]:
    command = [
        "gh",
        "run",
        "list",
        "--repo",
        repo,
        "--limit",
        str(limit),
        "--workflow",
        DEFAULT_WORKFLOW,
        "--json",
        ",".join(RUN_FIELDS),
    ]
    output = run_json(command)
    return output if isinstance(output, list) else []


def view_run(repo: str, run_id: str) -> JsonDict:
    output = run_json([
        "gh",
        "run",
        "view",
        str(run_id),
        "--repo",
        repo,
        "--json",
        ",".join(RUN_VIEW_FIELDS),
    ])
    return output if isinstance(output, dict) else {}


def job_api(repo: str, job_id: str) -> JsonDict:
    output = run_json(["gh", "api", f"repos/{repo}/actions/jobs/{job_id}"])
    return output if isinstance(output, dict) else {}


def job_log(repo: str, job_id: str, run_id: str | None = None) -> str:
    try:
        return run_text(["gh", "api", f"repos/{repo}/actions/jobs/{job_id}/logs"])
    except CommandFailure:
        if not run_id:
            raise
    return run_text(["gh", "run", "view", str(run_id), "--repo", repo, "--job", str(job_id), "--log"])


def run_json(command: list[str]) -> Any:
    output = run_text(command)
    try:
        return json.loads(output or "null")
    except json.JSONDecodeError as exc:
        raise CommandFailure(command, 0, output, f"failed to parse JSON stdout: {exc}") from exc


def run_text(command: list[str], timeout_seconds: int = 120) -> str:
    if command and command[0] == "gh" and shutil.which("gh") is None:
        raise CommandFailure(command, 127, "", "gh CLI not found on PATH")
    try:
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise CommandFailure(command, 124, timeout_output(exc.stdout), f"command timed out after {timeout_seconds}s") from exc
    if completed.returncode != 0:
        raise CommandFailure(command, completed.returncode, completed.stdout, completed.stderr)
    return completed.stdout


def command_error(tool: str, message: str, exc: CommandFailure) -> JsonDict:
    error: JsonDict = {
        "tool": tool,
        "message": message,
        "command": shlex.join(exc.command),
        "returncode": exc.returncode,
    }
    if exc.stderr.strip():
        error["stderr_excerpt"] = excerpt(exc.stderr)
    if exc.stdout.strip():
        error["stdout_excerpt"] = excerpt(exc.stdout)
    guidance = auth_guidance(tool, exc.stderr)
    if guidance:
        error["guidance"] = guidance
    return error


def normalize_run(raw: JsonDict) -> JsonDict:
    return {
        "run_id": raw.get("databaseId"),
        "url": raw.get("url"),
        "title": raw.get("displayTitle"),
        "workflow": raw.get("workflowName"),
        "event": raw.get("event"),
        "branch": raw.get("headBranch"),
        "head_sha": raw.get("headSha"),
        "status": raw.get("status"),
        "conclusion": raw.get("conclusion"),
        "created_at": raw.get("createdAt"),
        "updated_at": raw.get("updatedAt"),
    }


def normalize_job(raw: JsonDict, repo: str | None = None, run_id: str | None = None) -> JsonDict:
    job_id = raw.get("id") or raw.get("databaseId")
    html_url = raw.get("html_url") or raw.get("url")
    if not html_url and repo and run_id and job_id:
        html_url = f"https://github.com/{repo}/actions/runs/{run_id}/job/{job_id}"
    return {
        "job_id": job_id,
        "run_id": raw.get("run_id") or run_id,
        "run_attempt": raw.get("run_attempt"),
        "name": raw.get("name"),
        "status": raw.get("status"),
        "conclusion": raw.get("conclusion"),
        "runner_name": raw.get("runner_name"),
        "started_at": raw.get("started_at") or raw.get("startedAt"),
        "completed_at": raw.get("completed_at") or raw.get("completedAt"),
        "url": html_url,
    }


def auth_guidance(tool: str, stderr: str) -> str | None:
    text = stderr.lower()
    if tool == "github" and any(token in text for token in ("auth", "login", "oauth", "401", "403", "not logged")):
        return "Authenticate GitHub CLI outside this helper: gh auth login"
    return None


def excerpt(text: str, limit: int = 2000) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "\n...<truncated>"


def timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
