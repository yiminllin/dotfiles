#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from phoenix_inspector import hil, text_search, zml
from phoenix_inspector.inventory import build_inventory
from phoenix_inspector.models import EvidenceReport
from phoenix_inspector.reports import render_json, render_markdown, write_report
from phoenix_inspector.sources import resolve_source

CLI = 'python3 "$HOME/dotfiles/scripts/phoenix_inspector.py"'


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
  return report.exit_code


def dispatch(args: argparse.Namespace) -> EvidenceReport:
  if args.command == "inventory":
    return command_inventory(args)
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
  if args.command == "summary":
    return zml.summary_report(args)
  if args.command == "compare":
    return zml.compare_report(args)
  if args.command == "recent-hil":
    return hil.recent_hil_report(args)
  raise ValueError("unsupported command")


def command_inventory(args: argparse.Namespace) -> EvidenceReport:
  resolved = resolve_source(args.source, "inventory", {"backend": args.backend, "systems_root": args.systems_root})
  if resolved.resolved_type in {"gha_url", "s3_root"}:
    return hil.inventory_remote_report(args.source, args)
  inventory = build_inventory(resolved)
  blockers = [*resolved.blockers]
  for blocker in inventory.blockers:
    if blocker not in blockers:
      blockers.append(blocker)
  report = EvidenceReport(title="Phoenix Source Inventory", status="blocked" if blockers else "ok", sources=[resolved], inventories=[inventory], blockers=blockers, summary=f"Inventoried `{args.source}` as `{resolved.resolved_type}` with {len(inventory.artifacts)} artifact(s).", confidence="medium" if inventory.artifacts else "blocked")
  report.evidence_table.append({"finding": "source inventory", "source_ref": args.source, "supports": "Classifies available local artifacts and generated outputs.", "does_not_prove": "Does not inspect signal values or prove root cause."})
  report.proves.append("The explicit source was classified without broad discovery.")
  report.does_not_prove.append("Inventory does not prove artifact completeness beyond the explicit source.")
  if resolved.resolved_type not in {"unsupported_flight_id", "unsupported_packet_json", "unsupported_archive", "unknown"}:
    report.next_commands.extend([
      f"{CLI} fields {args.source} --fuzzy FIELD_OR_SIGNAL_NAME",
      f"{CLI} search-logs {args.source} --query REGEX",
      f"{CLI} validators {args.source}",
      f"{CLI} journal {args.source}",
      f"{CLI} topics {args.source} --fuzzy TOPIC_FAMILY",
      f"{CLI} extract <zml> --topic TOPIC --field FIELD",
      f"{CLI} compare --fail FAIL --pass PASS --topic TOPIC --field FIELD",
    ])
  return report


def emit(report: EvidenceReport, args: argparse.Namespace) -> str:
  output_format = getattr(args, "format", "markdown")
  out_dir = getattr(args, "out_dir", None)
  if out_dir:
    _, output = write_report(report, output_format, out_dir, report.title.lower())
    return output
  return render_json(report) if output_format == "json" else render_markdown(report)


HELP_FORMATTER = argparse.RawDescriptionHelpFormatter


class HelpfulArgumentParser(argparse.ArgumentParser):
  def error(self, message: str) -> None:
    self.print_help(sys.stderr)
    self.exit(2, f"\nerror: {message}\n")


TOP_LEVEL_EPILOG = f"""examples:
  {CLI} inventory /tmp/hil-run
  {CLI} inventory /tmp/run.zml.zst
  {CLI} inventory https://github.com/ZiplineTeam/FlightSystems/actions/runs/123456789
  {CLI} fields /tmp/run.zml.zst --fuzzy flight_phase_for_controller
  {CLI} extract /tmp/run.zml.zst --topic /nav --field pose.x --csv /tmp/pi/nav.csv
  {CLI} summary /tmp/pi/nav.csv --metric transitions --metric minmax --metric delta

source placeholders are explicit paths/URLs only; run "{CLI} inventory -h" for supported source forms.
Run "{CLI} <command> -h" for command-specific examples.
"""

INVENTORY_EPILOG = f"""source forms:
  Local log dir or extracted bundle: /tmp/hil-run or /tmp/gha-artifacts/run-123/
  Local ZML/ZST:                   /tmp/run.zml or /tmp/run.zml.zst
  GHA run/job URL:                 https://github.com/ZiplineTeam/FlightSystems/actions/runs/123456789[/job/987654321]
  S3 prefix:                       s3://bucket/path/to/run/   (prefix only; bucket roots are refused)

examples:
  {CLI} inventory /tmp/hil-run
  {CLI} inventory /tmp/run.zml.zst --format json
  {CLI} inventory https://github.com/ZiplineTeam/FlightSystems/actions/runs/123456789
  {CLI} inventory s3://zipline-artifacts/hil/runs/123456789/
"""

