from __future__ import annotations

from pathlib import Path
from typing import Any

from . import artifacts, gha, test_record
from .log_summary import summarize_log
from .models import DEFAULT_REPO, JsonDict, Packet, Source
from .parsing import is_test_record_uri
from .sources import normalize_source


def build_summary_packet(
    target: str,
    *,
    repo: str = DEFAULT_REPO,
    job: str | None = None,
    preset: str | None = None,
    passing: bool = False,
    max_jobs: int = 20,
    max_inventory_items: int = 500,
    max_test_records: int = 20,
) -> JsonDict:
    try:
        source = normalize_source(target, repo=repo, job=job)
    except ValueError as exc:
        packet = Packet(mode="summarize", status="error")
        packet.errors.append({"tool": "input", "message": str(exc)})
        return packet.to_dict()

    packet = Packet(mode="summarize", source=source, query={"preset": preset, "passing": passing})
    if source.kind in {"github_run", "github_job"}:
        summarize_github_source(packet, source, preset, passing, max_jobs, max_inventory_items, max_test_records)
    elif source.kind == "s3":
        summarize_s3_source(packet, source, max_inventory_items, max_test_records, gha.preset_test_record_query(preset), exact_query=bool(preset))
    elif source.kind == "local_path":
        summarize_local_source(packet, source, gha.preset_test_record_query(preset), exact_query=bool(preset))
    finalize_packet(packet)
    return packet.to_dict()


def build_recent_packet(
    *,
    repo: str = DEFAULT_REPO,
    preset: str | None = None,
    passing: bool = False,
    max_matches: int = 10,
    limit: int | None = None,
    lookback_hours: float | None = None,
    job_name: str | None = None,
    title: str | None = None,
    branch: str | None = None,
    status: list[str] | None = None,
    conclusion: list[str] | None = None,
    test_record_query: str | None = None,
    max_inventory_items: int = 500,
    max_test_records: int = 20,
) -> JsonDict:
    resolved_test_record_query = test_record_query or gha.preset_test_record_query(preset)
    exact_test_record_query = bool(resolved_test_record_query and preset and not test_record_query)
    candidates, errors, query = gha.list_recent_hil_candidates(
        repo=repo,
        preset=preset,
        passing=passing,
        max_matches=None if resolved_test_record_query else max_matches,
        limit=limit,
        lookback_hours=lookback_hours,
        job_name=job_name,
        title=title,
        branch=branch,
        status=status,
        conclusion=conclusion,
    )
    query["test_record_query"] = resolved_test_record_query
    query["test_record_query_source"] = "explicit" if test_record_query else "preset" if resolved_test_record_query else None
    query["test_record_query_match_mode"] = "exact" if exact_test_record_query else "substring" if resolved_test_record_query else None
    if resolved_test_record_query:
        query["requested_max_matches"] = max_matches
    packet = Packet(mode="recent", query=query, status="running")
    packet.candidates = [] if resolved_test_record_query else candidates
    packet.errors.extend(errors)
    if preset:
        packet.confidence.append(
            f"Applied GitHub run/job preset prefilters for {preset!r}; returned jobs require matching test_record evidence."
        )
    confirmed_count = 0
    searched_count = 0
    for candidate in candidates:
        if not resolved_test_record_query and searched_count >= max_matches:
            break
        job_entry = summarize_candidate(
            packet,
            repo,
            candidate,
            max_inventory_items,
            max_test_records,
            resolved_test_record_query,
            test_record_query_exact=exact_test_record_query,
        )
        searched_count += 1
        if resolved_test_record_query and job_entry and job_has_test_record_query_match(job_entry):
            confirmed_count += 1
            if confirmed_count >= max_matches:
                break
    if resolved_test_record_query:
        keep_recent_jobs_confirmed_by_test_record(packet, candidates, resolved_test_record_query, max_matches, searched_count)
    if not candidates and not errors:
        packet.status = "no_matches"
        packet.next_steps.append("Broaden lookback or limit, or remove preset/passing filters.")
    finalize_packet(packet)
    return packet.to_dict()


def summarize_github_source(
    packet: Packet,
    source: Source,
    preset: str | None,
    passing: bool,
    max_jobs: int,
    max_inventory_items: int,
    max_test_records: int,
) -> None:
    repo = source.repo or DEFAULT_REPO
    if source.run_id:
        try:
            run = gha.view_run(repo, source.run_id)
        except gha.CommandFailure as exc:
            packet.errors.append(gha.command_error("github", f"gh run view {source.run_id} failed", exc))
            packet.status = "error"
            return
        packet.github["run"] = gha.normalize_run(run)
    else:
        run = {}

    if source.job_id:
        candidate = {"run_id": source.run_id, "job_id": source.job_id, "job_url": github_job_url(repo, source.run_id, source.job_id)}
        summarize_candidate(
            packet,
            repo,
            candidate,
            max_inventory_items,
            max_test_records,
            gha.preset_test_record_query(preset),
            test_record_query_exact=bool(preset),
            require_job_metadata=True,
        )
        return

    candidates = gha.list_run_hil_candidates(run, repo, preset=preset, passing=passing)
    packet.candidates = candidates
    if not candidates:
        packet.status = "no_matches"
        packet.confidence.append("No non-skipped jobs matching the real HIL job filter were found in this run.")
        return
    if len(candidates) > 1:
        packet.ambiguity.append(f"Run contains {len(candidates)} matching HIL jobs; processed up to {max_jobs} without selecting one silently.")
    for candidate in candidates[:max_jobs]:
        summarize_candidate(
            packet,
            repo,
            candidate,
            max_inventory_items,
            max_test_records,
            gha.preset_test_record_query(preset),
            test_record_query_exact=bool(preset),
        )
    if len(candidates) > max_jobs:
        packet.ambiguity.append(f"Skipped {len(candidates) - max_jobs} additional HIL jobs due to --max-jobs bound.")


