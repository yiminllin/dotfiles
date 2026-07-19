from __future__ import annotations

from pathlib import Path

from .models import DEFAULT_REPO, Source
from .parsing import normalize_s3_reference, parse_github_actions_url


def normalize_source(raw_target: str, repo: str = DEFAULT_REPO, job: str | None = None) -> Source:
    target = raw_target.strip()
    selected_job = parse_job_selector(job) if job else None

    parsed = parse_github_actions_url(target)
    if parsed:
        run_id = str(parsed["run_id"])
        if selected_job:
            validate_selected_job(selected_job, repo=str(parsed["repo"]), run_id=run_id, target_job_id=parsed.get("job_id"))
        job_id = parsed.get("job_id") or (selected_job or {}).get("job_id")
        return Source(
            kind="github_job" if job_id else "github_run",
            input=target,
            repo=str(parsed["repo"]),
            run_id=run_id,
            job_id=str(job_id) if job_id else None,
        )

    if target.isdigit():
        if selected_job:
            validate_selected_job(selected_job, repo=repo, run_id=target)
        return Source(
            kind="github_job" if selected_job else "github_run",
            input=target,
            repo=repo,
            run_id=target,
            job_id=(selected_job or {}).get("job_id"),
        )

    path = Path(target).expanduser()
    if path.exists():
        if not path.is_file():
            raise ValueError(f"local path is not a file: {path}")
        return Source(kind="local_path", input=target, local_path=str(path))

    if looks_like_s3_reference(target):
        return Source(kind="s3", input=target, s3_uri=normalize_s3_reference(target))

    raise ValueError("target must be a GitHub Actions run/job URL, bare run id, S3 reference, or existing local path")


def parse_job_selector(raw_job: str | None) -> dict[str, str] | None:
    if not raw_job:
        return None
    raw_job = raw_job.strip()
    if raw_job.isdigit():
        return {"job_id": raw_job}
    parsed = parse_github_actions_url(raw_job)
    if parsed and parsed.get("job_id"):
        return {"repo": str(parsed["repo"]), "run_id": str(parsed["run_id"]), "job_id": str(parsed["job_id"])}
    raise ValueError("--job must be a numeric job id or GitHub Actions job URL")


def validate_selected_job(selected_job: dict[str, str], repo: str, run_id: str, target_job_id: str | None = None) -> None:
    if selected_job.get("repo") and selected_job["repo"] != repo:
        raise ValueError("--job URL repo does not match target repo")
    if selected_job.get("run_id") and selected_job["run_id"] != run_id:
        raise ValueError("--job URL run id does not match target run id")
    if target_job_id and selected_job.get("job_id") != target_job_id:
        raise ValueError("--job does not match target job id")


def looks_like_s3_reference(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered.startswith("s3://")
        or "s3.console.aws.amazon.com/s3/buckets/" in lowered
        or lowered.startswith("platform2-testing-logs/")
        or lowered.startswith("p2-zip-system-hil/")
    )