SEARCH_LOGS_EPILOG = f"""examples:
  {CLI} search-logs /tmp/hil-run --query 'Traceback|Exception|Error Code' --context 2
  {CLI} search-logs /tmp/hil-run --query 'FAIL_VALIDATORS|FAIL_TEST' --artifact-type test_log --max-matches 50

Remote GHA/S3 sources are inventoried but not downloaded; provide a bounded local bundle for text search.
"""

VALIDATORS_EPILOG = f"""examples:
  {CLI} validators /tmp/hil-run
  {CLI} validators /tmp/hil-run --query 'FAIL_VALIDATORS|Error Code' --context 1
"""

JOURNAL_EPILOG = f"""examples:
  {CLI} journal /tmp/hil-run
  {CLI} journal /tmp/hil-run --query 'watchdog|service|restart|alarm' --context 2
"""

TOPICS_EPILOG = f"""examples:
  {CLI} topics /tmp/run.zml.zst --pattern nav --systems-root /Systems
  {CLI} topics /tmp/run.zml.zst --fuzzy controller --limit 20 --backend zml-cli
"""

FIELDS_EPILOG = f"""examples:
  {CLI} fields /tmp/run.zml.zst --fuzzy flight_phase_for_controller
  {CLI} fields /tmp/hil-run --fuzzy pseudorange --topic-fuzzy gnss --sample-top 3 --format json
  {CLI} find-field /tmp/run.zml.zst --fuzzy pose.x --topic-contains nav
"""

EXTRACT_EPILOG = f"""examples:
  {CLI} extract /tmp/run.zml.zst --topic /nav --field pose.x --csv /tmp/pi/nav.csv
  {CLI} extract /tmp/run.zml.zst --topic /nav --field pose.x --field pose.y --start 10 --end 20
  {CLI} extract /tmp/run.zml.zst --topic /nav --all-fields --csv /tmp/pi/nav-all.csv
"""

SUMMARY_EPILOG = f"""examples:
  {CLI} summary /tmp/pi/nav.csv --metric transitions
  {CLI} summary /tmp/pi/nav-all.csv --metric transitions --metric minmax --metric delta
  {CLI} summary /tmp/pi/nav-all.csv --metric minmax --field pose.x
"""

COMPARE_EPILOG = f"""examples:
  {CLI} compare --fail /tmp/fail.zml.zst --pass /tmp/pass.zml.zst --topic /nav --field pose.x --out-dir /tmp/pi
  {CLI} compare --fail /tmp/fail.zml.zst --pass /tmp/pass.zml.zst --topic /nav --field pose.x --csv /tmp/pi/compare.csv
  {CLI} compare --fail /tmp/fail.zml.zst --pass /tmp/pass.zml.zst --preset gnss-timing
"""

RECENT_HIL_EPILOG = f"""examples:
  {CLI} recent-hil --preset zip_autokiosk --passing --max-matches 3
  {CLI} recent-hil --branch main --job-name HIL --conclusion failure --lookback-hours 24 --limit 200 --max-matches 5

Read-only remote discovery only; requires already-working gh/aws credentials when remote data is queried.
"""

def add_command(subparsers: argparse._SubParsersAction, name: str, **kwargs) -> argparse.ArgumentParser:
  return subparsers.add_parser(name, formatter_class=HELP_FORMATTER, **kwargs)


