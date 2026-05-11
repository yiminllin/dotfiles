#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from phoenix_inspector import hil, specs, taxonomy, text_search, zml
from phoenix_inspector.inventory import build_inventory
from phoenix_inspector.models import EvidenceReport
from phoenix_inspector.reports import render_json, render_markdown, write_report
from phoenix_inspector.sources import resolve_source

CLI = 'python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py"'


def main() -> int:
  try:
    args = parse_args()
    report = dispatch(args)
  except ValueError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    return 2
  report.exit_code = 1 if report.status == "error" else 0
  output = emit(report, args)
  if output:
    print(output, end="")
  specs.remember_last_run(report)
  return report.exit_code


def dispatch(args: argparse.Namespace) -> EvidenceReport:
  if args.command == "inventory":
    return command_inventory(args)
  if args.command == "inspect":
    return command_inspect(args)
  if args.command == "search-logs":
    return text_search.search_logs_report(args)
  if args.command == "validators":
    return text_search.validators_report(args)
  if args.command == "journal":
    return text_search.journal_report(args)
  if args.command == "topics":
    return zml.topics_report(args.source, args.pattern, args.backend, args.systems_root, args.format, args.fuzzy, args.limit)
  if args.command in {"fields", "find-field"}:
    return zml.fields_report(args)
  if args.command == "extract":
    return zml.extract_report(args)
  if args.command == "compare":
    return zml.compare_report(args)
  if args.command == "recent-hil":
    return hil.recent_hil_report(args)
  if args.command == "sync-check":
    return hil.sync_check_report(args)
  if args.command == "taxonomy":
    return taxonomy.taxonomy_recent_hil(args)
  if args.command == "spec" and args.spec_command == "init":
    return specs.init_spec(args.name, args.out, args.from_last_run)
  if args.command == "spec" and args.spec_command == "validate":
    return specs.validate_spec_report(args.spec_yaml, args.fixture or [])
  raise ValueError("unsupported command")


def command_inventory(args: argparse.Namespace) -> EvidenceReport:
  resolved = resolve_source(args.source, "inventory", {"backend": args.backend, "systems_root": args.systems_root})
  if resolved.resolved_type in {"gha_url", "s3_root"}:
    return hil.inventory_remote_report(args.source, args)
  inventory = build_inventory(resolved)
  report = EvidenceReport(title="Phoenix Source Inventory", status="blocked" if inventory.blockers or resolved.blockers else "ok", sources=[resolved], inventories=[inventory], blockers=[*resolved.blockers, *inventory.blockers], summary=f"Inventoried `{args.source}` as `{resolved.resolved_type}` with {len(inventory.artifacts)} artifact(s).", confidence="medium" if inventory.artifacts else "blocked")
  report.evidence_table.append({"finding": "source inventory", "source_ref": args.source, "supports": "Classifies available local artifacts and generated outputs.", "does_not_prove": "Does not inspect signal values or prove root cause."})
  report.proves.append("The explicit source was classified without broad discovery.")
  report.does_not_prove.append("Inventory does not prove artifact completeness beyond the explicit source.")
  report.next_commands.append(f"{CLI} inspect {args.source}")
  return report


def command_inspect(args: argparse.Namespace) -> EvidenceReport:
  resolved = resolve_source(args.source, "inspect", {"spec": args.spec, "backend": args.backend, "systems_root": args.systems_root})
  if args.spec and resolved.resolved_type in {"gha_url", "s3_root"}:
    report = hil.inventory_remote_report(args.source, args)
    from phoenix_inspector.models import Blocker

    report.title = "Phoenix Inspect"
    report.blockers.append(Blocker("remote_spec_requires_local_artifacts", "warning", "missing_artifact", "Remote spec execution requires selected local artifacts after inventory identifies exact evidence paths.", args.source, "Download or provide selected local ZML/log artifacts, then rerun inspect --spec with the local path."))
    report.status = "partial" if report.status == "ok" else report.status
    return report
  if args.spec:
    return specs.inspect_with_spec(args.source, args.spec)
  if resolved.resolved_type in {"gha_url", "s3_root"}:
    report = hil.inventory_remote_report(args.source, args)
    report.title = "Phoenix Inspect"
    return report
  inventory = build_inventory(resolved)
  blockers = [*resolved.blockers, *inventory.blockers]
  report_status = "blocked" if blockers else "ok"
  report = EvidenceReport(title="Phoenix Inspect", status=report_status, sources=[resolved], inventories=[inventory], blockers=blockers, summary=f"Inspected `{args.source}` as an inventory-oriented evidence source with {len(inventory.artifacts)} artifact(s).", confidence="blocked" if blockers else "medium")
  report.evidence_table.append({"finding": "source inventory", "source_ref": args.source, "supports": "Classifies available artifacts and points to field-first or direct signal follow-up.", "does_not_prove": "Does not run diagnostic recipes or prove root cause."})
  report.proves.append("The explicit source was classified without broad rediscovery.")
  report.does_not_prove.append("Inventory-oriented inspection does not prove signal behavior or causality.")
  report.next_commands.extend([
    f"{CLI} fields {args.source} --fuzzy FIELD_OR_SIGNAL_NAME",
    f"{CLI} search-logs {args.source} --query REGEX",
    f"{CLI} validators {args.source}",
    f"{CLI} journal {args.source}",
    f"{CLI} topics {args.source} --fuzzy TOPIC_FAMILY",
    f"{CLI} extract <zml> --topic TOPIC --field FIELD",
    f"{CLI} compare --fail FAIL --pass PASS --topic TOPIC --field FIELD",
    f"{CLI} spec init --name my-question --from-last-run",
  ])
  return report


