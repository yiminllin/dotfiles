from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import JsonDict
from .presets import COMPATIBILITY_ALIASES, PRESETS, alias_targets


SOURCE_RELATIVE_PATHS = (
    "hil/ci/workflow/utils/default_test_configs.py",
    "hil/ci/workflow/utils/test_plan.py",
    ".github/workflows/p2-zip-system-hil-build.yml",
    ".github/workflows/hil-test.yml",
    "hil/p2_tests/phoenix_missions/config.py",
)


@dataclass
class ExtractedTest:
    name: str
    display_name: str = ""
    runner_args: str = ""
    test_record_query: str = ""
    source_paths: set[str] = field(default_factory=set)

    def to_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "runner_args": self.runner_args,
            "test_record_query": self.test_record_query,
            "source_paths": sorted(self.source_paths),
        }


def build_sync_check(systems_root: str = "/Systems") -> JsonDict:
    root = Path(systems_root)
    source_paths = {relative: root / relative for relative in SOURCE_RELATIVE_PATHS}
    blockers: list[JsonDict] = []
    parsed_sources: list[str] = []
    presence_only_sources: list[str] = []

    extracted: dict[str, ExtractedTest] = {}
    primary = source_paths["hil/ci/workflow/utils/default_test_configs.py"]
    if primary.is_file():
        try:
            extracted = extract_default_test_configs(primary)
            parsed_sources.append(str(primary))
        except (OSError, SyntaxError, ValueError) as exc:
            blockers.append(source_blocker(primary, f"failed to parse primary HIL defaults: {exc}"))
    else:
        blockers.append(source_blocker(primary, "primary HIL defaults source is not readable"))

    for relative, path in source_paths.items():
        if relative == "hil/ci/workflow/utils/default_test_configs.py":
            continue
        if path.is_file():
            parsed_sources.append(str(path))
            presence_only_sources.append(str(path))
        else:
            blockers.append(source_blocker(path, "optional source is not readable"))

    comparison = compare_presets(extracted) if extracted else empty_comparison()
    status = "ok"
    if comparison["missing_presets"] or comparison["extra_presets"] or comparison["extra_aliases"] or comparison["mismatches"]:
        status = "mismatch"
    if not extracted or any(blocker.get("required") for blocker in blockers):
        status = "error"

    return {
        "status": status,
        "systems_root": str(root),
        "source_paths": parsed_sources,
        "comparison_source_paths": [str(primary)] if extracted else [],
        "presence_only_source_paths": presence_only_sources,
        "notes": [
            "Canonical preset comparison is statically parsed from default_test_configs.py; optional workflow/test-plan sources are presence-only in this check."
        ],
        "blockers": blockers,
        "counts": {
            "systems_canonical": len(extracted),
            "local_canonical": len(PRESETS),
            "aliases": len(alias_targets()),
            "missing_presets": len(comparison["missing_presets"]),
            "extra_presets": len(comparison["extra_presets"]),
            "extra_aliases": len(comparison["extra_aliases"]),
            "mismatches": len(comparison["mismatches"]),
        },
        "missing_presets": comparison["missing_presets"],
        "extra_presets": comparison["extra_presets"],
        "extra_aliases": comparison["extra_aliases"],
        "intentional_aliases": COMPATIBILITY_ALIASES,
        "mismatches": comparison["mismatches"],
        "systems_tests": [test.to_dict() for test in sorted(extracted.values(), key=lambda item: item.name)],
    }


def extract_default_test_configs(path: Path) -> dict[str, ExtractedTest]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    valid_tests = extract_valid_tests(tree)
    default_displays = extract_default_display_names(tree, valid_tests)
    runner_args = extract_runner_args(tree, valid_tests)
    if not default_displays:
        raise ValueError("no DefaultTestConfigs._defaults entries found")

    extracted: dict[str, ExtractedTest] = {}
    for enum_name, display_name in default_displays.items():
        canonical = valid_tests.get(enum_name, enum_name.lower())
        args = runner_args.get(enum_name, f"run --test-name {canonical}")
        extracted[canonical] = ExtractedTest(
            name=canonical,
            display_name=display_name.strip(),
            runner_args=args,
            test_record_query=test_record_query_from_runner_args(args, canonical),
            source_paths={str(path)},
        )
    return extracted


