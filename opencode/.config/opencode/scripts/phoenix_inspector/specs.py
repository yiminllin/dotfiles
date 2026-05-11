from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from .models import Blocker, CheckResult, EvidenceReport


LAST_RUN_PATH = Path("/tmp/phoenix-inspector/last-run.json")
CLI = 'python3 "$HOME/.config/opencode/scripts/phoenix_inspector.py"'


def remember_last_run(report: EvidenceReport) -> None:
  LAST_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
  LAST_RUN_PATH.write_text(json.dumps(last_run_summary(report), indent=2), encoding="utf-8")


def last_run_summary(report: EvidenceReport) -> dict:
  return {
    "title": report.title,
    "status": report.status,
    "sources": [source.to_dict() for source in report.sources],
    "signal_requests": [result.request.to_dict() for result in report.signal_results],
    "check_results": [check.to_dict() for check in report.check_results],
    "output_paths": report.output_paths,
    "legacy_query": (report.extra.get("legacy_packet") or {}).get("query") if report.extra else None,
    "legacy_mode": (report.extra.get("legacy_packet") or {}).get("mode") if report.extra else None,
    "legacy_sources": (report.extra.get("legacy_packet") or {}).get("sources") if report.extra else None,
  }


def load_spec(path: str) -> dict:
  text = Path(path).read_text(encoding="utf-8")
  try:
    import yaml  # type: ignore

    value = yaml.safe_load(text)
  except Exception:
    value = json.loads(text)
  if not isinstance(value, dict):
    raise ValueError("spec must be a mapping")
  return value


def init_spec(name: str, out: str | None, from_last_run: bool) -> EvidenceReport:
  blockers = []
  last_run = {}
  if from_last_run:
    if not LAST_RUN_PATH.is_file():
      blockers.append(Blocker("last_run_missing", "error", "missing_artifact", "No last-run record exists for spec init.", str(LAST_RUN_PATH), "Run inventory/topics/extract/compare first, then retry spec init --from-last-run."))
      return EvidenceReport(title="Spec Init", status="blocked", blockers=blockers, summary="Spec init blocked because there is no last run.", confidence="blocked")
    last_run = json.loads(LAST_RUN_PATH.read_text(encoding="utf-8"))
  spec = {
    "name": name,
    "version": 1,
    "question": f"Reusable investigation for {name}",
    "applies_to": ["local_log_dir", "zml_file", "hil_packet_json"],
    "required_artifacts": [],
    "optional_artifacts": [],
    "extract": extract_operations_from_last_run(last_run),
    "compare": compare_operations_from_last_run(last_run),
    "evidence_limits": {"sample_rows": 20, "log_snippets": 10},
    "proves": ["The declared evidence was available and evaluated."],
    "does_not_prove": ["Does not prove root cause without source-specific corroboration."],
    "fixtures": [],
    "promotion": {"status": "candidate", "remaining_blockers": ["needs repeated cases and fixture-backed validation"]},
    "last_run": last_run,
  }
  operations = [*spec["extract"], *spec["compare"]]
  if from_last_run and not operations:
    blockers.append(Blocker("last_run_has_no_executable_operations", "warning", "validation_gap", "Last run did not contain rerunnable extract or compare operations.", str(LAST_RUN_PATH), "Run extract or compare successfully, then retry spec init --from-last-run."))
    return EvidenceReport(title="Spec Init", status="blocked", blockers=blockers, summary="Spec init blocked because the last run cannot be rerun as a spec.", confidence="blocked", extra={"spec": spec})
  path = Path(out or f"{name}.yaml")
  path.write_text(dump_yaml_like(spec), encoding="utf-8")
  report = EvidenceReport(title="Spec Init", status="ok", summary=f"Wrote reusable investigation spec to {path}.", confidence="medium", output_paths=[str(path)], extra={"spec": spec})
  report.proves.append("Spec was initialized from bounded local last-run metadata." if from_last_run else "Spec draft was initialized.")
  report.does_not_prove.append("Spec initialization does not turn a recipe into a diagnostic workflow.")
  return report