def emit(report: EvidenceReport, args: argparse.Namespace) -> str:
  output_format = getattr(args, "format", "markdown")
  out_dir = getattr(args, "out_dir", None)
  if out_dir:
    _, output = write_report(report, output_format, out_dir, report.title.lower())
    return output
  return render_json(report) if output_format == "json" else render_markdown(report)


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(prog="phoenix_inspector", description="Canonical read-only Phoenix/HIL/GHA/ZML evidence inspector.")
  add_common(parser)
  subparsers = parser.add_subparsers(dest="command", required=True)

  inventory = subparsers.add_parser("inventory", help="Inventory a GHA URL, s3:// prefix, local log dir, ZML, packet JSON, or local bundle.")
  inventory.add_argument("source")
  add_common(inventory)
  add_hil_common(inventory)

  inspect = subparsers.add_parser("inspect", help="Inspect source inventory and suggest field-first or spec follow-up.", description="Inventory-oriented, field-first inspection. Use fields/find-field when a field is known but topic is unknown, then extract directly once topic and field are known. Use --spec for reusable ad hoc recipes.")
  inspect.add_argument("source", help="Explicit GHA/S3/local/ZML/packet source to classify")
  inspect.add_argument("--spec", help="Reusable investigation spec YAML/JSON")
  add_common(inspect)

  search_logs = subparsers.add_parser("search-logs", help="Search inventoried local non-ZML text artifacts with a bounded regex.", description="Bounded line-oriented regex search over inventoried local non-ZML text artifacts. Does not download remote artifacts, broad-scan directories, or read binary/ZML files.")
  search_logs.add_argument("source", help="Explicit local log bundle, selected artifact path, packet, GHA URL, or S3 prefix")
  search_logs.add_argument("--query", required=True, help="Python regular expression to search for")
  add_text_search_args(search_logs)

  validators = subparsers.add_parser("validators", help="Search validator output artifacts for failure signatures.", description="Preset text search for validator failure signatures in inventoried local validator artifacts. Pass --query to override the default regex.")
  validators.add_argument("source")
  validators.add_argument("--query", help="Override validator failure regex")
  add_text_search_args(validators)

  journal = subparsers.add_parser("journal", help="Search journal artifacts for watchdog/service/alarm signatures.", description="Preset case-insensitive text search for watchdog, service, alarm, restart, and process-status signatures in inventoried local journal artifacts. Pass --query to override the default regex.")
  journal.add_argument("source")
  journal.add_argument("--query", help="Override journal regex")
  add_text_search_args(journal)

  topics = subparsers.add_parser("topics", help="List topics in a local ZML/ZST source.", description="Topic-family discovery for local ZML/ZST sources. Prefer fields/find-field when the field or signal name is already known.")
  topics.add_argument("source", help="Local ZML/ZST file or bounded log directory")
  topics.add_argument("--pattern", help="Keep topics containing this substring")
  topics.add_argument("--fuzzy", help="Fuzzy-search topics by substring, tokens, and approximate matching")
  topics.add_argument("--limit", type=positive_int, default=20, help="Maximum fuzzy topic matches to show (default: 20)")
  topics.add_argument("--format", choices=("markdown", "json", "both"), default="markdown")
  topics.add_argument("--out-dir")
  add_backend_common(topics)

  fields = subparsers.add_parser("fields", help="Field-first discovery across candidate ZMLs; use when the field/signal is known but topic is not.", description="Field-first discovery across candidate ZMLs. Use this before extract when a field/signal name is known but the topic is not.")
  add_fields_args(fields)

  find_field = subparsers.add_parser("find-field", help="Alias for fields.", description="Alias for field-first discovery across candidate ZMLs.")
  add_fields_args(find_field)

  extract = subparsers.add_parser("extract", help="Extract one topic/field selection from a local ZML/ZST source.", description="Direct extract path once the local ZML/ZST source, topic, and field selection are known.")
  extract.add_argument("source", help="Local ZML/ZST file or bounded log directory")
  extract.add_argument("--topic", required=True)
  extract.add_argument("--field", action="append", required=True)
  add_window_args(extract)
  extract.add_argument("--csv", help="Write extracted sample rows to CSV")
  extract.add_argument("--plot", help="Reserved static plot output path; reports a blocker until plotting is backed")
  extract.add_argument("--plot-dir", help="Reserved static plot output directory")
  add_common(extract)

  compare = subparsers.add_parser("compare", help="Compare explicit failing and passing sources.", description="Generic differential evidence workflow. Use --topic/--field, --preset, or --spec; presets are non-diagnostic topic/field bundles.")
  compare.add_argument("--fail", required=True, help="Failing local ZML/ZST source")
  compare.add_argument("--pass", dest="pass_source", required=True, help="Passing local ZML/ZST source")
  group = compare.add_mutually_exclusive_group(required=True)
  group.add_argument("--spec")
  group.add_argument("--preset")
  group.add_argument("--topic")
  compare.add_argument("--field", action="append")
  compare.add_argument("--align", choices=("auto", "absolute", "event", "manual"), default="auto")
  compare.add_argument("--time-tolerance", type=nonnegative_float, default=0.0)
  compare.add_argument("--numeric-tolerance", type=nonnegative_float, default=0.0)
  compare.add_argument("--csv")
  add_window_args(compare)
  add_common(compare)

  recent = subparsers.add_parser("recent-hil", help="Find recent HIL source candidates without deep diagnosis.")
  recent.add_argument("--preset")
  recent.add_argument("--passing", action="store_true")
  recent.add_argument("--branch")
  recent.add_argument("--job-name")
  recent.add_argument("--title")
  recent.add_argument("--status", action="append", default=[])
  recent.add_argument("--conclusion", action="append", default=[])
  recent.add_argument("--test-record-query")
  recent.add_argument("--lookback-hours", type=positive_float)
  recent.add_argument("--limit", type=positive_int, help="Workflow runs to list/search before filtering; sparse presets may need high values such as 1000")
  recent.add_argument("--max-matches", type=positive_int, default=10, help="Matching jobs/candidates to return after filtering (default: 10)")
  add_common(recent)

  sync = subparsers.add_parser("sync-check", help="Wrap HIL preset sync checks in canonical report contracts.")
  sync.add_argument("source", nargs="?", default="/Systems", help="Compatibility source argument; --systems-root controls the checked root")
  sync.add_argument("--preset")
  add_common(sync)

  tax = subparsers.add_parser("taxonomy", help="Build batch taxonomy from evidence reports or recent HIL candidates.")
  tax_sub = tax.add_subparsers(dest="taxonomy_command", required=True)
  tax_recent = tax_sub.add_parser("recent-hil", help="Taxonomize recent HIL candidates conservatively.")
  tax_recent.add_argument("--limit", type=positive_int, help="Workflow runs to list/search before filtering; sparse presets may need high values such as 1000")
  tax_recent.add_argument("--load-evidence", action="store_true", help="For returned matches only, load bounded per-job HIL evidence before labeling")
  tax_recent.add_argument("--csv")
  tax_recent.add_argument("--report", action="append", help="Load an existing EvidenceReport JSON row; repeatable")
  add_common(tax_recent)
  add_recent_filter_args(tax_recent)

  spec = subparsers.add_parser("spec", help="Investigation spec workflows.")
  spec_sub = spec.add_subparsers(dest="spec_command", required=True)
  spec_init = spec_sub.add_parser("init", help="Initialize a reusable investigation spec.")
  spec_init.add_argument("--name", required=True)
  spec_init.add_argument("--from-last-run", action="store_true", required=True)
  spec_init.add_argument("--out")
  add_common(spec_init)
  spec_validate = spec_sub.add_parser("validate", help="Run a reusable investigation spec against explicit fixtures.")
  spec_validate.add_argument("spec_yaml")
  spec_validate.add_argument("--fixture", action="append", required=True)
  add_common(spec_validate)
  return parser.parse_args()