def extract_valid_tests(tree: ast.AST) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "ValidTest":
            continue
        for statement in node.body:
            if not isinstance(statement, ast.Assign):
                continue
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    result[target.id] = target.id.lower()
    return result


def extract_default_display_names(tree: ast.AST, valid_tests: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            enum_name = valid_test_key_name(key)
            if not enum_name or enum_name not in valid_tests:
                continue
            display_name = tuple_string_item(value, 2)
            if display_name:
                result[enum_name] = display_name
    return result


def extract_runner_args(tree: ast.AST, valid_tests: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        value = assigned_dict_value(node, "_TEST_TARGETS")
        if value is None:
            continue
        for key, item in zip(value.keys, value.values):
            enum_name = valid_test_key_name(key)
            if enum_name in valid_tests:
                result[enum_name] = tuple_string_item(item, 1)
    return result


def assigned_dict_value(node: ast.AST, name: str) -> ast.Dict | None:
    if isinstance(node, ast.Assign):
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets) and isinstance(node.value, ast.Dict):
            return node.value
    if isinstance(node, ast.AnnAssign):
        if isinstance(node.target, ast.Name) and node.target.id == name and isinstance(node.value, ast.Dict):
            return node.value
    return None


def valid_test_key_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "ValidTest":
        return node.attr
    return None


def tuple_string_item(node: ast.AST, index: int) -> str:
    if not isinstance(node, ast.Tuple) or len(node.elts) <= index:
        return ""
    value = node.elts[index]
    return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else ""


def test_record_query_from_runner_args(args: str, canonical: str) -> str:
    bracket_match = re.search(r"\[([^\]]+)\]", args)
    if bracket_match:
        return bracket_match.group(1)
    k_match = re.search(r"(?:^|\s)-k\s+([^\s]+)", args)
    if k_match:
        return k_match.group(1)
    marker_match = re.search(r"(?:^|\s)-m\s+([^\s]+)", args)
    if marker_match:
        return marker_match.group(1)
    legacy_match = re.search(r"--test-name\s+([^\s]+)", args)
    if legacy_match:
        return legacy_match.group(1)
    return canonical


def compare_presets(extracted: dict[str, ExtractedTest]) -> JsonDict:
    systems_names = set(extracted)
    local_names = set(PRESETS)
    local_aliases = alias_targets()
    expected_aliases = {alias for alias, target in COMPATIBILITY_ALIASES.items() if target in systems_names}

    mismatches = []
    for name in sorted(local_names & systems_names):
        preset = PRESETS[name]
        source = extracted[name]
        if not (preset.run_title_fragments or preset.job_name_fragments or preset.test_record_query):
            mismatches.append({"preset": name, "field": "matchers", "message": "preset has no matcher fragments"})
        if not contains_fragment(preset.job_name_fragments, f"HIL Test: {name}"):
            mismatches.append({"preset": name, "field": "job_name_fragments", "message": f"missing HIL Test: {name}"})
        if source.display_name and not contains_fragment(preset.job_name_fragments, source.display_name):
            mismatches.append(
                {
                    "preset": name,
                    "field": "job_name_fragments",
                    "message": "missing /Systems display name fragment",
                    "expected": source.display_name,
                }
            )
        if source.test_record_query and preset.test_record_query != source.test_record_query:
            mismatches.append(
                {
                    "preset": name,
                    "field": "test_record_query",
                    "message": "local query differs from /Systems runner args",
                    "expected": source.test_record_query,
                    "actual": preset.test_record_query,
                }
            )

    return {
        "missing_presets": sorted(systems_names - local_names),
        "extra_presets": sorted(local_names - systems_names),
        "extra_aliases": sorted(set(local_aliases) - expected_aliases),
        "mismatches": mismatches,
    }


def empty_comparison() -> JsonDict:
    return {"missing_presets": [], "extra_presets": [], "extra_aliases": [], "mismatches": []}


def contains_fragment(fragments: tuple[str, ...], expected: str) -> bool:
    normalized_expected = normalize_text(expected)
    return any(normalize_text(fragment) == normalized_expected for fragment in fragments)


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def source_blocker(path: Path, message: str) -> JsonDict:
    return {"tool": "local", "path": str(path), "message": message, "required": path.name == "default_test_configs.py"}


def render_sync_check_text(report: JsonDict) -> str:
    lines = [f"hil_evidence preset sync-check: {report.get('status')}"]
    counts = report.get("counts") or {}
    lines.append(
        "counts: systems={systems_canonical} local={local_canonical} aliases={aliases} "
        "missing={missing_presets} extra={extra_presets} extra_aliases={extra_aliases} mismatches={mismatches}".format(**counts)
    )
    lines.append(f"systems_root: {report.get('systems_root')}")
    append_list(lines, "comparison_source_paths", report.get("comparison_source_paths") or [])
    append_list(lines, "presence_only_source_paths", report.get("presence_only_source_paths") or [])
    append_list(lines, "notes", report.get("notes") or [])
    append_list(lines, "missing_presets", report.get("missing_presets") or [])
    append_list(lines, "extra_presets", report.get("extra_presets") or [])
    append_list(lines, "extra_aliases", report.get("extra_aliases") or [])
    append_list(lines, "mismatches", [format_mismatch(item) for item in report.get("mismatches") or []])
    append_list(lines, "blockers", [format_blocker(item) for item in report.get("blockers") or []])
    return "\n".join(lines).rstrip() + "\n"


def render_sync_check_markdown(report: JsonDict) -> str:
    lines = ["# hil_evidence preset sync-check", "", f"- Status: `{report.get('status')}`"]
    counts = report.get("counts") or {}
    lines.append(
        "- Counts: systems `{systems_canonical}`, local `{local_canonical}`, aliases `{aliases}`, "
        "missing `{missing_presets}`, extra `{extra_presets}`, extra aliases `{extra_aliases}`, mismatches `{mismatches}`".format(**counts)
    )
    lines.append(f"- Systems root: `{report.get('systems_root')}`")
    lines.append("")
    for title, values in (
        ("Comparison source paths", report.get("comparison_source_paths") or []),
        ("Presence-only source paths", report.get("presence_only_source_paths") or []),
        ("Notes", report.get("notes") or []),
        ("Missing presets", report.get("missing_presets") or []),
        ("Extra presets", report.get("extra_presets") or []),
        ("Extra aliases", report.get("extra_aliases") or []),
        ("Mismatches", [format_mismatch(item) for item in report.get("mismatches") or []]),
        ("Blockers", [format_blocker(item) for item in report.get("blockers") or []]),
    ):
        lines.extend([f"## {title}", ""])
        lines.extend(f"- {value}" for value in values) if values else lines.append("_None._")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def append_list(lines: list[str], title: str, values: list[Any]) -> None:
    lines.append(f"{title}:")
    if not values:
        lines.append("  - none")
        return
    lines.extend(f"  - {value}" for value in values)


def format_mismatch(item: JsonDict) -> str:
    expected = f" expected={item.get('expected')!r}" if item.get("expected") is not None else ""
    actual = f" actual={item.get('actual')!r}" if item.get("actual") is not None else ""
    return f"{item.get('preset')}: {item.get('field')}: {item.get('message')}{expected}{actual}"


def format_blocker(item: JsonDict) -> str:
    required = "required" if item.get("required") else "optional"
    return f"{required}: {item.get('path')}: {item.get('message')}"