def summarize_candidate(
    packet: Packet,
    repo: str,
    candidate: JsonDict,
    max_inventory_items: int,
    max_test_records: int,
    test_record_query: str | None,
    test_record_query_exact: bool = False,
    require_job_metadata: bool = False,
) -> JsonDict | None:
    run_id = str(candidate.get("run_id") or "")
    job_id = str(candidate.get("job_id") or "")
    if not job_id:
        packet.errors.append({"tool": "github", "message": "candidate is missing job_id", "candidate": candidate})
        return None

    job_entry: JsonDict = {"candidate": candidate, "github": {}, "s3": {}, "test_records": [], "blockers": []}
    try:
        job_meta = gha.job_api(repo, job_id)
        job_entry["github"]["job"] = gha.normalize_job(job_meta, repo=repo, run_id=run_id)
    except gha.CommandFailure as exc:
        job_entry["blockers"].append(gha.command_error("github", f"gh job API failed for {job_id}", exc))
        if require_job_metadata:
            packet.jobs.append(job_entry)
            return job_entry
        job_meta = {}
    if job_meta and not gha.is_real_hil_job(job_meta):
        job_entry["blockers"].append(
            {
                "tool": "github",
                "message": "selected job does not match the non-skipped real HIL job filter; evidence collection stopped for this job",
            }
        )
        packet.jobs.append(job_entry)
        return job_entry
    job_run_id = str(job_meta.get("run_id") or "")
    if run_id and job_run_id and job_run_id != run_id:
        error = {
            "tool": "github",
            "message": f"job {job_id} belongs to run {job_run_id}, not target run {run_id}; refusing to mix evidence",
        }
        packet.errors.append(error)
        job_entry["blockers"].append(error)
        packet.jobs.append(job_entry)
        return job_entry

    try:
        log_text = gha.job_log(repo, job_id, run_id=run_id or None)
    except gha.CommandFailure as exc:
        job_entry["blockers"].append(gha.command_error("github", f"gh job log failed for {job_id}", exc))
        packet.jobs.append(job_entry)
        return job_entry

    log_summary = summarize_log(log_text)
    runner_name = str(job_meta.get("runner_name") or "")
    s3_evidence = artifacts.evidence_from_log(log_text, runner_name=runner_name)
    inventories, inventory_blockers = artifacts.inventory_roots(s3_evidence["roots"], max_items=max_inventory_items)
    record_uris = artifacts.test_record_uris(s3_evidence["roots"], inventories)
    record_summaries, record_blockers = test_record.summarize_s3_test_records(
        record_uris,
        query=test_record_query,
        max_records=max_test_records,
        exact_query=test_record_query_exact,
    )

    job_entry["log_summary"] = log_summary
    job_entry["s3"] = {**s3_evidence, "inventories": inventory_summaries(inventories), "test_record_uris": record_uris}
    job_entry["test_records"] = record_summaries
    job_entry["blockers"].extend(inventory_blockers + record_blockers)
    packet.jobs.append(job_entry)
    return job_entry


