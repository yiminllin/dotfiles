from __future__ import annotations

import fnmatch
import re
import shlex
import shutil
import subprocess

from .models import JsonDict
from .parsing import (
    dedupe_preserving_order,
    extract_artifact_s3_refs,
    extract_baraza,
    extract_baraza_from_inventory,
    extract_log_links,
    find_test_record_keys_from_recursive_ls,
    is_test_record_uri,
    normalize_s3_root,
    split_s3_uri,
)


S3_BUCKET = "platform2-testing-logs"
KEY_ARTIFACT_HINT_LIMIT = 25
TEST_RECORD_ARTIFACT_LIMIT = 25
KEY_FILE_PATTERNS = (
    "*test_record.json",
    "*test_log_*.log",
    "*phoenix_logs/phoenix.log",
    "*.zml",
    "*.zml.zst",
)
JOURNAL_ARTIFACT_RE = re.compile(
    r"(?:^|[/._-])journalctl(?:$|[/._-])|(?:^|[/._-])journal(?:$|[/._-])",
    re.IGNORECASE,
)
VALIDATOR_ARTIFACT_RE = re.compile(r"validator|validation", re.IGNORECASE)


def evidence_from_log(log_text: str, runner_name: str = "") -> JsonDict:
    refs = extract_artifact_s3_refs(log_text, runner_name=runner_name, details=True)
    links = extract_log_links(log_text, bucket=S3_BUCKET)
    roots = dedupe_preserving_order(
        root
        for link in links["s3_links"] + [ref["s3_uri"] for ref in refs if ref.get("s3_uri")]
        if (root := normalize_s3_root(link, runner_name=runner_name, bucket=S3_BUCKET)) is not None
    )
    return {
        "refs": refs,
        "s3_links": links["s3_links"],
        "baraza_links": links["baraza_links"],
        "baraza": extract_baraza(log_text),
        "roots": roots,
    }


def inventory_roots(roots: list[str], max_items: int = 500) -> tuple[list[JsonDict], list[JsonDict]]:
    if not roots:
        return [], []
    if shutil.which("aws") is None:
        return [], [blocker("aws", "aws CLI not found on PATH; S3 inventory and test_record reads skipped")]

    inventories: list[JsonDict] = []
    blockers: list[JsonDict] = []
    for root in roots:
        try:
            stdout = run_text(["aws", "s3", "ls", "--recursive", root])
        except CommandFailure as exc:
            blockers.append(command_blocker("aws", f"aws s3 ls failed for {root}", exc))
            continue
        inventory = inventory_from_listing(root, stdout, max_items)
        inventories.append(inventory)
    return inventories, blockers


def inventory_from_listing(root: str, stdout: str, max_items: int) -> JsonDict:
    inventory = parse_aws_ls(root, stdout, max_items)
    inventory["test_record_uris"] = test_record_uris_from_listing(root, stdout)
    inventory["baraza"] = extract_baraza_from_inventory(inventory)
    return inventory


def parse_aws_ls(s3_uri: str, stdout: str, max_items: int) -> JsonDict:
    bucket, prefix = split_s3_uri(s3_uri)
    items = []
    key_hints = []
    test_record_artifacts = []
    total_count = 0
    total_size = 0
    for line in stdout.splitlines():
        match = re.match(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+(\d+)\s+(.+)$", line)
        if not match:
            continue
        total_count += 1
        size = int(match.group(2))
        key = match.group(3)
        total_size += size
        uri = f"s3://{bucket}/{key}"
        classification = classify_key_artifact(key)
        if classification and classification.get("category") == "test_record" and len(test_record_artifacts) < TEST_RECORD_ARTIFACT_LIMIT:
            test_record_artifacts.append({"key": key, "uri": uri, "size": size, **classification})
        if classification and len(key_hints) < KEY_ARTIFACT_HINT_LIMIT:
            key_hints.append({"key": key, "uri": uri, "size": size, **classification})
        if len(items) < max_items:
            items.append(
                {
                    "last_modified": match.group(1),
                    "size": size,
                    "key": key,
                    "uri": uri,
                    "key_file": classification is not None,
                }
            )
    return {
        "s3_uri": s3_uri,
        "bucket": bucket,
        "prefix": prefix,
        "count": total_count,
        "total_size": total_size,
        "truncated": total_count > len(items),
        "items": items,
        "key_artifact_hints": key_hints,
        "test_record_artifacts": test_record_artifacts,
    }


def test_record_uris(roots: list[str], inventories: list[JsonDict]) -> list[str]:
    uris = [root.rstrip("/") for root in roots if is_test_record_uri(root)]
    for inventory in inventories:
        uris.extend(str(uri) for uri in inventory.get("test_record_uris") or [] if uri)
        for item in inventory.get("items") or []:
            uri = str(item.get("uri") or "")
            if is_test_record_uri(uri):
                uris.append(uri)
    return dedupe_preserving_order(uris)


def test_record_uris_from_listing(root: str, stdout: str) -> list[str]:
    try:
        bucket, _ = split_s3_uri(root)
    except ValueError:
        return []
    return [
        f"s3://{bucket}/{key}"
        for key in find_test_record_keys_from_recursive_ls(stdout)
    ]


def is_key_file(key: str) -> bool:
    return classify_key_artifact(key) is not None


def classify_key_artifact(key: str) -> JsonDict | None:
    if not key:
        return None
    if fnmatch.fnmatch(key, "*test_record.json"):
        return {"category": "test_record", "type": "test_record.json", "note": "Authoritative test result and manifest."}
    if fnmatch.fnmatch(key, "*test_log_*.log"):
        return {"category": "test_log", "type": "HTF log", "note": "Harness log with failure and teardown context."}
    if fnmatch.fnmatch(key, "*phoenix_logs/phoenix.log"):
        return {"category": "phoenix_log", "type": "phoenix.log", "note": "Phoenix orchestration log."}
    if fnmatch.fnmatch(key, "*.zml.zst"):
        return {"category": "zml", "type": "compressed ZML", "note": "Validator and journal signal streams."}
    if fnmatch.fnmatch(key, "*.zml"):
        return {"category": "zml", "type": "ZML", "note": "Validator and journal signal streams."}
    if JOURNAL_ARTIFACT_RE.search(key):
        return {"category": "journal", "type": "journal", "note": "Systemd journal or journal-derived artifact."}
    if VALIDATOR_ARTIFACT_RE.search(key):
        return {"category": "validation", "type": "validator artifact", "note": "Validator output or validation summary."}
    if any(fnmatch.fnmatch(key, pattern) for pattern in KEY_FILE_PATTERNS):
        return {"category": "artifact", "type": "key file", "note": "High-signal HIL artifact."}
    return None


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


def blocker(tool: str, message: str) -> JsonDict:
    return {"tool": tool, "message": message, "guidance": aws_guidance(message)}


def command_blocker(tool: str, message: str, exc: CommandFailure) -> JsonDict:
    result: JsonDict = {
        "tool": tool,
        "message": message,
        "command": shlex.join(exc.command),
        "returncode": exc.returncode,
    }
    if exc.stderr.strip():
        result["stderr_excerpt"] = excerpt(exc.stderr)
    if exc.stdout.strip():
        result["stdout_excerpt"] = excerpt(exc.stdout)
    guidance = aws_guidance(exc.stderr)
    if guidance:
        result["guidance"] = guidance
    return result


def aws_guidance(text: str) -> str | None:
    lowered = text.lower()
    if any(token in lowered for token in ("credentials", "expiredtoken", "sso", "access denied", "forbidden", "not authorized")):
        return "Refresh AWS credentials outside this helper; do not run auth from the helper."
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