def inspect_with_spec(source: str, spec_path: str) -> EvidenceReport:
  from .inventory import build_inventory
  from .sources import resolve_source

  spec = load_spec(spec_path)
  resolved = resolve_source(source, "inspect", {"spec": spec_path})
  inventory = build_inventory(resolved)
  blockers = list(inventory.blockers)
  operations = spec_operations(spec)
  checks = [CheckResult("spec-loaded", "pass", f"Loaded spec `{spec.get('name')}` with {len(operations)} executable operation(s).")]
  signal_results = []
  evidence_rows = []
  if not operations:
    blockers.append(Blocker("spec_has_no_operations", "warning", "validation_gap", "Spec declares no executable extract or compare operations.", spec_path, "Add at least one extract topic/field or compare operation before treating this as a successful investigation."))
  for operation in operations:
    op_report = run_spec_operation(source, inventory, operation)
    signal_results.extend(op_report.signal_results)
    blockers.extend(op_report.blockers)
    evidence_rows.extend(op_report.evidence_table)
    checks.append(CheckResult(f"spec-{operation['kind']}", "pass" if op_report.status == "ok" else "blocked", op_report.summary, observed={"operation": operation}, blockers=op_report.blockers))
  status = spec_status(blockers, signal_results)
  report = EvidenceReport(title=f"Spec Inspect: {spec.get('name')}", status=status, sources=[resolved], inventories=[inventory], signal_results=signal_results, check_results=checks, blockers=blockers, evidence_table=evidence_rows, summary=f"Ran reusable investigation spec `{spec.get('name')}` against `{source}`.", confidence="medium" if status == "ok" else "blocked")
  report.proves.extend(spec.get("proves") or [])
  report.does_not_prove.extend(spec.get("does_not_prove") or [])
  report.next_commands.append(f"{CLI} spec validate {spec_path} --fixture {source}")
  return report


def validate_spec_report(spec_path: str, fixtures: list[str]) -> EvidenceReport:
  spec = load_spec(spec_path)
  blockers = []
  checks = []
  if not fixtures:
    blockers.append(Blocker("fixture_required", "error", "validation_gap", "Spec validation requires at least one --fixture.", needed_action="Pass one or more local fixture sources."))
  if not spec_operations(spec):
    blockers.append(Blocker("spec_has_no_operations", "warning", "validation_gap", "Spec declares no executable operations to validate.", spec_path, "Add extract or compare operations before validation."))
  for fixture in fixtures:
    if not Path(fixture).exists():
      blockers.append(Blocker("fixture_missing", "error", "missing_artifact", "Fixture path is missing.", fixture, "Provide an existing fixture path."))
      continue
    result = inspect_with_spec(fixture, spec_path)
    blockers.extend(result.blockers)
    checks.append(CheckResult("fixture-spec-run", "pass" if result.status == "ok" else "blocked", f"Spec run against {fixture}: {result.status}", observed={"fixture": fixture, "signal_result_count": len(result.signal_results)}, blockers=result.blockers))
  status = "ok" if not blockers else "blocked"
  return EvidenceReport(title="Spec Validate", status=status, check_results=checks, blockers=blockers, summary=f"Validated spec `{spec.get('name')}` against {len(fixtures)} fixture(s).", confidence="medium" if status == "ok" else "blocked", proves=["Fixture spec execution ran."], does_not_prove=["Spec validation does not create a fixture-backed diagnostic workflow by itself."])


def spec_operations(spec: dict) -> list[dict]:
  operations = []
  for item in spec.get("extract") or []:
    if item.get("topic"):
      operations.append({"kind": "extract", "topic": item["topic"], "fields": field_list(item), "backend": item.get("backend"), "systems_root": item.get("systems_root")})
  for item in spec.get("compare") or []:
    operations.append({"kind": "compare", **item})
  return operations