def parse_args() -> argparse.Namespace:
  parser = HelpfulArgumentParser(prog="phoenix_inspector", description="Canonical read-only Phoenix/HIL/GHA/ZML evidence inspector.", epilog=TOP_LEVEL_EPILOG, formatter_class=HELP_FORMATTER)
  add_common(parser)
  subparsers = parser.add_subparsers(dest="command", required=True, parser_class=HelpfulArgumentParser)

  inventory = add_command(subparsers, "inventory", help="Inventory a GHA URL, s3:// prefix, local log dir/extracted bundle, or ZML file.", epilog=INVENTORY_EPILOG)
  inventory.add_argument("source", help="Explicit source path/URL; see supported source forms below")
  add_output_args(inventory)
  add_backend_common(inventory, suppress=True)

  search_logs = add_command(subparsers, "search-logs", help="Search inventoried local non-ZML text artifacts with a bounded regex.", description="Bounded line-oriented regex search over inventoried local non-ZML text artifacts. Does not download remote artifacts, broad-scan directories, or read binary/ZML files.", epilog=SEARCH_LOGS_EPILOG)
  search_logs.add_argument("source", help="Explicit local log bundle, selected local text artifact path, GHA URL, or S3 prefix")
  search_logs.add_argument("--query", required=True, help="Python regular expression to search for")
  add_text_search_args(search_logs)

  validators = add_command(subparsers, "validators", help="Search validator output artifacts for failure signatures.", description="Preset text search for validator failure signatures in inventoried local validator artifacts. Pass --query to override the default regex.", epilog=VALIDATORS_EPILOG)
  validators.add_argument("source", help="Explicit local log bundle or selected local artifact path")
  validators.add_argument("--query", help="Override validator failure regex")
  add_text_search_args(validators)

  journal = add_command(subparsers, "journal", help="Search journal artifacts for watchdog/service/alarm signatures.", description="Preset case-insensitive text search for watchdog, service, alarm, restart, and process-status signatures in inventoried local journal artifacts. Pass --query to override the default regex.", epilog=JOURNAL_EPILOG)
  journal.add_argument("source", help="Explicit local log bundle or selected local artifact path")
  journal.add_argument("--query", help="Override journal regex")
  add_text_search_args(journal)

  topics = add_command(subparsers, "topics", help="List topics in a local ZML/ZST source.", description="Topic-family discovery for local ZML/ZST sources. Prefer fields/find-field when the field or signal name is already known.", epilog=TOPICS_EPILOG)
  topics.add_argument("source", help="Local ZML/ZST file or bounded log directory")
  topics.add_argument("--pattern", help="Keep topics containing this substring")
  topics.add_argument("--fuzzy", help="Fuzzy-search topics by substring, tokens, and approximate matching")
  topics.add_argument("--limit", type=positive_int, default=20, help="Maximum fuzzy topic matches to show (default: 20)")
  topics.add_argument("--format", choices=("markdown", "json", "both"), default="markdown")
  topics.add_argument("--out-dir")
  add_backend_common(topics)

  fields = add_command(subparsers, "fields", help="Field-first discovery across candidate ZMLs; use when the field/signal is known but topic is not.", description="Field-first discovery across candidate ZMLs. Use this before extract when a field/signal name is known but the topic is not.", epilog=FIELDS_EPILOG)
  add_fields_args(fields)

  find_field = add_command(subparsers, "find-field", help="Alias for fields.", description="Alias for field-first discovery across candidate ZMLs.", epilog=FIELDS_EPILOG)
  add_fields_args(find_field)

  extract = add_command(subparsers, "extract", help="Extract one topic/field selection from a local ZML/ZST source.", description="Direct extract path once the local ZML/ZST source, topic, and field selection are known.", epilog=EXTRACT_EPILOG)
  extract.add_argument("source", help="Local ZML/ZST file or bounded log directory")
  extract.add_argument("--topic", required=True)
  extract_selection = extract.add_mutually_exclusive_group(required=True)
  extract_selection.add_argument("--field", action="append")
  extract_selection.add_argument("--all-fields", action="store_true", help="Extract every field for the requested topic")
  add_window_args(extract)
  extract.add_argument("--csv", help="Write extracted sample rows to CSV")
  add_common(extract)

  summary = add_command(subparsers, "summary", help="Summarize Phoenix Inspector extracted CSV metrics.", description="Summarize CSVs written by extract --csv. The supported shape is path,topic,timestamp,field,value; simple CSVs with timestamp/field/value are accepted best-effort.", epilog=SUMMARY_EPILOG)
  summary.add_argument("csv", help="CSV produced by extract --csv")
  summary.add_argument("--metric", action="append", choices=("transitions", "minmax", "delta"), required=True, help="Metric to compute; repeatable")
  summary.add_argument("--field", action="append", help="Restrict to this field; repeatable. Defaults to all fields.")
  add_common(summary)

  compare = add_command(subparsers, "compare", help="Compare explicit failing and passing sources.", description="Generic differential evidence workflow. Use --topic/--field or --preset; presets are non-diagnostic topic/field bundles.", epilog=COMPARE_EPILOG)
  compare.add_argument("--fail", required=True, help="Failing local ZML/ZST source")
  compare.add_argument("--pass", dest="pass_source", required=True, help="Passing local ZML/ZST source")
  group = compare.add_mutually_exclusive_group(required=True)
  group.add_argument("--preset")
  group.add_argument("--topic")
  compare.add_argument("--field", action="append")
  compare.add_argument("--align", choices=("auto", "absolute", "event", "manual"), default="auto")
  compare.add_argument("--time-tolerance", type=nonnegative_float, default=0.0)
  compare.add_argument("--numeric-tolerance", type=nonnegative_float, default=0.0)
  compare.add_argument("--csv")
  add_window_args(compare)
  add_common(compare)

  recent = add_command(subparsers, "recent-hil", help="Find recent HIL source candidates without deep diagnosis.", epilog=RECENT_HIL_EPILOG)
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


def add_output_args(parser: argparse.ArgumentParser) -> None:
  parser.add_argument("--format", choices=("markdown", "json", "both"), default="markdown")
  parser.add_argument("--out-dir")


def add_backend_common(parser: argparse.ArgumentParser, suppress: bool = False) -> None:
  parser.add_argument("--backend", choices=zml.BACKEND_CHOICES, default="auto", help=argparse.SUPPRESS if suppress else "ZML backend (default: auto)")
  parser.add_argument("--systems-root", default=zml.default_systems_root(), help=argparse.SUPPRESS if suppress else "Systems checkout root for Phoenix-aware backends (default: /Systems when present)")


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