def keep_recent_jobs_confirmed_by_test_record(
    packet: Packet,
    metadata_candidates: list[JsonDict],
    query: str,
    max_matches: int,
    searched_count: int,
) -> None:
    original_jobs = packet.jobs
    confirmed_jobs = [job for job in original_jobs if job_has_test_record_query_match(job)]
    blocked_unconfirmed_jobs = [job for job in original_jobs if job not in confirmed_jobs and job.get("blockers")]

    for job in confirmed_jobs:
        mark_test_record_confirmation(job, query, "confirmed", "test_record.json matched query")
    for job in blocked_unconfirmed_jobs:
        mark_test_record_confirmation(job, query, "unconfirmed", "test_record confirmation was blocked")

    selected_confirmed_jobs = confirmed_jobs[:max_matches]
    selected_blocked_jobs = blocked_unconfirmed_jobs[: max(0, max_matches - len(selected_confirmed_jobs))]
    packet.jobs = selected_confirmed_jobs + selected_blocked_jobs
    selected_job_ids = {str((job.get("candidate") or {}).get("job_id") or "") for job in packet.jobs}
    packet.candidates = [candidate for candidate in metadata_candidates if str(candidate.get("job_id") or "") in selected_job_ids]
    mark_selected_candidates(packet.candidates, packet.jobs)
    packet.query["metadata_candidate_count"] = len(metadata_candidates)
    packet.query["searched_candidate_count"] = searched_count
    packet.query["confirmed_test_record_match_count"] = len(confirmed_jobs)
    packet.query["unconfirmed_candidate_count"] = len(blocked_unconfirmed_jobs)
    packet.query["negative_candidate_count"] = max(0, searched_count - len(confirmed_jobs) - len(blocked_unconfirmed_jobs))

    skipped = packet.query["negative_candidate_count"]
    if skipped:
        packet.ambiguity.append(
            f"Skipped {skipped} metadata-matched candidate(s) because no test_record.json matched {query!r}."
        )
    if confirmed_jobs:
        if selected_blocked_jobs:
            packet.ambiguity.append(
                f"Included {len(selected_blocked_jobs)} unconfirmed candidate(s) because blockers prevented test_record confirmation."
            )
        return
    if blocked_unconfirmed_jobs:
        packet.status = "partial"
        packet.next_steps.append(
            f"Resolve listed blockers to confirm whether unconfirmed candidates match {query!r}."
        )
        return

    if packet.errors:
        packet.status = "error"
    else:
        packet.status = "no_matches"
    packet.next_steps.append(
        f"Broaden recent-run filters or inspect S3/test_record access; no candidate was confirmed by {query!r}."
    )


def mark_test_record_confirmation(job: JsonDict, query: str, status: str, reason: str) -> None:
    job["test_record_confirmation"] = {"query": query, "status": status, "reason": reason}


def mark_selected_candidates(candidates: list[JsonDict], jobs: list[JsonDict]) -> None:
    status_by_job_id = {
        str((job.get("candidate") or {}).get("job_id") or ""): job.get("test_record_confirmation")
        for job in jobs
    }
    for candidate in candidates:
        confirmation = status_by_job_id.get(str(candidate.get("job_id") or ""))
        if confirmation:
            candidate["test_record_confirmation"] = confirmation


def job_has_test_record_query_match(job: JsonDict) -> bool:
    return any(record.get("query_matches") for record in job.get("test_records") or [])


def summarize_s3_source(
    packet: Packet,
    source: Source,
    max_inventory_items: int,
    max_test_records: int,
    query: str | None,
    exact_query: bool = False,
) -> None:
    root = source.s3_uri or ""
    inventories, blockers = artifacts.inventory_roots([root], max_items=max_inventory_items)
    record_uris = artifacts.test_record_uris([root], inventories)
    records, record_blockers = test_record.summarize_s3_test_records(record_uris, query=query, max_records=max_test_records, exact_query=exact_query)
    packet.s3 = {"roots": [root], "inventories": inventory_summaries(inventories), "test_record_uris": record_uris}
    packet.test_records = records
    packet.blockers.extend(blockers + record_blockers)


def summarize_local_source(packet: Packet, source: Source, query: str | None, exact_query: bool = False) -> None:
    path = source.local_path or ""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if path.endswith("test_record.json") or is_test_record_uri(path):
        summary, error = test_record.summarize_local_test_record(path, query=query, exact_query=exact_query)
        if summary:
            packet.test_records.append(summary)
        if error:
            packet.errors.append(error)
        return
    packet.log_summary = summarize_log(text)


def inventory_summaries(inventories: list[JsonDict]) -> list[JsonDict]:
    summaries = []
    for inventory in inventories:
        summary = {
            "s3_uri": inventory.get("s3_uri"),
            "count": inventory.get("count"),
            "total_size": inventory.get("total_size"),
            "truncated": inventory.get("truncated"),
            "key_artifact_hints": inventory.get("key_artifact_hints") or [],
            "test_record_artifacts": inventory.get("test_record_artifacts") or [],
        }
        baraza = inventory.get("baraza") or {}
        if any(baraza.get(key) for key in ("links", "flight_ids", "mission_ids", "candidates")):
            summary["baraza"] = baraza
        summaries.append(summary)
    return summaries


def finalize_packet(packet: Packet) -> None:
    for job in packet.jobs:
        packet.blockers.extend(job.get("blockers") or [])
        packet.next_steps.extend((job.get("log_summary") or {}).get("next_step_hints") or [])
    if packet.log_summary:
        packet.next_steps.extend(packet.log_summary.get("next_step_hints") or [])
    packet.next_steps = unique(packet.next_steps)
    if packet.status == "running":
        if packet.errors:
            packet.status = "error"
        elif packet.blockers:
            packet.status = "partial"
        else:
            packet.status = "ok"


def github_job_url(repo: str, run_id: Any, job_id: Any) -> str:
    if run_id:
        return f"https://github.com/{repo}/actions/runs/{run_id}/job/{job_id}"
    return f"https://github.com/{repo}/actions/jobs/{job_id}"


def unique(values: list[str]) -> list[str]:
    result = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