def run_spec_operation(source: str, inventory, operation: dict) -> EvidenceReport:
  from . import zml

  if operation["kind"] == "extract":
    zml_source = source_for_extract(source, inventory)
    if not zml_source:
      blocker = Blocker("spec_extract_missing_zml", "warning", "missing_artifact", "Spec extract operation needs a local ZML/ZST file, but inventory found none.", source, "Provide a local ZML/ZST source or a log directory containing one.")
      return EvidenceReport(title="Spec Extract", status="blocked", blockers=[blocker], summary="Spec extract blocked by missing local ZML evidence.")
    args = SimpleNamespace(source=zml_source, topic=operation["topic"], field=operation.get("fields") or [], start=None, end=None, center=None, duration=None, backend=operation.get("backend") or "auto", systems_root=operation.get("systems_root") or "/Systems", csv=None, plot=None, plot_dir=None, format="json")
    return zml.extract_report(args)
  if operation["kind"] == "compare":
    fail = operation.get("fail") or operation.get("fail_source")
    passing = operation.get("pass") or operation.get("pass_source")
    if not fail or not passing:
      blocker = Blocker("spec_compare_missing_sources", "warning", "not_implemented", "Spec compare operation needs explicit fail/pass sources.", needed_action="Add fail and pass source paths to the compare operation, or run compare directly.")
      return EvidenceReport(title="Spec Compare", status="blocked", blockers=[blocker], summary="Spec compare blocked by missing fail/pass sources.")
    window = operation.get("window") or {}
    args = SimpleNamespace(fail=fail, pass_source=passing, topic=operation.get("topic"), field=operation.get("fields") or [], preset=operation.get("preset"), spec=None, start=window.get("start"), end=window.get("end"), center=window.get("center"), duration=window.get("duration"), backend=operation.get("backend") or "auto", systems_root=operation.get("systems_root") or "/Systems", time_tolerance=float(operation.get("time_tolerance") or 0), numeric_tolerance=float(operation.get("numeric_tolerance") or 0), csv=None, format="json")
    return zml.compare_report(args)
  blocker = Blocker("spec_operation_not_implemented", "warning", "not_implemented", f"Spec operation kind `{operation.get('kind')}` is not implemented.")
  return EvidenceReport(title="Spec Operation", status="blocked", blockers=[blocker], summary="Spec operation blocked.")


def source_for_extract(source: str, inventory) -> str | None:
  if inventory.source.resolved_type == "zml_file":
    return source
  if inventory.zml_files:
    return inventory.zml_files[0].get("path")
  return None


def spec_status(blockers: list[Blocker], signal_results: list) -> str:
  if not blockers:
    return "ok"
  return "partial" if signal_results else "blocked"


def extract_operations_from_last_run(last_run: dict) -> list[dict]:
  if last_run.get("legacy_mode") == "compare":
    return []
  operations = []
  for request in last_run.get("signal_requests") or []:
    topics = request.get("topics") or []
    fields = request.get("fields") or []
    for topic in topics:
      operations.append({"topic": topic, "fields": fields})
  return operations


def compare_operations_from_last_run(last_run: dict) -> list[dict]:
  if last_run.get("legacy_mode") != "compare":
    return []
  query = last_run.get("legacy_query") or {}
  sources = last_run.get("legacy_sources") or []
  fail = (sources[0] or {}).get("input") if len(sources) > 0 and isinstance(sources[0], dict) else None
  passing = (sources[1] or {}).get("input") if len(sources) > 1 and isinstance(sources[1], dict) else None
  if not fail or not passing:
    return []
  backend = (query.get("backend") or {}).get("selected") or (query.get("backend") or {}).get("requested")
  tolerances = query.get("tolerances") or {}
  window = query.get("window") or {}
  operations = []
  for item in query.get("topics") or []:
    if item.get("name"):
      operation = {"topic": item.get("name"), "fields": item.get("fields") or [], "fail": fail, "pass": passing, "backend": backend}
      if window:
        operation["window"] = window
      if "time" in tolerances:
        operation["time_tolerance"] = tolerances["time"]
      if "numeric" in tolerances:
        operation["numeric_tolerance"] = tolerances["numeric"]
      operations.append(operation)
  return operations


def field_list(item: dict) -> list[str]:
  raw = item.get("fields") if "fields" in item else item.get("field")
  if raw is None:
    return []
  if isinstance(raw, str):
    return [raw]
  return list(raw)


def dump_yaml_like(value: dict) -> str:
  try:
    import yaml  # type: ignore

    return yaml.safe_dump(value, sort_keys=False)
  except Exception:
    return json.dumps(value, indent=2) + "\n"