def add_fields_args(fields: argparse.ArgumentParser) -> None:
  fields.add_argument("source")
  fields.add_argument("--fuzzy", required=True, help="Fuzzy/substring query for field names or paths")
  fields.add_argument("--topic", action="append", help="Restrict discovery to this exact topic; repeatable")
  fields.add_argument("--topic-contains", action="append", help="Restrict candidate topics to this substring; repeatable")
  fields.add_argument("--topic-regex", action="append", help="Restrict candidate topics to this regular expression; repeatable")
  fields.add_argument("--topic-fuzzy", help="Fuzzy-search candidate topics before bounded sampling")
  fields.add_argument("--sample-limit", type=nonnegative_int, default=5, help="Maximum parsed samples per sampled topic (default: 5)")
  fields.add_argument("--sample-top", type=nonnegative_int, default=0, help="Sample only the top N metadata/fallback candidates for examples or no-index discovery (default: 0)")
  fields.add_argument("--no-sample", action="store_true", help="Disable decoded sample fallback; report metadata/index matches only")
  fields.add_argument("--limit", type=nonnegative_int, default=20, help="Maximum field matches to show (default: 20)")
  fields.add_argument("--max-zmls", type=positive_int, default=200, help="Maximum candidate ZML files under a directory (default: 200)")
  fields.add_argument("--workers", type=positive_int, default=4, help="Maximum concurrent ZML metadata/list probes for field discovery (default: 4)")
  fields.add_argument("--max-topics", type=nonnegative_int, default=500, help="Maximum candidate topics considered per ZML before sampling (default: 500)")
  fields.add_argument("--max-topics-sampled", type=nonnegative_int, default=25, help="Hard cap on topics read for field discovery (default: 25)")
  fields.add_argument("--max-fields-per-topic", type=nonnegative_int, default=1000, help="Hard cap on flattened unique fields tracked per topic (default: 1000)")
  fields.add_argument("--format", choices=("markdown", "json", "both"), default="markdown")
  fields.add_argument("--out-dir")
  add_backend_common(fields)


