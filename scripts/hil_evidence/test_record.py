from __future__ import annotations

import json
import shutil
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .models import JsonDict
from .parsing import extract_test_record_summary, find_json_exact_query_matches, find_json_query_matches


def summarize_local_test_record(path: str, query: str | None = None, exact_query: bool = False) -> tuple[JsonDict | None, JsonDict | None]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        record = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        return None, {"tool": "local", "message": f"failed to read test_record.json {path}: {exc}"}
    return summarize_record(record, path, query, exact_query=exact_query), None


def summarize_s3_test_records(
    uris: list[str],
    query: str | None = None,
    max_records: int = 20,
    exact_query: bool = False,
) -> tuple[list[JsonDict], list[JsonDict]]:
    if not uris:
        return [], []
    if shutil.which("aws") is None:
        return [], [{"tool": "aws", "message": "aws CLI not found on PATH; test_record.json reads skipped"}]

    summaries: list[JsonDict] = []
    blockers: list[JsonDict] = []
    for uri in uris[:max_records]:
        try:
            text = run_text(["aws", "s3", "cp", uri, "-"])
            record = json.loads(text)
        except CommandFailure as exc:
            blockers.append(command_blocker(f"aws s3 cp failed for {uri}", exc))
            continue
        except json.JSONDecodeError as exc:
            blockers.append({"tool": "test_record", "message": f"invalid JSON in {uri}: {exc}"})
            continue
        summaries.append(summarize_record(record, uri, query, exact_query=exact_query))
    return summaries, blockers


def summarize_record(record: Any, uri: str, query: str | None = None, exact_query: bool = False) -> JsonDict:
    summary = extract_test_record_summary(record, uri)
    if query:
        summary["query"] = query
        summary["query_match_mode"] = "exact" if exact_query else "substring"
        summary["query_matches"] = find_json_exact_query_matches(record, query) if exact_query else find_json_query_matches(record, query)
    return summary


class CommandFailure(Exception):
    def __init__(self, command: list[str], returncode: int, stdout: str, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(shlex.join(command))


def run_text(command: list[str], timeout_seconds: int = 120) -> str:
    try:
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise CommandFailure(command, 124, timeout_output(exc.stdout), f"command timed out after {timeout_seconds}s") from exc
    if completed.returncode != 0:
        raise CommandFailure(command, completed.returncode, completed.stdout, completed.stderr)
    return completed.stdout


def command_blocker(message: str, exc: CommandFailure) -> JsonDict:
    blocker: JsonDict = {
        "tool": "aws",
        "message": message,
        "command": shlex.join(exc.command),
        "returncode": exc.returncode,
    }
    if exc.stderr.strip():
        blocker["stderr_excerpt"] = excerpt(exc.stderr)
    return blocker


def excerpt(text: str, limit: int = 2000) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "\n...<truncated>"


def timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
