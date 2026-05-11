from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phoenix_inspector.hil import packet_report, sync_check_report
from phoenix_inspector.inventory import build_inventory
from phoenix_inspector.models import EvidenceReport, ProvenanceRef, RunSource
from phoenix_inspector.reports import render_markdown
from phoenix_inspector.sources import detect_source_type, resolve_source
from phoenix_inspector.specs import init_spec, inspect_with_spec, remember_last_run, validate_spec_report
from phoenix_inspector.taxonomy import classify_evidence, label_from_report, taxonomy_recent_hil
from phoenix_inspector.zml import BACKEND_CHOICES, AutoBackend, SafeZmlConvBackend, backend_adapter, compare_report, extract_report, fields_report, topics_report
from zml_audit.backends import BackendResult
from zml_audit.models import Blocker, TimeWindow

CLI_SPEC = importlib.util.spec_from_file_location("phoenix_inspector_cli", Path(__file__).parents[1] / "phoenix_inspector.py")
cli = importlib.util.module_from_spec(CLI_SPEC)
assert CLI_SPEC.loader is not None
CLI_SPEC.loader.exec_module(cli)


class PhoenixInspectorTests(unittest.TestCase):
  def write_text_search_fixture(self, root: Path) -> None:
    (root / "test_record.json").write_text('{"result":"failed","reason":"Error Code 44"}\n', encoding="utf-8")
    (root / "phoenix.log").write_text("boot\nError Code 17 in phoenix\nhealthy after error\n", encoding="utf-8")
    (root / "validator_summary.txt").write_text("validator suite\nFAIL_VALIDATORS Error Code 22\n", encoding="utf-8")
    (root / "process_status.log").write_text("startup\nWATCHDOG service restart requested\n", encoding="utf-8")
    (root / "test_log_case.log").write_text("setup\nFAIL_TEST exception in case\n", encoding="utf-8")
    (root / "flight.zml").write_text("Error Code NOT_SEARCHED\nFAIL_VALIDATORS NOT_SEARCHED\n", encoding="utf-8")

  def test_report_contract_serializes_required_fields(self) -> None:
    report = EvidenceReport(title="Contract", sources=[resolve_source("P2M_1C780E1120F27000", "inventory")])
    data = report.to_dict()

    self.assertEqual(data["schema_version"], "phoenix_inspector.report.v1")
    self.assertIn(data["status"], {"ok", "partial", "blocked", "error"})
    self.assertIn("generated_at", data)
    self.assertIn("unsupported_source", data["sources"][0]["blockers"][0]["category"])

  def test_source_detection_covers_supported_shapes(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      zml = root / "run.zml.zst"
      zml.write_text("", encoding="utf-8")
      packet = root / "packet.json"
      packet.write_text('{"mode":"summarize","jobs":[]}', encoding="utf-8")

      self.assertEqual(detect_source_type("https://github.com/ZiplineTeam/FlightSystems/actions/runs/123/job/456"), "gha_url")
      self.assertEqual(detect_source_type("s3://bucket/prefix/"), "s3_root")
      self.assertEqual(detect_source_type(str(root)), "local_log_dir")
      self.assertEqual(detect_source_type(str(zml)), "zml_file")
      self.assertEqual(detect_source_type(str(packet)), "hil_packet_json")
      self.assertEqual(detect_source_type("P2M_1C780E1120F27000"), "unsupported_flight_id")

  def test_s3_bucket_root_is_safety_blocked(self) -> None:
    resolved = resolve_source("s3://bucket", "inventory")

    self.assertEqual(resolved.blockers[0].code, "s3_bucket_root_refused")
    self.assertEqual(resolved.blockers[0].category, "safety_boundary")

  def test_local_inventory_classifies_key_artifacts_and_generated_outputs(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      (root / "test_record.json").write_text('{"test_info":{"name":"zip","result":"failed"}}', encoding="utf-8")
      (root / "compute.zml.zst").write_text("", encoding="utf-8")
      (root / "phoenix.log").write_text("ERROR boom", encoding="utf-8")
      (root / "validator_summary.json").write_text("{}", encoding="utf-8")
      reports = root / "reports"
      reports.mkdir()
      (reports / "phoenix_inspector.json").write_text("{}", encoding="utf-8")

      inventory = build_inventory(resolve_source(str(root), "inventory"))

    self.assertIn("test_record", inventory.key_artifacts)
    self.assertIn("zml_zst", inventory.key_artifacts)
    self.assertEqual(len(inventory.generated_outputs), 1)

  def test_text_artifact_search_presets_context_and_zml_skip(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      self.write_text_search_fixture(root)
      searched = cli.dispatch(type("Args", (), {"command": "search-logs", "source": str(root), "query": "Error Code", "artifact_type": None, "max_matches": 10, "context": 1, "format": "json", "out_dir": None})())
      validators = cli.dispatch(type("Args", (), {"command": "validators", "source": str(root), "query": None, "artifact_type": None, "max_matches": 10, "context": 0, "format": "json", "out_dir": None})())
      journal = cli.dispatch(type("Args", (), {"command": "journal", "source": str(root), "query": None, "artifact_type": None, "max_matches": 10, "context": 0, "format": "json", "out_dir": None})())

    matches = searched.extra["text_search"]["matches"]
    markdown = render_markdown(searched)
    self.assertEqual(searched.status, "ok")
    self.assertTrue(any(match["line_number"] == 2 and match["before"] and match["after"] for match in matches))
    self.assertFalse(any(match["path"].endswith(".zml") for match in matches))
    self.assertTrue(any(match["artifact_type"] == "test_record" for match in matches))
    self.assertIn("## Text Artifact Matches", markdown)
    self.assertIn("phoenix_log", markdown)
    self.assertTrue(all(match["artifact_type"] == "validator_output" for match in validators.extra["text_search"]["matches"]))
    self.assertTrue(any("FAIL_VALIDATORS" in match["text"] for match in validators.extra["text_search"]["matches"]))
    self.assertEqual(journal.extra["text_search"]["matches"][0]["artifact_type"], "journal")
    self.assertIn("WATCHDOG service", journal.extra["text_search"]["matches"][0]["text"])

  def test_text_artifact_search_remote_blocker_and_max_match_truncation(self) -> None:
    remote = cli.dispatch(type("Args", (), {"command": "search-logs", "source": "s3://bucket/prefix/", "query": "FAIL", "artifact_type": None, "max_matches": 10, "context": 0, "format": "json", "out_dir": None})())

    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      packet = root / "packet.json"
      packet.write_text(json.dumps({"mode": "summarize", "jobs": [{"s3": {"inventories": [{"key_artifact_hints": [{"category": "logs", "uri": "s3://bucket/prefix/phoenix.log"}]}]}}]}), encoding="utf-8")
      packet_blocked = cli.dispatch(type("Args", (), {"command": "search-logs", "source": str(packet), "query": "FAIL", "artifact_type": None, "max_matches": 10, "context": 0, "format": "json", "out_dir": None})())
      self.write_text_search_fixture(root)
      truncated = cli.dispatch(type("Args", (), {"command": "search-logs", "source": str(root), "query": "FAIL", "artifact_type": None, "max_matches": 1, "context": 0, "format": "json", "out_dir": None})())

    self.assertEqual(remote.status, "blocked")
    self.assertEqual(remote.blockers[-1].code, "text_search_requires_local_artifacts")
    self.assertEqual(packet_blocked.status, "blocked")
    self.assertEqual(packet_blocked.blockers[-1].code, "text_search_requires_local_artifacts")
    self.assertEqual(len(truncated.extra["text_search"]["matches"]), 1)
    self.assertEqual(truncated.status, "partial")
    self.assertTrue(truncated.extra["text_search"]["truncation"]["max_matches_reached"])

  def test_local_inventory_refuses_broad_root(self) -> None:
    inventory = build_inventory(resolve_source("/", "inventory"))

    self.assertEqual(inventory.blockers[0].code, "broad_directory_refused")
    self.assertEqual(inventory.blockers[0].category, "safety_boundary")

  def test_sync_check_uses_source_fallback_when_systems_root_missing(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      missing_root = Path(temp_dir) / "missing-systems"
      args = type("Args", (), {"systems_root": None, "source": str(missing_root)})()

      report = sync_check_report(args)

    self.assertEqual(report.status, "blocked")
    self.assertEqual(report.extra["legacy_packet"]["systems_root"], str(missing_root))
    self.assertEqual(report.check_results[0].status, "blocked")
    self.assertTrue(report.blockers)

  def test_hil_empty_match_statuses_are_blocked_not_ok(self) -> None:
    for legacy_status in ("no_matches", "no_hil_jobs"):
      with self.subTest(legacy_status=legacy_status):
        report = packet_report("Recent HIL Sources", {"status": legacy_status, "source": {"input": "filters"}}, [])

        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.blockers[0].code, legacy_status)
        self.assertEqual(report.blockers[0].category, "missing_artifact")

  def test_packet_inventory_extracts_embedded_context(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      packet = Path(temp_dir) / "packet.json"
      packet.write_text(json.dumps({"mode": "summarize", "jobs": [{"s3": {"baraza": {"mission_ids": ["P2M_x"]}, "inventories": [{"key_artifact_hints": [{"category": "zml", "uri": "s3://b/run.zml.zst"}]}]}}], "test_records": [{"test_name": "zip"}]}), encoding="utf-8")

      inventory = build_inventory(resolve_source(str(packet), "inventory"))

    self.assertEqual(inventory.baraza_context["source"], "embedded")
    self.assertIn("zml", inventory.key_artifacts)
    self.assertEqual(inventory.test_record["count"], 1)

  def test_markdown_report_has_stable_sections(self) -> None:
    markdown = render_markdown(EvidenceReport(title="Sections", proves=["p"], does_not_prove=["d"]))

    for heading in ("Summary", "Source and Inventory", "Evidence Table", "Signal and Check Findings", "Timebase and Alignment", "Proves / Does Not Prove", "Blockers and Missing Evidence", "Output Paths", "Next Commands"):
      self.assertIn(f"## {heading}", markdown)

  def test_local_text_zml_topics_extract_and_compare(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      fail = root / "fail.zml"
      passing = root / "pass.zml"
      fail.write_text('{"topic":"/nav","timestamp":1,"fields":{"pose":{"x":1},"arr":[{"v":2}]}}\n{"topic":"/nav","timestamp":2,"fields":{"pose":{"x":5},"arr":[{"v":3}]}}\n', encoding="utf-8")
      passing.write_text('{"topic":"/nav","timestamp":1,"fields":{"pose":{"x":1},"arr":[{"v":2}]}}\n{"topic":"/nav","timestamp":2,"fields":{"pose":{"x":3},"arr":[{"v":3}]}}\n', encoding="utf-8")
      csv_path = root / "extract.csv"

      topics = topics_report(str(fail), "/nav", "local-text", "/no-systems", "json")
      extract_args = type("Args", (), {"source": str(fail), "topic": "/nav", "field": ["pose.x", "arr[*].v"], "start": None, "end": None, "center": None, "duration": None, "backend": "local-text", "systems_root": "/no-systems", "csv": str(csv_path), "plot": None, "plot_dir": None, "format": "json"})()
      extracted = extract_report(extract_args)
      compare_args = type("Args", (), {"fail": str(fail), "pass_source": str(passing), "topic": "/nav", "field": ["pose.x"], "preset": None, "spec": None, "start": None, "end": None, "center": None, "duration": None, "backend": "local-text", "systems_root": "/no-systems", "time_tolerance": 0.0, "numeric_tolerance": 0.0, "csv": None, "format": "json"})()
      compared = compare_report(compare_args)

      self.assertEqual(topics.status, "ok")
      self.assertEqual(extracted.status, "ok")
      self.assertTrue(csv_path.is_file())
      self.assertEqual(compared.status, "ok")
      self.assertEqual(compared.signal_results[0].backend, "local-text")
      self.assertIn("first_divergences", compared.extra["legacy_packet"]["comparison"])

  def test_extract_report_uses_direct_known_extract_for_exact_topic_field(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml.zst"
      path.write_text("", encoding="utf-8")
      args = type("Args", (), {"source": str(path), "topic": "/nav", "field": ["x"], "start": None, "end": None, "center": None, "duration": None, "backend": "zml-cli", "systems_root": "/no-systems", "csv": None, "plot": None, "plot_dir": None, "format": "json"})()

      def fake_build_audit_packet(source, specs, window, **kwargs):
        self.assertEqual(source, str(path))
        self.assertEqual(specs[0].name, "/nav")
        self.assertEqual(specs[0].fields, ("x",))
        self.assertEqual(kwargs.get("direct_known_extract"), True)
        self.assertEqual(kwargs.get("systems_root"), "/no-systems")
        return {"schema_version": 1, "mode": "audit", "status": "ok", "query": {"topics": [specs[0].to_dict()], "backend": {"requested": "zml-cli"}}, "source": {"input": source, "kind": "file", "candidates": [source]}, "files": [{"path": source, "topics": [{"topic": "/nav", "present": True}], "backend": {"selected": "fake"}}], "blockers": []}

      with patch("phoenix_inspector.zml.build_audit_packet", side_effect=fake_build_audit_packet):
        report = extract_report(args)

    self.assertEqual(report.status, "ok")

  def test_fuzzy_topics_report_records_ranked_matches(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text('{"topic":"/controller/main_state","timestamp":1,"fields":{"x":1}}\n{"topic":"/control/controllr_status","timestamp":1,"fields":{"x":2}}\n', encoding="utf-8")

      report = topics_report(str(path), None, "local-text", "/no-systems", "json", fuzzy="controller", limit=1)

    matches = report.extra["legacy_packet"]["files"][0]["topic_matches"]
    self.assertEqual(report.status, "ok")
    self.assertEqual(matches[0]["topic"], "/controller/main_state")
    self.assertEqual(report.signal_results[0].stats["topic_matches"], matches)

  def test_local_text_fields_report_discovers_ranked_paths(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text('{"topic":"/compute_a.zip_executive.cloud_bound_status","timestamp":1,"fields":{"message":{"flight_phase_for_controller":"BOUND"},"measurements":[{"pseudorange":10}]}}\n', encoding="utf-8")
      args = type("Args", (), {"source": str(path), "fuzzy": "flight_phase_for_controller", "topic": None, "topic_contains": None, "topic_regex": None, "topic_fuzzy": "cloud_bound_status", "sample_limit": 2, "limit": 5, "max_topics_sampled": 3, "max_fields_per_topic": 20, "backend": "local-text", "systems_root": "/no-systems", "format": "json"})()

      report = fields_report(args)

    matches = report.extra["legacy_packet"]["files"][0]["field_matches"]
    markdown = render_markdown(report)
    self.assertEqual(report.status, "ok")
    self.assertEqual(matches[0]["field_path"], "message.flight_phase_for_controller")
    self.assertEqual(report.signal_results[0].stats["field_matches"], matches)
    self.assertIn("message.flight_phase_for_controller", markdown)

  def test_cli_parser_accepts_fuzzy_topics_args(self) -> None:
    with patch("sys.argv", ["phoenix_inspector.py", "topics", "run.zml", "--fuzzy", "controller", "--limit", "5", "--format", "both", "--systems-root", "/custom/Systems"]):
      args = cli.parse_args()

    self.assertEqual(args.fuzzy, "controller")
    self.assertEqual(args.limit, 5)
    self.assertEqual(args.format, "both")
    self.assertEqual(args.systems_root, "/custom/Systems")

  def test_cli_parser_accepts_fields_args(self) -> None:
    with patch("sys.argv", ["phoenix_inspector.py", "fields", "run.zml", "--fuzzy", "phase", "--topic-fuzzy", "cloud", "--sample-limit", "2", "--sample-top", "1", "--max-zmls", "5", "--workers", "2", "--max-topics", "6", "--no-sample"]):
      args = cli.parse_args()

    self.assertEqual(args.command, "fields")
    self.assertEqual(args.fuzzy, "phase")
    self.assertEqual(args.topic_fuzzy, "cloud")
    self.assertEqual(args.sample_limit, 2)
    self.assertEqual(args.sample_top, 1)
    self.assertEqual(args.max_zmls, 5)
    self.assertEqual(args.workers, 2)
    self.assertEqual(args.max_topics, 6)
    self.assertEqual(args.no_sample, True)

  def test_cli_parser_accepts_find_field_alias(self) -> None:
    with patch("sys.argv", ["phoenix_inspector.py", "find-field", "run.zml", "--fuzzy", "phase"]):
      args = cli.parse_args()

    self.assertEqual(args.command, "find-field")
    self.assertEqual(args.fuzzy, "phase")

  def test_find_field_format_both_writes_json_and_markdown_outputs(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      zml_path = root / "run.zml"
      out_dir = root / "fields"
      zml_path.write_text('{"topic":"/nav","timestamp":1,"fields":{"flight_phase_for_controller":"BOUND"}}\n', encoding="utf-8")

      with patch("sys.argv", ["phoenix_inspector.py", "find-field", str(zml_path), "--fuzzy", "flight_phase_for_controller", "--backend", "local-text", "--sample-top", "1", "--format", "both", "--out-dir", str(out_dir)]):
        args = cli.parse_args()
      report = cli.dispatch(args)
      output = cli.emit(report, args)

      self.assertEqual(args.format, "both")
      self.assertIn("zml-field-discovery.json", output)
      self.assertIn("zml-field-discovery.md", output)
      self.assertTrue((out_dir / "zml-field-discovery.json").is_file())
      self.assertTrue((out_dir / "zml-field-discovery.md").is_file())

  def test_cli_parser_accepts_text_search_commands_and_help(self) -> None:
    with patch("sys.argv", ["phoenix_inspector.py", "search-logs", "logs", "--query", "Error", "--artifact-type", "phoenix_log", "--max-matches", "5", "--context", "2"]):
      search_args = cli.parse_args()
    with patch("sys.argv", ["phoenix_inspector.py", "validators", "logs"]):
      validators_args = cli.parse_args()
    with patch("sys.argv", ["phoenix_inspector.py", "journal", "logs", "--query", "watchdog"]):
      journal_args = cli.parse_args()
    with patch("sys.argv", ["phoenix_inspector.py", "--help"]), patch("sys.stdout", new_callable=io.StringIO) as stdout:
      with self.assertRaises(SystemExit) as raised:
        cli.parse_args()

    self.assertEqual(search_args.command, "search-logs")
    self.assertEqual(search_args.artifact_type, ["phoenix_log"])
    self.assertEqual(search_args.max_matches, 5)
    self.assertEqual(search_args.context, 2)
    self.assertEqual(validators_args.command, "validators")
    self.assertEqual(journal_args.command, "journal")
    self.assertEqual(raised.exception.code, 0)
    self.assertIn("search-logs", stdout.getvalue())
    self.assertIn("validators", stdout.getvalue())
    self.assertIn("journal", stdout.getvalue())

  def test_cli_parser_keeps_lens_off_primary_surface(self) -> None:
    with patch("sys.argv", ["phoenix_inspector.py", "inspect", "run.zml", "--lens", "gnss-timing"]), patch("sys.stderr", new=io.StringIO()):
      with self.assertRaises(SystemExit):
        cli.parse_args()

    with patch("sys.argv", ["phoenix_inspector.py", "lens", "scaffold", "question.yaml", "--name", "candidate"]), patch("sys.stderr", new=io.StringIO()):
      with self.assertRaises(SystemExit):
        cli.parse_args()

  def test_binary_local_text_returns_structured_blocker(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "binary.zml.zst"
      path.write_bytes(b"\xff\x00\xff")

      report = topics_report(str(path), None, "local-text", "/no-systems", "json")

    self.assertEqual(report.status, "blocked")
    self.assertEqual(report.blockers[0].category, "backend_failure")

  def test_zml_refuses_broad_directory_before_legacy_resolver(self) -> None:
    report = topics_report("/", None, "auto", "/no-systems", "json")

    self.assertEqual(report.status, "blocked")
    self.assertEqual(report.blockers[0].category, "safety_boundary")

  def test_safe_zml_conv_uses_bazel_fallback_from_systems_root(self) -> None:
    calls = []

    def runner(command, **kwargs):
      calls.append((command, kwargs))
      return type("Completed", (), {"returncode": 0, "stdout": '{"topic":"/nav","timestamp":1}\n', "stderr": ""})()

    with patch("zml_audit.backends.shutil.which", side_effect=lambda binary: "/usr/bin/bazel" if binary == "bazel" else None), patch("zml_audit.backends.Path.exists", return_value=True):
      backend = SafeZmlConvBackend("/Systems")
      backend.backend.runner = runner
      result = backend.read_topic("missing.zml", "/nav", TimeWindow())

    self.assertIsNone(result.blocker)
    self.assertEqual(calls[0][0][:4], ["bazel", "run", "//tools/zml_conv:zml_conv", "--"])
    self.assertEqual(calls[0][1]["cwd"], "/Systems")
    self.assertEqual(result.metadata["systems_root"], "/Systems")

  def test_supported_backend_choices_exclude_python_adapter(self) -> None:
    self.assertEqual(BACKEND_CHOICES, ("auto", "zml-conv", "zml-cli", "local-text"))
    with self.assertRaises(ValueError):
      backend_adapter("python", "/Systems")

  def test_auto_backend_order_is_zml_conv_then_zml_cli(self) -> None:
    auto = AutoBackend("/Systems")

    self.assertEqual([backend.name for backend in auto.backends], ["zml-conv", "zml-cli"])

  def test_auto_backend_does_not_cache_path_specific_metadata_failure(self) -> None:
    class PathMetadataBackend:
      name = "path-metadata"

      def field_metadata(self, path: str) -> BackendResult:
        if path == "first.zml":
          return BackendResult(blocker=Blocker(tool=self.name, message="metadata failed for this file"), backend=self.name, metadata={"selected": self.name})
        return BackendResult(stdout='{"topics":[{"topic":"/second","fields":["target_field"]}]}', backend=self.name, metadata={"selected": self.name})

    auto = AutoBackend("/no-systems")
    auto.backends = [PathMetadataBackend()]

    first = auto.field_metadata("first.zml")
    second = auto.field_metadata("second.zml")

    self.assertIsNotNone(first.blocker)
    self.assertIsNone(second.blocker)
    self.assertIn("target_field", second.stdout)

  def test_auto_backend_does_not_cache_repeated_timeouts_before_later_success(self) -> None:
    class TimeoutThenSuccessBackend:
      name = "timeout-then-success"

      def __init__(self) -> None:
        self.calls: list[str] = []

      def field_metadata(self, path: str) -> BackendResult:
        self.calls.append(path)
        if path in {"first.zml", "second.zml"}:
          return BackendResult(blocker=Blocker(tool=self.name, message="field metadata timed out after 1.5s"), backend=self.name, metadata={"selected": self.name})
        return BackendResult(stdout='{"topics":[{"topic":"/third","fields":["target_field"]}]}', backend=self.name, metadata={"selected": self.name})

    backend = TimeoutThenSuccessBackend()
    auto = AutoBackend("/no-systems")
    auto.backends = [backend]

    first = auto.field_metadata("first.zml")
    second = auto.field_metadata("second.zml")
    third = auto.field_metadata("third.zml")

    self.assertIsNotNone(first.blocker)
    self.assertIsNotNone(second.blocker)
    self.assertIsNone(third.blocker)
    self.assertEqual(backend.calls, ["first.zml", "second.zml", "third.zml"])
    self.assertIn("target_field", third.stdout)

  def test_compare_csv_and_empty_spec_blocker_are_structured(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      fail = root / "fail.zml"
      passing = root / "pass.zml"
      csv_path = root / "compare.csv"
      spec_path = root / "empty.json"
      fail.write_text('{"topic":"/nav","timestamp":1,"fields":{"x":1}}\n', encoding="utf-8")
      passing.write_text('{"topic":"/nav","timestamp":1,"fields":{"x":2}}\n', encoding="utf-8")
      spec_path.write_text(json.dumps({"name": "empty", "compare": []}), encoding="utf-8")
      compare_args = type("Args", (), {"fail": str(fail), "pass_source": str(passing), "topic": "/nav", "field": ["x"], "preset": None, "spec": None, "start": None, "end": None, "center": None, "duration": None, "backend": "local-text", "systems_root": "/no-systems", "time_tolerance": 0.0, "numeric_tolerance": 0.0, "csv": str(csv_path), "format": "json"})()
      empty_spec_args = type("Args", (), {"fail": str(fail), "pass_source": str(passing), "topic": None, "field": None, "preset": None, "spec": str(spec_path), "start": None, "end": None, "center": None, "duration": None, "backend": "local-text", "systems_root": "/no-systems", "time_tolerance": 0.0, "numeric_tolerance": 0.0, "csv": None, "format": "json"})()

      compared = compare_report(compare_args)
      blocked = compare_report(empty_spec_args)

      self.assertEqual(compared.status, "ok")
      self.assertTrue(csv_path.is_file())
      self.assertEqual(blocked.status, "blocked")
      self.assertEqual(blocked.blockers[0].code, "compare_has_no_signal_selection")

  def test_compare_spec_uses_declared_compare_operation(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      fail = root / "fail.zml"
      passing = root / "pass.zml"
      spec = root / "compare.json"
      fail.write_text('{"topic":"/nav","timestamp":1,"fields":{"x":1}}\n', encoding="utf-8")
      passing.write_text('{"topic":"/nav","timestamp":1,"fields":{"x":2}}\n', encoding="utf-8")
      spec.write_text(json.dumps({"name": "compare", "compare": [{"topic": "/nav", "fields": ["x"]}], "proves": ["p"], "does_not_prove": ["d"]}), encoding="utf-8")
      args = type("Args", (), {"fail": str(fail), "pass_source": str(passing), "topic": None, "field": None, "preset": None, "spec": str(spec), "start": None, "end": None, "center": None, "duration": None, "backend": "local-text", "systems_root": "/no-systems", "time_tolerance": 0.0, "numeric_tolerance": 0.0, "csv": None, "format": "json"})()

      report = compare_report(args)

    self.assertEqual(report.status, "ok")
    self.assertIn("first_divergences", report.extra["legacy_packet"]["comparison"])

  def test_compare_preset_uses_preset_recipe_without_lens(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      fail = root / "fail.zml"
      passing = root / "pass.zml"
      fail.write_text('{"topic":"nav.state+","timestamp":1,"fields":{"clock_bias":10}}\n', encoding="utf-8")
      passing.write_text('{"topic":"nav.state+","timestamp":1,"fields":{"clock_bias":2}}\n', encoding="utf-8")
      args = type("Args", (), {"fail": str(fail), "pass_source": str(passing), "topic": None, "field": None, "preset": "gnss-timing", "spec": None, "start": None, "end": None, "center": None, "duration": None, "backend": "local-text", "systems_root": "/no-systems", "time_tolerance": 0.0, "numeric_tolerance": 0.0, "csv": None, "format": "json"})()

      report = compare_report(args)

    topic_names = [item["name"] for item in report.extra["legacy_packet"]["query"]["topics"]]
    self.assertEqual(report.status, "ok")
    self.assertIn("nav.state+", topic_names)

  def test_taxonomy_labels_backend_and_validation_blockers_conservatively(self) -> None:
    backend_label = label_from_report({"status": "blocked", "blockers": [{"category": "backend_failure"}]})
    validation_label = label_from_report({"status": "blocked", "blockers": [{"category": "validation_gap"}]})

    self.assertEqual(backend_label, "infra_or_artifact_failure")
    self.assertEqual(validation_label, "inconclusive")

  def test_taxonomy_classifies_synthetic_hil_evidence_markers(self) -> None:
    cases = [
      ({"job_conclusion": "success"}, None, "not_loaded", "pass"),
      ({"job_conclusion": "failure"}, {"jobs": [{"log_summary": {"validator_failures": [{"text": "Validator failed pose check"}]}}]}, "loaded", "validator_failure"),
      ({"job_conclusion": "failure"}, {"jobs": [{"log_summary": {"validator_failures": [{"text": "┃ Validator Name ┃ Passed ┃ Flight ID ┃ Failed Checks ┃ Details ┃"}]}}]}, "loaded", "unknown_after_evidence"),
      ({"job_conclusion": "failure"}, {"jobs": [{"log_summary": {"alarm_error_lines": [{"text": "ALARM geofence breach"}]}}]}, "loaded", "alarm_failure"),
      ({"job_conclusion": "failure"}, {"errors": [{"message": "command timed out after 120s"}]}, "blocked", "timeout"),
      ({"job_conclusion": "failure"}, {"jobs": [{"log_summary": {"alarm_error_lines": [{"text": "dashboard report push failed"}]}}]}, "loaded", "dashboard_push_or_reporting_issue"),
      ({"job_conclusion": "failure"}, {"jobs": [{"test_records": [{"test_name": "case", "result": "failed"}]}]}, "loaded", "test_harness_failure"),
      ({"job_conclusion": "failure"}, {"jobs": [{"test_records": [{"test_name": "case"}]}]}, "loaded", "unknown_after_evidence"),
      ({"job_conclusion": "failure"}, {"jobs": [{"log_summary": {"line_count": 3}}]}, "loaded", "unknown_after_evidence"),
      ({"job_conclusion": "failure"}, None, "not_loaded", "inconclusive"),
    ]

    for candidate, packet, status, expected in cases:
      with self.subTest(expected=expected):
        failure_reason, _, _ = classify_evidence(candidate, packet, status)

      self.assertEqual(failure_reason, expected)

  def test_taxonomy_recent_hil_loads_evidence_only_for_returned_matches(self) -> None:
    candidates = [
      {"gha_url": "https://github.com/ZiplineTeam/FlightSystems/actions/runs/1/job/101", "run_id": "1", "job_id": "101", "job_conclusion": "failure"},
      {"gha_url": "https://github.com/ZiplineTeam/FlightSystems/actions/runs/2/job/202", "run_id": "2", "job_id": "202", "job_conclusion": "failure"},
    ]
    recent = EvidenceReport(title="Recent HIL Sources", extra={"legacy_packet": {"candidates": candidates}})

    def packet_for(source: str, **_kwargs):
      if source.endswith("101"):
        return {"status": "ok", "jobs": [{"log_summary": {"validator_failures": [{"text": "Validator failed"}]}}]}
      return {"status": "ok", "jobs": [{"log_summary": {"alarm_error_lines": [{"text": "ALARM stop"}]}}]}

    with tempfile.TemporaryDirectory() as temp_dir:
      args = type("Args", (), {"report": None, "preset": "zip_autokiosk", "passing": False, "limit": 1, "max_matches": 2, "load_evidence": True, "csv": str(Path(temp_dir) / "taxonomy.csv"), "out_dir": str(Path(temp_dir) / "out")})()
      with patch("phoenix_inspector.taxonomy.recent_hil_report", return_value=recent), patch("phoenix_inspector.taxonomy.build_summary_packet", side_effect=packet_for) as build_packet:
        report = taxonomy_recent_hil(args)

      rows = report.extra["rows"]
      csv_text = Path(args.csv).read_text(encoding="utf-8")

    self.assertEqual(build_packet.call_count, 2)
    self.assertEqual([row["failure_reason"] for row in rows], ["validator_failure", "alarm_failure"])
    self.assertTrue(all(row["evidence_status"] == "loaded" for row in rows))
    self.assertTrue(all(row.get("evidence_path") for row in rows))
    self.assertIn("evidence_summary", csv_text)

  def test_taxonomy_recent_hil_default_does_not_load_evidence(self) -> None:
    with patch("sys.argv", ["phoenix_inspector.py", "taxonomy", "recent-hil", "--limit", "1000", "--max-matches", "3", "--load-evidence"]):
      parsed = cli.parse_args()
    self.assertEqual(parsed.limit, 1000)
    self.assertEqual(parsed.max_matches, 3)
    self.assertTrue(parsed.load_evidence)

    candidate = {"gha_url": "https://github.com/ZiplineTeam/FlightSystems/actions/runs/1/job/101", "run_id": "1", "job_id": "101", "job_conclusion": "failure"}
    recent = EvidenceReport(title="Recent HIL Sources", extra={"legacy_packet": {"candidates": [candidate]}})
    args = type("Args", (), {"report": None, "preset": None, "passing": False, "limit": 1000, "max_matches": 1, "load_evidence": False, "csv": None, "out_dir": None})()

    with patch("phoenix_inspector.taxonomy.recent_hil_report", return_value=recent), patch("phoenix_inspector.taxonomy.build_summary_packet") as build_packet:
      report = taxonomy_recent_hil(args)

    build_packet.assert_not_called()
    row = report.extra["rows"][0]
    self.assertEqual(row["failure_reason"], "inconclusive")
    self.assertEqual(row["evidence_status"], "not_loaded")

  def test_empty_spec_blocks_instead_of_claiming_success(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      source = root / "logs"
      source.mkdir()
      (source / "phoenix.log").write_text("ok", encoding="utf-8")
      spec_path = root / "question.yaml"
      spec_path.write_text(json.dumps({"name": "q", "extract": [], "proves": ["p"], "does_not_prove": ["d"]}), encoding="utf-8")

      inspected = inspect_with_spec(str(source), str(spec_path))
      validated = validate_spec_report(str(spec_path), [str(source)])
      scaffold = init_spec("from-last", str(root / "from-last.yaml"), from_last_run=False)

    self.assertEqual(inspected.status, "blocked")
    self.assertEqual(validated.status, "blocked")
    self.assertEqual(scaffold.status, "ok")

  def test_spec_executes_extract_and_init_reuses_last_run(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      zml = root / "case.zml"
      zml.write_text('{"topic":"/nav","timestamp":1,"fields":{"x":1}}\n', encoding="utf-8")
      spec_path = root / "question.json"
      spec_path.write_text(json.dumps({"name": "q", "extract": [{"topic": "/nav", "fields": ["x"], "backend": "local-text"}], "proves": ["p"], "does_not_prove": ["d"]}), encoding="utf-8")

      inspected = inspect_with_spec(str(zml), str(spec_path))
      remember_last_run(inspected)
      initialized = init_spec("from-last", str(root / "from-last.yaml"), from_last_run=True)

    self.assertEqual(inspected.status, "ok")
    self.assertEqual(len(inspected.signal_results), 1)
    self.assertEqual(initialized.extra["spec"]["extract"][0]["topic"], "/nav")

  def test_inspect_without_spec_is_inventory_oriented(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "case.zml"
      path.write_text('{"topic":"/nav","timestamp":1,"fields":{"clock_bias":1}}\n', encoding="utf-8")
      args = type("Args", (), {"source": str(path), "spec": None, "backend": "local-text", "systems_root": "/no-systems"})()

      report = cli.command_inspect(args)

    self.assertEqual(report.status, "ok")
    self.assertFalse(report.check_results)
    self.assertTrue(any(" fields " in command for command in report.next_commands))
    self.assertIn("inventory-oriented", report.summary)

  def test_compare_last_run_init_persists_rerunnable_sources(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      fail = root / "fail.zml"
      passing = root / "pass.zml"
      fail.write_text('{"topic":"/nav","timestamp":1,"fields":{"x":1}}\n', encoding="utf-8")
      passing.write_text('{"topic":"/nav","timestamp":1,"fields":{"x":2}}\n', encoding="utf-8")
      compare_args = type("Args", (), {"fail": str(fail), "pass_source": str(passing), "topic": "/nav", "field": ["x"], "preset": None, "spec": None, "start": "0", "end": "2", "center": None, "duration": None, "backend": "local-text", "systems_root": "/no-systems", "time_tolerance": 0.25, "numeric_tolerance": 0.5, "csv": None, "format": "json"})()
      compare = compare_report(compare_args)
      remember_last_run(compare)

      initialized = init_spec("compare-last", str(root / "compare-last.json"), from_last_run=True)
      rerun = inspect_with_spec(str(fail), str(root / "compare-last.json"))

    self.assertEqual(initialized.extra["spec"]["compare"][0]["fail"], str(fail))
    self.assertEqual(initialized.extra["spec"]["compare"][0]["pass"], str(passing))
    self.assertEqual(initialized.extra["spec"]["extract"], [])
    self.assertEqual(initialized.extra["spec"]["compare"][0]["backend"], "local-text")
    self.assertEqual(initialized.extra["spec"]["compare"][0]["window"], {"start": 0.0, "end": 2.0})
    self.assertEqual(initialized.extra["spec"]["compare"][0]["time_tolerance"], 0.25)
    self.assertEqual(initialized.extra["spec"]["compare"][0]["numeric_tolerance"], 0.5)
    self.assertEqual(rerun.status, "ok")

  def test_spec_init_blocks_non_rerunnable_last_run(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      remember_last_run(EvidenceReport(title="Inventory Only", status="ok"))

      initialized = init_spec("empty-last", str(root / "empty-last.json"), from_last_run=True)

    self.assertEqual(initialized.status, "blocked")
    self.assertEqual(initialized.blockers[0].code, "last_run_has_no_executable_operations")


if __name__ == "__main__":
  unittest.main()