def add_text_search_args(parser: argparse.ArgumentParser) -> None:
  parser.add_argument("--artifact-type", action="append", help="Restrict search to this inventory artifact type; repeatable")
  parser.add_argument("--max-matches", type=positive_int, default=text_search.DEFAULT_MAX_MATCHES, help=f"Maximum total matches to report (default: {text_search.DEFAULT_MAX_MATCHES})")
  parser.add_argument("--context", type=nonnegative_int, default=text_search.DEFAULT_CONTEXT, help="Context lines before and after each match (default: 0)")
  parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
  parser.add_argument("--out-dir")


def add_common(parser: argparse.ArgumentParser) -> None:
  parser.add_argument("--format", choices=("markdown", "json", "both"), default="markdown", help=argparse.SUPPRESS)
  parser.add_argument("--out-dir", help=argparse.SUPPRESS)
  add_backend_common(parser, suppress=True)


def add_backend_common(parser: argparse.ArgumentParser, suppress: bool = False) -> None:
  parser.add_argument("--backend", choices=zml.BACKEND_CHOICES, default="auto", help=argparse.SUPPRESS if suppress else "ZML backend (default: auto)")
  parser.add_argument("--systems-root", default=zml.default_systems_root(), help=argparse.SUPPRESS if suppress else "Systems checkout root for Phoenix-aware backends (default: /Systems when present)")


def add_hil_common(parser: argparse.ArgumentParser) -> None:
  parser.add_argument("--preset")
  parser.add_argument("--passing", action="store_true")
  parser.add_argument("--max-inventory-items", type=positive_int, default=500)
  parser.add_argument("--max-test-records", type=positive_int, default=20)


def add_recent_filter_args(parser: argparse.ArgumentParser) -> None:
  parser.add_argument("--preset")
  parser.add_argument("--passing", action="store_true")
  parser.add_argument("--branch")
  parser.add_argument("--job-name")
  parser.add_argument("--title")
  parser.add_argument("--status", action="append", default=[])
  parser.add_argument("--conclusion", action="append", default=[])
  parser.add_argument("--test-record-query")
  parser.add_argument("--lookback-hours", type=positive_float)
  parser.add_argument("--max-matches", type=positive_int, default=10, help="Matching jobs/rows returned and processed after filtering (default: 10)")


def add_window_args(parser: argparse.ArgumentParser) -> None:
  parser.add_argument("--start")
  parser.add_argument("--end")
  parser.add_argument("--center")
  parser.add_argument("--duration", type=positive_float)


def positive_int(raw: str) -> int:
  value = int(raw)
  if value < 1:
    raise argparse.ArgumentTypeError("must be at least 1")
  return value


def nonnegative_int(raw: str) -> int:
  value = int(raw)
  if value < 0:
    raise argparse.ArgumentTypeError("must be greater than or equal to 0")
  return value


def positive_float(raw: str) -> float:
  value = float(raw)
  if value <= 0:
    raise argparse.ArgumentTypeError("must be greater than 0")
  return value


def nonnegative_float(raw: str) -> float:
  value = float(raw)
  if value < 0:
    raise argparse.ArgumentTypeError("must be greater than or equal to 0")
  return value


if __name__ == "__main__":
  sys.exit(main())
