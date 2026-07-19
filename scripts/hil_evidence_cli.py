#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from hil_evidence import build_recent_packet, build_summary_packet, render_markdown
from hil_evidence.models import DEFAULT_REPO
from hil_evidence.presets import PRESET_CONFIGS
from hil_evidence.render import render_json
from hil_evidence.sync import build_sync_check, render_sync_check_markdown, render_sync_check_text


def main() -> int:
    args = parse_args()
    if args.command in {"sync-check", "check-presets"}:
        report = build_sync_check(args.systems_root)
        if args.format == "json":
            print(render_json(report), end="")
        elif args.format == "markdown":
            print(render_sync_check_markdown(report), end="")
        else:
            print(render_sync_check_text(report), end="")
        return 0 if report.get("status") == "ok" else 1

    if args.format == "both" and not args.out_dir:
        print("ERROR: --format both requires --out-dir so JSON and markdown have separate stable paths", file=sys.stderr)
        return 2
    if args.command == "summarize":
        packet = build_summary_packet(
            args.target,
            repo=args.repo,
            job=args.job,
            preset=args.preset,
            passing=args.passing,
            max_jobs=args.max_jobs,
            max_inventory_items=args.max_inventory_items,
            max_test_records=args.max_test_records,
        )
        label = source_label("summary", packet.get("source") or {"input": args.target})
    else:
        packet = build_recent_packet(
            repo=args.repo,
            preset=args.preset,
            passing=args.passing,
            max_matches=args.max_matches,
            limit=args.limit,
            lookback_hours=args.lookback_hours,
            job_name=args.job_name,
            title=args.title,
            branch=args.branch,
            status=args.status,
            conclusion=args.conclusion,
            test_record_query=args.test_record_query,
            max_inventory_items=args.max_inventory_items,
            max_test_records=args.max_test_records,
        )
        label = slug("recent-{}{}-{}".format(args.preset or "hil", "-passing" if args.passing else "", args.max_matches))

    outputs = write_outputs(packet, args.out_dir, args.format, label)
    if outputs:
        for path in outputs:
            print(path)
    else:
        print(render_markdown(packet) if args.format == "markdown" else render_json(packet), end="")
    return 1 if packet.get("status") == "error" else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build read-only HIL/GHA evidence packets.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summarize = subparsers.add_parser("summarize", help="Summarize one run/job/S3/local source.")
    summarize.add_argument("target", help="GitHub Actions run/job URL, run id, S3 reference, or local log/test_record path")
    summarize.add_argument("--job", help="Job id or job URL when target is a run URL/id")
    summarize.add_argument("--preset", choices=sorted(PRESET_CONFIGS), help="Apply preset metadata and test_record query hints")
    summarize.add_argument("--passing", action="store_true", help="When summarizing a run, only process passing HIL jobs")
    add_common_args(summarize)

    recent = subparsers.add_parser("recent", help="Find and summarize recent real HIL jobs.")
    recent.add_argument("--preset", choices=sorted(PRESET_CONFIGS), help="Apply existing HIL finder preset filters")
    recent.add_argument("--passing", action="store_true", help="Only include completed successful jobs")
    recent.add_argument("--max-matches", type=positive_int, default=10, help="Maximum matching jobs to summarize")
    recent.add_argument("--limit", type=positive_int, help="Maximum workflow runs to list before local filtering")
    recent.add_argument(
        "--lookback-hours",
        type=positive_float,
        help="Recent run lookback window (default: 3000 for autokiosk presets, 72 otherwise)",
    )
    recent.add_argument("--job-name", help="Only include jobs whose name/display name contains this text")
    recent.add_argument("--title", help="Only include workflow runs whose display title contains this text")
    recent.add_argument("--branch", help="Only include workflow runs whose head branch contains this text")
    recent.add_argument("--status", action="append", default=[], help="Only include jobs with this status; repeatable")
    recent.add_argument("--conclusion", action="append", default=[], help="Only include jobs with this conclusion; repeatable")
    recent.add_argument(
        "--test-record-query",
        help="Confirm recent candidates by a test_record.json substring query; overrides the preset query when both are supplied",
    )
    add_common_args(recent)

    sync_check = subparsers.add_parser(
        "sync-check",
        aliases=["check-presets"],
        help="Compare local HIL presets with statically parsed /Systems HIL defaults.",
    )
    sync_check.add_argument("--systems-root", default="/Systems", help="Systems checkout root (default: /Systems)")
    sync_check.add_argument("--format", choices=("json", "text", "markdown"), default="text")
    return parser.parse_args()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub owner/repo (default: {DEFAULT_REPO})")
    parser.add_argument("--out-dir", help="Directory for packet.json / packet.md outputs; stdout is used when omitted")
    parser.add_argument("--format", choices=("json", "markdown", "both"), default="markdown")
    parser.add_argument("--max-jobs", type=positive_int, default=20, help="Maximum HIL jobs to process for a single run")
    parser.add_argument("--max-inventory-items", type=positive_int, default=500, help="Maximum S3 inventory entries per root")
    parser.add_argument("--max-test-records", type=positive_int, default=20, help="Maximum test_record.json files to read")


def write_outputs(packet: dict, out_dir: str | None, output_format: str, label: str) -> list[str]:
    if not out_dir:
        return []
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    outputs = []
    if output_format in {"json", "both"}:
        path = directory / f"{label}.json"
        path.write_text(render_json(packet), encoding="utf-8")
        outputs.append(str(path))
    if output_format in {"markdown", "both"}:
        path = directory / f"{label}.md"
        path.write_text(render_markdown(packet), encoding="utf-8")
        outputs.append(str(path))
    return outputs


def source_label(prefix: str, source: dict) -> str:
    if source.get("run_id") and source.get("job_id"):
        return slug(f"{prefix}-run-{source['run_id']}-job-{source['job_id']}")
    if source.get("run_id"):
        return slug(f"{prefix}-run-{source['run_id']}")
    if source.get("s3_uri"):
        return slug(f"{prefix}-{source['s3_uri']}")
    return slug(f"{prefix}-{source.get('input', 'source')}")


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
    return value[:120] or "packet"


def positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def positive_float(raw: str) -> float:
    value = float(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return value


if __name__ == "__main__":
    sys.exit(main())
