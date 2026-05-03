#!/usr/bin/env python3
"""Generate draft PR descriptions for a PR chain using an existing style reference."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_REASON = (
    "Describe the shared chain-level symptom/problem and context. For stacked PRs, keep "
    "this reason identical across the chain and put per-PR specifics in Description of Change."
)
DEFAULT_CRITICALITY = """- [ ] L1 Major <!-- Impacts critical safety systems (e.g. Paraland, DAA, fault mgmt) -->
- [ ] L2 Moderate <!-- Impacts production system, or safety-related testing -->
- [x] L3 Nonfunctional <!-- Trivial to validate no impact on prod (e.g. docs, style, dev tool) -->"""
DEFAULT_VERIFICATION = """- [ ] TODO: add exact verification command, run link, or manual result"""
DEFAULT_RELEASE_NOTES = """- [ ] Release Notes or Upgrade Instructions required

<!-- If checked, replace this line with your release notes or upgrade instructions -->"""

NOISE_FILES = {
    "Cargo.lock",
    "MODULE.bazel.lock",
}

DEFAULT_MAX_SECTIONS = 5
DEFAULT_MAX_BULLETS_PER_SECTION = 4

AREA_ORDER = [
    "scenario",
    "orchestration",
    "config",
    "routing",
    "validator",
    "injection",
    "tests",
    "ci",
    "other",
]

AREA_TITLES = {
    "scenario": "Scenario setup and mission flow",
    "orchestration": "Graph/domain bring-up",
    "config": "Config resolution and runtime planning",
    "routing": "Inter-domain routing and bridge classification",
    "validator": "Validation rules and fail-fast guardrails",
    "injection": "Message redirection and identifier mapping",
    "tests": "Automated coverage and scenario plumbing",
    "ci": "Workflow dispatch and test-plan selection",
    "other": "Additional supporting changes",
}

SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

VERB_MAP = {
    "add": "adds",
    "update": "updates",
    "migrate": "migrates",
    "plumb": "plumbs",
    "route": "routes",
    "enable": "enables",
    "disable": "disables",
    "refactor": "refactors",
    "fix": "fixes",
    "remove": "removes",
    "rename": "renames",
    "wire": "wires",
    "set": "sets",
    "introduce": "introduces",
    "implement": "implements",
}

SNIPPET_START_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*(?:pub\s+)?enum\s+[A-Za-z_][A-Za-z0-9_]*"),
    re.compile(r"^\s*(?:pub\s+)?struct\s+[A-Za-z_][A-Za-z0-9_]*"),
    re.compile(r"^\s*(?:pub\s+)?fn\s+[A-Za-z_][A-Za-z0-9_]*\("),
    re.compile(r"^\s*def\s+[A-Za-z_][A-Za-z0-9_]*\("),
    re.compile(r"^\s*[A-Z][A-Z0-9_]+\s*=\s*auto\(\)"),
    re.compile(r"^\s*-+\s+[A-Z][A-Z0-9_]+\s*->"),
]

DECLARATION_RE = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const|fn|struct|enum|type)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
SCOPED_SYMBOL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)::([A-Za-z_][A-Za-z0-9_]*)\b")

KNOWN_SCENARIO_STEPS = {
    "takeoff",
    "load_from_auto_kiosk",
    "deliver_with_droid",
    "dock_at",
    "deliver",
    "dock",
    "transit",
    "raise_droid",
    "await_flight_readiness",
}


@dataclass(frozen=True)
class CommitInfo:
    headline: str


@dataclass(frozen=True)
class PullRequestInfo:
    number: int
    title: str
    body: str
    commits: list[CommitInfo]


@dataclass(frozen=True)
class StyleTemplate:
    reason_text: str
    criticality_block: str
    verification_block: str
    release_notes_block: str


@dataclass(frozen=True)
class PatchedFile:
    filename: str
    patch: str
    added_lines: tuple[str, ...]


@dataclass(frozen=True)
class Snippet:
    label: str
    language: str
    code: str


def _run_cmd(cmd: list[str]) -> str:
    cp = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if cp.returncode != 0:
        msg = cp.stderr.strip() or cp.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(cmd)}: {msg}")
    return cp.stdout


def _require_gh() -> None:
    _run_cmd(["gh", "auth", "status"])


def _parse_pr_number(token: str) -> int:
    token = token.strip()
    if token.startswith("http://") or token.startswith("https://"):
        match = re.search(r"/pull/(\d+)", token)
        if not match:
            raise argparse.ArgumentTypeError(f"Could not parse PR number from URL: {token}")
        return int(match.group(1))

    value = token.lstrip("#")
    if value.isdigit():
        return int(value)
    raise argparse.ArgumentTypeError(f"Expected PR number, '#123', or PR URL. Got: {token}")


def _load_gh_json(cmd: list[str]) -> Any:
    out = _run_cmd(cmd)
    return json.loads(out)


def _added_lines_from_patch(patch: str) -> tuple[str, ...]:
    lines: list[str] = []
    for raw in patch.splitlines():
        if raw.startswith("+++") or not raw.startswith("+"):
            continue
        lines.append(raw[1:])
    return tuple(lines)


def _fetch_pr(repo: str, pr_number: int) -> PullRequestInfo:
    payload = _load_gh_json(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "number,title,body,commits",
        ]
    )
    commits = [
        CommitInfo(
            headline=entry.get("messageHeadline", "").strip(),
        )
        for entry in payload.get("commits", [])
    ]
    return PullRequestInfo(
        number=int(payload["number"]),
        title=payload.get("title", "").strip(),
        body=payload.get("body", "") or "",
        commits=commits,
    )


def _extract_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    headers = list(SECTION_HEADER_RE.finditer(body))
    for idx, header in enumerate(headers):
        key = header.group(1).strip()
        start = header.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(body)
        sections[key] = body[start:end].strip("\n")
    return sections


def _strip_comments(text: str) -> str:
    return HTML_COMMENT_RE.sub("", text)


def _clean_block(text: str, fallback: str, *, preserve_comments: bool = False) -> str:
    cleaned = text.strip()
    if not preserve_comments:
        cleaned = _strip_comments(cleaned).strip()
    return cleaned if cleaned else fallback


def _extract_reason_text(reason_block: str) -> str:
    if not reason_block.strip():
        return DEFAULT_REASON

    lines: list[str] = []
    for raw in _strip_comments(reason_block).splitlines():
        line = raw.rstrip()
        if line.strip().lower() == "pr tree":
            break
        if line.strip().startswith("- #"):
            continue
        lines.append(line)

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    text = "\n".join(lines).strip()
    return text if text else DEFAULT_REASON


def _looks_generic_verification_block(text: str) -> bool:
    cleaned = _strip_comments(text).strip().lower()
    if not cleaned:
        return True
    return "ab-compare" in cleaned or "behavior no-op" in cleaned


def _infer_style_template(
    repo: str,
    prs: list[PullRequestInfo],
    style_pr: int | None,
) -> StyleTemplate:
    source: PullRequestInfo | None = None
    by_number = {pr.number: pr for pr in prs}

    if style_pr is not None:
        if style_pr in by_number:
            source = by_number[style_pr]
        else:
            source = _fetch_pr(repo, style_pr)
    else:
        for pr in prs:
            if "## Reason for Change" in pr.body and "## Description of Change" in pr.body:
                source = pr
                break
        if source is None and prs:
            source = prs[0]

    if source is None:
        return StyleTemplate(
            reason_text=DEFAULT_REASON,
            criticality_block=DEFAULT_CRITICALITY,
            verification_block=DEFAULT_VERIFICATION,
            release_notes_block=DEFAULT_RELEASE_NOTES,
        )

    sections = _extract_sections(source.body)
    verification_block = _clean_block(
        sections.get("Verification", ""),
        DEFAULT_VERIFICATION,
        preserve_comments=True,
    )
    if _looks_generic_verification_block(verification_block):
        verification_block = DEFAULT_VERIFICATION

    return StyleTemplate(
        reason_text=_extract_reason_text(sections.get("Reason for Change", "")),
        criticality_block=DEFAULT_CRITICALITY,
        verification_block=verification_block,
        release_notes_block=DEFAULT_RELEASE_NOTES,
    )


def _chain_tree(pr_chain: list[int], current: int) -> str:
    return "\n".join(f"- #{pr}{' ◀' if pr == current else ''}" for pr in pr_chain)


def _humanize_title(title: str) -> str:
    cleaned = re.sub(r"^(?:\[[^]]+\]\s*)+", "", title).strip()
    if " - " in cleaned:
        _, cleaned = cleaned.split(" - ", 1)
        cleaned = cleaned.strip()
    if not cleaned:
        return "updates the codebase"

    words = cleaned.split()
    first = words[0].lower()
    if first in VERB_MAP and len(words) > 1:
        return f"{VERB_MAP[first]} {' '.join(words[1:])}"
    return f"implements {cleaned}"


def _fetch_pr_files_with_patch(repo: str, pr_number: int) -> list[PatchedFile]:
    files: list[PatchedFile] = []
    page = 1
    while True:
        batch = _load_gh_json(
            [
                "gh",
                "api",
                f"repos/{repo}/pulls/{pr_number}/files?per_page=100&page={page}",
            ]
        )
        if not isinstance(batch, list) or not batch:
            break
        for entry in batch:
            files.append(
                PatchedFile(
                    filename=str(entry.get("filename", "")),
                    patch=str(entry.get("patch", "") or ""),
                    added_lines=_added_lines_from_patch(str(entry.get("patch", "") or "")),
                )
            )
        if len(batch) < 100:
            break
        page += 1
    return files


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _join_codes(values: list[str], *, limit: int = 5) -> str:
    items = _dedupe([value for value in values if value])[:limit]
    if not items:
        return ""
    formatted = [f"`{item}`" for item in items]
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} and {formatted[1]}"
    return ", ".join(formatted[:-1]) + f", and {formatted[-1]}"


def _classify_area(path: str) -> str:
    if path in NOISE_FILES:
        return "other"
    if path.startswith("ash/scenarios/") or ("/scenarios/" in path and path.endswith(".pbtxt")):
        return "scenario"
    if path.startswith("ash/phoenix/core/zrtmp_bridge/"):
        return "routing"
    if path.startswith("ash/phoenix/orchestration/"):
        if "ipc_domain" in path or "routing" in path or "bridge" in path:
            return "routing"
        if "config" in path:
            return "config"
        return "orchestration"
    if "validator_configs" in path or "validators/config" in path:
        return "validator"
    if "message_injection_configs" in path:
        return "injection"
    if path.startswith("hil/p2_tests/"):
        return "tests"
    if path.startswith("hil/ci/workflow/") or path.startswith(".github/workflows/"):
        return "ci"
    return "other"


def _format_step(step: str) -> str:
    return "".join(piece.capitalize() for piece in step.split("_"))


def _extract_scenario_steps(files: list[PatchedFile]) -> list[str]:
    steps: list[str] = []
    for file_info in files:
        if not file_info.filename.endswith(".pbtxt"):
            continue
        for line in file_info.added_lines:
            match = re.match(r"^\s*([a-z_]+)\s*\{\s*$", line)
            if match is None:
                continue
            token = match.group(1)
            if token in KNOWN_SCENARIO_STEPS:
                steps.append(_format_step(token))
    return _dedupe(steps)


def _extract_graph_nodes(files: list[PatchedFile]) -> list[str]:
    nodes: list[str] = []
    pattern = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_]*)::(?:default|new(?:_[A-Za-z0-9_]+)?)\([^)]*\)\.add_to_graph"
    )
    for file_info in files:
        for line in file_info.added_lines:
            match = pattern.match(line)
            if match is not None:
                nodes.append(match.group(1))
    return _dedupe(nodes)


def _extract_dispatch_options(files: list[PatchedFile]) -> list[str]:
    options: list[str] = []
    pattern = re.compile(r"^\s*-\s*([A-Z][A-Z0-9_]+)\s*->")
    for file_info in files:
        for line in file_info.added_lines:
            match = pattern.match(line)
            if match is not None:
                options.append(match.group(1))
    return _dedupe(options)


def _extract_valid_tests(files: list[PatchedFile]) -> list[str]:
    values: list[str] = []
    enum_pattern = re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*=\s*auto\(\)")
    valid_test_pattern = re.compile(r"ValidTest\.([A-Z][A-Z0-9_]+)")
    for file_info in files:
        for line in file_info.added_lines:
            if match := enum_pattern.match(line):
                values.append(match.group(1))
            values.extend(valid_test_pattern.findall(line))
    return _dedupe(values)


def _extract_pytest_ids(files: list[PatchedFile]) -> list[str]:
    ids: list[str] = []
    pattern = re.compile(r'id="([^"]+)"')
    for file_info in files:
        for line in file_info.added_lines:
            ids.extend(pattern.findall(line))
    return _dedupe(ids)


def _extract_helper_defs(files: list[PatchedFile]) -> list[str]:
    funcs: list[str] = []
    pattern = re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\(")
    for file_info in files:
        for line in file_info.added_lines:
            match = pattern.match(line)
            if match is None:
                continue
            name = match.group(1)
            if not name.startswith("_"):
                continue
            funcs.append(name)
    return _dedupe(funcs)


def _extract_declared_symbols(
    files: list[PatchedFile],
    *,
    keywords: tuple[str, ...] | None = None,
) -> list[str]:
    symbols: list[str] = []
    lowered_keywords = tuple(keyword.lower() for keyword in keywords or ())
    for file_info in files:
        skip_next_declaration = False
        in_test_module = False
        for line in file_info.added_lines:
            stripped = line.strip()
            if stripped.startswith("mod tests {"):
                in_test_module = True
            if in_test_module:
                continue
            if stripped.startswith("#[test]") or stripped.startswith("#[should_panic"):
                skip_next_declaration = True
                continue
            match = DECLARATION_RE.match(line)
            if match is None:
                continue
            if skip_next_declaration:
                skip_next_declaration = False
                continue
            name = match.group(1)
            if name.startswith("test_"):
                continue
            if lowered_keywords and not any(
                keyword in name.lower() for keyword in lowered_keywords
            ):
                continue
            symbols.append(name)
    return _dedupe(symbols)


def _extract_scoped_symbols(
    files: list[PatchedFile],
    *,
    prefixes: tuple[str, ...],
) -> list[str]:
    symbols: list[str] = []
    wanted_prefixes = set(prefixes)
    for file_info in files:
        for line in file_info.added_lines:
            for prefix, value in SCOPED_SYMBOL_RE.findall(line):
                if prefix not in wanted_prefixes:
                    continue
                symbols.append(f"{prefix}::{value}")
    return _dedupe(symbols)


def _has_fail_fast_checks(files: list[PatchedFile]) -> bool:
    return any(
        any(token in line for token in ("panic!", "assert!", "assert_eq!", "assert_ne!"))
        for file_info in files
        for line in file_info.added_lines
    )


def _extract_config_paths(files: list[PatchedFile]) -> list[str]:
    paths: list[str] = []
    pattern = re.compile(r"([A-Za-z0-9_./-]+\.(?:ya?ml|json|pbtxt))")
    for file_info in files:
        for line in file_info.added_lines:
            for match in pattern.findall(line):
                if "/" in match:
                    paths.append(match)
    return _dedupe(paths)


def _extract_redirect_pairs(files: list[PatchedFile]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for file_info in files:
        lines = file_info.added_lines
        last_original: str | None = None
        for line in lines:
            original_match = re.search(r"original_identifier_to_redirect:\s*(\S+)", line)
            if original_match:
                last_original = original_match.group(1)
                continue
            new_match = re.search(r"new_identifier_to_redirect_to:\s*(\S+)", line)
            if new_match and last_original is not None:
                pairs.append((last_original, new_match.group(1)))
                last_original = None
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pair in pairs:
        if pair in seen:
            continue
        seen.add(pair)
        deduped.append(pair)
    return deduped


def _extract_required_tasks(files: list[PatchedFile]) -> list[str]:
    tasks: list[str] = []
    in_required_tasks = False
    for file_info in files:
        lines = file_info.added_lines
        for line in lines:
            if re.match(r"^\s*required_tasks:\s*$", line):
                in_required_tasks = True
                continue
            if in_required_tasks and re.match(r"^\s*[A-Za-z_]+:\s*$", line):
                in_required_tasks = False
            if not in_required_tasks:
                continue
            match = re.match(r"^\s*-\s*([A-Za-z][A-Za-z0-9_]+)\s*$", line)
            if match:
                tasks.append(match.group(1))
    return _dedupe(tasks)


def _extract_optional_alarms(files: list[PatchedFile]) -> list[str]:
    alarms: list[str] = []
    for file_info in files:
        for line in file_info.added_lines:
            match = re.match(r"^\s*([A-Z][A-Z0-9_]+):\s*$", line)
            if match:
                alarms.append(match.group(1))
    return _dedupe(alarms)


def _language_for_path(path: str) -> str:
    if path.endswith(".rs"):
        return "rust"
    if path.endswith(".py"):
        return "python"
    if path.endswith(".yaml") or path.endswith(".yml"):
        return "yaml"
    if path.endswith(".pbtxt"):
        return "text"
    if path.endswith(".bzl") or path.endswith("BUILD.bazel"):
        return "python"
    return "text"


def _extract_snippets(
    files: list[PatchedFile],
    *,
    max_snippets: int,
    max_lines: int,
) -> list[Snippet]:
    snippets: list[Snippet] = []
    seen_payloads: set[str] = set()
    used_labels: set[str] = set()
    for file_info in files:
        if file_info.filename in used_labels:
            continue
        if not file_info.patch:
            continue
        patch_lines = file_info.patch.splitlines()
        i = 0
        while i < len(patch_lines):
            raw = patch_lines[i]
            if raw.startswith("+++"):
                i += 1
                continue
            if not raw.startswith("+"):
                i += 1
                continue
            line = raw[1:]
            if not any(pattern.match(line) for pattern in SNIPPET_START_PATTERNS):
                i += 1
                continue

            block: list[str] = [line]
            i += 1
            while i < len(patch_lines) and len(block) < max_lines:
                nxt = patch_lines[i]
                if nxt.startswith("+++") or not nxt.startswith("+"):
                    break
                block.append(nxt[1:])
                i += 1

            while block and not block[-1].strip():
                block.pop()
            code = "\n".join(block).strip("\n")
            if len(block) < 2 or not code or code in seen_payloads:
                continue

            seen_payloads.add(code)
            snippets.append(
                Snippet(
                    label=file_info.filename,
                    language=_language_for_path(file_info.filename),
                    code=code,
                )
            )
            used_labels.add(file_info.filename)
            if len(snippets) >= max_snippets:
                return snippets
            break
        if len(snippets) >= max_snippets:
            break
    return snippets


def _build_human_sections(files: list[PatchedFile]) -> list[tuple[str, list[str]]]:
    buckets: dict[str, list[PatchedFile]] = defaultdict(list)
    for file_info in files:
        buckets[_classify_area(file_info.filename)].append(file_info)

    sections: list[tuple[str, list[str]]] = []

    for area in AREA_ORDER:
        area_files = buckets.get(area, [])
        if not area_files:
            continue

        bullets: list[str] = []

        if area == "scenario":
            scenario_paths = [f.filename for f in area_files if f.filename.endswith(".pbtxt")]
            bullets.append(
                "Adds or updates scenario definitions and mission wiring needed to exercise this flow."
            )
            if scenario_paths:
                bullets.append(f"Scenario file: {', '.join(f'`{p}`' for p in scenario_paths[:3])}.")
            mission_steps = _extract_scenario_steps(area_files)
            if mission_steps:
                bullets.append(
                    f"Defines mission progression as `{' -> '.join(mission_steps[:8])}`."
                )
            registered = []
            for file_info in area_files:
                if not file_info.filename.endswith("BUILD.bazel"):
                    continue
                for line in file_info.added_lines:
                    match = re.match(r'^\s*"([^"]+\.pbtxt)"\s*,?\s*$', line)
                    if match:
                        registered.append(match.group(1))
            if registered:
                bullets.append(
                    "Updates scenario build registration for "
                    f"{', '.join(f'`{p}`' for p in _dedupe(registered)[:4])}."
                )

        elif area == "orchestration":
            files_list = _dedupe([f.filename for f in area_files])
            bullets.append(
                "Updates graph/domain bring-up so the right components are created in the intended runtime."
            )
            if any(path.endswith(("BUILD.bazel", "Cargo.toml")) for path in files_list):
                bullets.append(
                    "Adds build/dependency wiring needed for the new orchestration and domain plumbing."
                )
            graph_nodes = _extract_graph_nodes(area_files)
            if graph_nodes:
                bullets.append(
                    f"Adds graph components {', '.join(f'`{n}`' for n in graph_nodes[:8])}."
                )
            if any("HIL like SIL" in f.patch for f in area_files):
                bullets.append("Keeps HIL behavior aligned with existing SIL graph behavior.")
            if files_list:
                bullets.append(f"Primary wiring file: `{files_list[0]}`.")

        elif area == "config":
            files_list = _dedupe([f.filename for f in area_files if f.filename not in NOISE_FILES])
            bullets.append(
                "Plumbs configuration and domain-resolution changes needed to make this stack step work."
            )
            config_symbols = _extract_declared_symbols(
                area_files,
                keywords=("config", "dock", "domain", "runtime"),
            )
            if config_symbols:
                bullets.append(
                    "Introduces or extends config/domain-planning symbols "
                    f"{_join_codes(config_symbols, limit=6)}."
                )
            if _has_fail_fast_checks(area_files):
                bullets.append(
                    "Adds fail-fast validation for unsupported or inconsistent configuration states."
                )
            if files_list:
                bullets.append(
                    f"Config files touched: {', '.join(f'`{p}`' for p in files_list[:4])}."
                )

        elif area == "routing":
            files_list = _dedupe([f.filename for f in area_files if f.filename not in NOISE_FILES])
            bullets.append(
                "Adds or updates inter-domain routing so traffic is classified onto the intended bridge path."
            )
            routing_bridge_symbols = _extract_scoped_symbols(
                area_files,
                prefixes=("BridgeMockType", "ZrtmpBridgeComputeDomain"),
            )
            if routing_bridge_symbols:
                bullets.append(
                    "Touches routing-specific bridge symbols "
                    f"{_join_codes(routing_bridge_symbols, limit=6)}."
                )
            routing_declared_symbols = _extract_declared_symbols(
                area_files,
                keywords=("route", "routing", "bridge", "metadata", "identifier"),
            )
            if routing_declared_symbols:
                bullets.append(
                    "Adds routing-specific helpers and identifier sets "
                    f"{_join_codes(routing_declared_symbols, limit=6)}."
                )
            if _has_fail_fast_checks(area_files):
                bullets.append(
                    "Adds fail-fast checks around conflicting routing metadata or unsupported direct-routing states."
                )
            if files_list:
                bullets.append(
                    f"Routing files touched: {', '.join(f'`{p}`' for p in files_list[:4])}."
                )

        elif area == "validator":
            validator_files = [
                f.filename
                for f in area_files
                if "validator_configs" in f.filename or "validators/config" in f.filename
            ]
            bullets.append(
                "Adds validator coverage and reviewer-visible guardrails for the updated flow."
            )
            if validator_files:
                bullets.append(
                    "Validator config(s): "
                    f"{', '.join(f'`{p}`' for p in _dedupe(validator_files)[:4])}."
                )
            tasks = _extract_required_tasks(area_files)
            if tasks:
                bullets.append(f"Defines required task sequence `{' -> '.join(tasks[:8])}`.")
            alarms = _extract_optional_alarms(area_files)
            if alarms:
                bullets.append(
                    "Allows expected optional alarms for startup/no-sync behavior "
                    f"({_join_codes(alarms, limit=6)})."
                )
            if _has_fail_fast_checks(area_files):
                bullets.append(
                    "Adds fail-fast validation when required task sequencing or expected metadata becomes inconsistent."
                )

        elif area == "injection":
            injection_files = _dedupe([f.filename for f in area_files])
            bullets.append(
                "Adds redirection/injection rules so simulated topics map onto the intended runtime identifiers."
            )
            bullets.append(
                f"Injection config(s): {', '.join(f'`{p}`' for p in injection_files[:4])}."
            )
            pairs = _extract_redirect_pairs(area_files)
            if pairs:
                examples = [f"`{src} -> {dst}`" for src, dst in pairs[:3]]
                bullets.append(
                    "Routes simulated topics into runtime identifiers (for example: "
                    + ", ".join(examples)
                    + ")."
                )

        elif area == "tests":
            test_files = _dedupe([f.filename for f in area_files])
            bullets.append(
                "Extends automated coverage for the new flow and the new routing/config branches."
            )
            bullets.append(f"Test files touched: {', '.join(f'`{p}`' for p in test_files[:4])}.")
            pytest_ids = _extract_pytest_ids(area_files)
            if pytest_ids:
                bullets.append(f"Adds mission/scenario cases {_join_codes(pytest_ids, limit=6)}.")
            helper_defs = _extract_helper_defs(area_files)
            if helper_defs:
                bullets.append(
                    "Adds scenario-specific helpers "
                    f"{_join_codes(helper_defs, limit=6)} for conditional setup."
                )
            config_paths = [
                path
                for path in _extract_config_paths(area_files)
                if "validator" in path or "message_injection" in path
            ]
            if config_paths:
                bullets.append(
                    "Wires additional validator/injection configs "
                    f"({', '.join(f'`{p}`' for p in _dedupe(config_paths)[:4])})."
                )

        elif area == "ci":
            ci_files = _dedupe([f.filename for f in area_files])
            bullets.append(
                "Plumbs the scenario through workflow dispatch, selection, and test-plan handling."
            )
            bullets.append(f"CI files touched: {', '.join(f'`{p}`' for p in ci_files[:4])}.")
            dispatch_options = _extract_dispatch_options(area_files)
            if dispatch_options:
                bullets.append(
                    f"Adds workflow dispatch option(s) {_join_codes(dispatch_options, limit=5)}."
                )
            valid_tests = _extract_valid_tests(area_files)
            if valid_tests:
                bullets.append(
                    "Plumbs selectors through `ValidTest`/test-plan handling "
                    f"({_join_codes(valid_tests, limit=6)})."
                )

        else:
            misc_files = [
                f.filename
                for f in area_files
                if f.filename not in NOISE_FILES and not f.filename.endswith(".md")
            ]
            if misc_files:
                bullets.append(
                    "Updates supporting implementation files that back the main behavior change in this PR."
                )
                bullets.append(
                    f"Supporting files: {', '.join(f'`{p}`' for p in _dedupe(misc_files)[:5])}."
                )

        if bullets:
            sections.append((AREA_TITLES[area], bullets))

    if not sections:
        sections.append(
            ("Implementation details", ["Updates implementation files in this PR scope."])
        )

    return sections


def _is_listing_bullet(bullet: str) -> bool:
    lowered = bullet.lower()
    listing_starts = (
        "scenario file:",
        "config files touched:",
        "routing files touched:",
        "validator config(s):",
        "injection config(s):",
        "test files touched:",
        "ci files touched:",
        "primary wiring file:",
        "supporting files:",
        "updates scenario build registration",
        "wires additional validator/injection configs",
    )
    return lowered.startswith(listing_starts)


def _compact_sections(
    sections: list[tuple[str, list[str]]],
    *,
    max_sections: int,
    max_bullets_per_section: int,
) -> list[tuple[str, list[str]]]:
    if max_sections <= 0 or max_bullets_per_section <= 0:
        return sections

    compacted: list[tuple[str, list[str]]] = []
    for title, bullets in sections:
        prioritized = [bullet for bullet in bullets if not _is_listing_bullet(bullet)]
        prioritized.extend(bullet for bullet in bullets if _is_listing_bullet(bullet))
        compacted.append((title, prioritized[:max_bullets_per_section]))
        if len(compacted) >= max_sections:
            break
    return compacted


def _ensure_sentence(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    if cleaned[-1] in ".!?":
        return cleaned
    return f"{cleaned}."


def _build_prose_description(
    pr: PullRequestInfo,
    sections: list[tuple[str, list[str]]],
    *,
    include_snippets: bool,
    snippets: list[Snippet],
) -> str:
    lines = [f"This PR {_humanize_title(pr.title)}."]
    for title, bullets in sections:
        summary = " ".join(_ensure_sentence(bullet) for bullet in bullets if bullet.strip())
        if not summary:
            continue
        lines.extend(["", f"{title}: {summary}"])

    if include_snippets and snippets:
        lines.extend(["", "Illustrative snippets:"])
        for snippet in snippets:
            lines.append(f"- `{snippet.label}`")
            lines.append(f"  ```{snippet.language}")
            lines.extend(f"  {code_line}" for code_line in snippet.code.splitlines())
            lines.append("  ```")

    return "\n".join(lines).strip()


def _build_bulleted_description(
    pr: PullRequestInfo,
    sections: list[tuple[str, list[str]]],
    *,
    include_snippets: bool,
    snippets: list[Snippet],
) -> str:
    lines = [f"This PR {_humanize_title(pr.title)}. In particular:", ""]
    for title, bullets in sections:
        lines.append(f"- {title}")
        lines.extend(f"  - {bullet}" for bullet in bullets)

    if include_snippets and snippets:
        lines.append("- Illustrative snippets")
        for snippet in snippets:
            lines.append(f"  - `{snippet.label}`")
            lines.append(f"    ```{snippet.language}")
            lines.extend(f"    {code_line}" for code_line in snippet.code.splitlines())
            lines.append("    ```")

    return "\n".join(lines).strip()


def _build_hybrid_description(
    pr: PullRequestInfo,
    sections: list[tuple[str, list[str]]],
    *,
    include_snippets: bool,
    snippets: list[Snippet],
) -> str:
    lines = [
        f"This PR {_humanize_title(pr.title)}.",
        "",
        "In particular, it makes the following changes:",
        "",
    ]
    for title, bullets in sections:
        lines.append(f"- {title}")
        lines.extend(f"  - {bullet}" for bullet in bullets)

    if include_snippets and snippets:
        lines.append("- Illustrative snippets")
        for snippet in snippets:
            lines.append(f"  - `{snippet.label}`")
            lines.append(f"    ```{snippet.language}")
            lines.extend(f"    {code_line}" for code_line in snippet.code.splitlines())
            lines.append("    ```")

    return "\n".join(lines).strip()


def _build_description_of_change(
    repo: str,
    pr: PullRequestInfo,
    *,
    description_style: str,
    include_snippets: bool,
    max_snippets: int,
    snippet_lines: int,
    compact: bool,
    max_sections: int,
    max_bullets_per_section: int,
) -> str:
    patched_files = _fetch_pr_files_with_patch(repo, pr.number)
    useful_files = [
        file_info for file_info in patched_files if file_info.filename not in NOISE_FILES
    ]
    if useful_files:
        patched_files = useful_files

    sections = _build_human_sections(patched_files)
    if compact:
        sections = _compact_sections(
            sections,
            max_sections=max_sections,
            max_bullets_per_section=max_bullets_per_section,
        )

    snippets: list[Snippet] = []
    if include_snippets:
        snippets = _extract_snippets(
            patched_files,
            max_snippets=max_snippets,
            max_lines=snippet_lines,
        )

    if description_style == "bullets":
        return _build_bulleted_description(
            pr,
            sections,
            include_snippets=include_snippets,
            snippets=snippets,
        )

    if description_style == "hybrid":
        return _build_hybrid_description(
            pr,
            sections,
            include_snippets=include_snippets,
            snippets=snippets,
        )

    return _build_prose_description(
        pr,
        sections,
        include_snippets=include_snippets,
        snippets=snippets,
    )


def _format_context_link(context_link: str | None) -> str:
    if context_link is None:
        return ""
    text = context_link.strip()
    if not text:
        return ""
    if re.match(r"^https?://", text):
        return f"Context: {text}"
    return text


def _build_pr_body(
    repo: str,
    pr: PullRequestInfo,
    pr_chain: list[int],
    style: StyleTemplate,
    reason_override: str | None,
    context_link: str | None,
    include_pr_tree: bool,
    description_style: str,
    include_snippets: bool,
    max_snippets: int,
    snippet_lines: int,
    compact: bool,
    max_sections: int,
    max_bullets_per_section: int,
) -> str:
    reason_text = reason_override.strip() if reason_override else style.reason_text.strip()
    context_link_text = _format_context_link(context_link)
    description_of_change = _build_description_of_change(
        repo=repo,
        pr=pr,
        description_style=description_style,
        include_snippets=include_snippets,
        max_snippets=max_snippets,
        snippet_lines=snippet_lines,
        compact=compact,
        max_sections=max_sections,
        max_bullets_per_section=max_bullets_per_section,
    )
    verification_block = style.verification_block.strip()
    include_verification_comment = "<!--" not in verification_block

    lines = [
        "## Reason for Change",
        "",
        "<!-- Describe the bug or feature -->",
        "",
        reason_text if reason_text else DEFAULT_REASON,
    ]
    if context_link_text:
        lines.extend(["", context_link_text])
    if include_pr_tree and pr_chain:
        lines.extend(["", "PR Tree", _chain_tree(pr_chain, pr.number)])
    lines.extend(
        [
            "",
            "## Description of Change",
            "",
            "<!-- What actually changed and how was it implemented? -->",
            "",
            description_of_change,
            "",
            "## Criticality of Change",
            "",
            style.criticality_block.strip(),
            "",
            "## Verification",
        ]
    )
    if include_verification_comment:
        lines.extend(["", "<!-- How have you proven this change works?-->"])
    lines.extend(
        [
            "",
            verification_block,
            "",
            "## Release Notes",
            "",
            style.release_notes_block.strip(),
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _write_outputs(outputs: dict[int, str], write_dir: Path | None, print_stdout: bool) -> None:
    if write_dir is not None:
        write_dir.mkdir(parents=True, exist_ok=True)
        for pr_number, body in outputs.items():
            out_path = write_dir / f"pr_{pr_number}.md"
            out_path.write_text(body, encoding="utf-8")
            print(f"Wrote {out_path}")

    if print_stdout:
        first = True
        for pr_number, body in outputs.items():
            if not first:
                print("\n" + "=" * 80 + "\n")
            first = False
            print(f"# PR #{pr_number}\n")
            print(body.rstrip())


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prs",
        nargs="+",
        type=_parse_pr_number,
        help="Ordered PR chain as numbers, #numbers, or PR URLs.",
    )
    parser.add_argument(
        "--repo",
        default="ZiplineTeam/FlightSystems",
        help="GitHub repo in OWNER/REPO format (default: ZiplineTeam/FlightSystems).",
    )
    parser.add_argument(
        "--style-pr",
        type=_parse_pr_number,
        default=None,
        help="PR number used as style source (can be outside provided PR list).",
    )
    parser.add_argument(
        "--reason",
        default=None,
        help="Override shared Reason for Change text before PR Tree; for stacks, keep it identical across PRs.",
    )
    parser.add_argument(
        "--context-link",
        default=None,
        help="Optional markdown or URL line to append in Reason for Change.",
    )
    parser.add_argument(
        "--write-dir",
        type=Path,
        default=None,
        help="Directory to write per-PR markdown files (pr_<number>.md).",
    )
    parser.add_argument(
        "--include-pr-tree",
        dest="include_pr_tree",
        action="store_true",
        default=None,
        help="Force-include a PR Tree block (default for multi-PR chains).",
    )
    parser.add_argument(
        "--omit-pr-tree",
        dest="include_pr_tree",
        action="store_false",
        help="Omit the PR Tree block, even for a multi-PR chain.",
    )
    parser.add_argument(
        "--description-style",
        choices=("hybrid", "prose", "bullets"),
        default="hybrid",
        help="Description of Change script-rendered style (default: hybrid); manually rewrite to diagrams/tables when clearer.",
    )
    parser.add_argument(
        "--tiny",
        action="store_true",
        help="Emit a shorter Description of Change.",
    )
    parser.add_argument(
        "--include-snippets",
        action="store_true",
        help="Include short illustrative code snippets in Description of Change.",
    )
    parser.add_argument(
        "--max-snippets",
        type=int,
        default=1,
        help="Maximum number of snippets to include when --include-snippets is set.",
    )
    parser.add_argument(
        "--snippet-lines",
        type=int,
        default=10,
        help="Maximum lines per snippet when --include-snippets is set.",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Disable compact mode and keep all generated sections and bullets.",
    )
    parser.add_argument(
        "--max-sections",
        type=int,
        default=DEFAULT_MAX_SECTIONS,
        help=f"Maximum top-level Description sections in compact mode (default: {DEFAULT_MAX_SECTIONS}).",
    )
    parser.add_argument(
        "--max-sub-bullets",
        type=int,
        default=DEFAULT_MAX_BULLETS_PER_SECTION,
        help=f"Maximum sub-bullets per section in compact mode (default: {DEFAULT_MAX_BULLETS_PER_SECTION}).",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print generated bodies to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    if not args.stdout and args.write_dir is None:
        args.stdout = True

    try:
        _require_gh()
        prs = [_fetch_pr(args.repo, number) for number in args.prs]
        style = _infer_style_template(args.repo, prs, args.style_pr)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    outputs: dict[int, str] = {}
    max_sections = max(1, args.max_sections)
    max_sub_bullets = max(1, args.max_sub_bullets)
    include_pr_tree = args.include_pr_tree
    if include_pr_tree is None:
        include_pr_tree = len(args.prs) > 1
    if args.tiny:
        max_sections = min(max_sections, 2)
        max_sub_bullets = min(max_sub_bullets, 2)
    for pr in prs:
        outputs[pr.number] = _build_pr_body(
            repo=args.repo,
            pr=pr,
            pr_chain=args.prs,
            style=style,
            reason_override=args.reason,
            context_link=args.context_link,
            include_pr_tree=include_pr_tree,
            description_style=args.description_style,
            include_snippets=args.include_snippets,
            max_snippets=max(0, args.max_snippets),
            snippet_lines=max(2, args.snippet_lines),
            compact=not args.detailed,
            max_sections=max_sections,
            max_bullets_per_section=max_sub_bullets,
        )

    _write_outputs(outputs, args.write_dir, print_stdout=args.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
