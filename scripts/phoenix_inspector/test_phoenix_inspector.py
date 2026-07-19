from __future__ import annotations

import csv
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phoenix_inspector.hil import packet_report
from phoenix_inspector.inventory import build_inventory
from phoenix_inspector.models import EvidenceReport, ProvenanceRef, RunSource
from phoenix_inspector.reports import render_markdown
from phoenix_inspector.sources import detect_source_type, resolve_source
from phoenix_inspector.zml import BACKEND_CHOICES, AutoBackend, SafeZmlConvBackend, backend_adapter, compare_report, extract_report, fields_report, summary_report, topics_report
from zml_audit.backends import BackendResult
from zml_audit.models import Blocker, TimeWindow

CLI_SPEC = importlib.util.spec_from_file_location("phoenix_inspector_cli", Path(__file__).parents[1] / "phoenix_inspector.py")
cli = importlib.util.module_from_spec(CLI_SPEC)
assert CLI_SPEC.loader is not None
CLI_SPEC.loader.exec_module(cli)


class PhoenixInspectorTests(unittest.TestCase):
  def assert_parse_error(self, argv: list[str]) -> str:
    with patch("sys.argv", ["phoenix_inspector.py", *argv]), patch("sys.stderr", new_callable=io.StringIO) as stderr:
      with self.assertRaises(SystemExit) as raised:
        cli.parse_args()

    self.assertEqual(raised.exception.code, 2)
    output = stderr.getvalue()
    self.assertIn("error:", output)
    return output

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
      local_json = root / "notes.json"
      local_json.write_text('{"note":"searchable text fixture"}', encoding="utf-8")
      archive = root / "hil-run.zip"
      archive.write_bytes(b"PK")

      self.assertEqual(detect_source_type("https://github.com/ZiplineTeam/FlightSystems/actions/runs/123/job/456"), "gha_url")
      self.assertEqual(detect_source_type("s3://bucket/prefix/"), "s3_root")
      self.assertEqual(detect_source_type(str(root)), "local_log_dir")
      self.assertEqual(detect_source_type(str(zml)), "zml_file")
      self.assertEqual(detect_source_type(str(local_json)), "local_text_file")
      self.assertEqual(detect_source_type(str(packet)), "unsupported_packet_json")
      self.assertEqual(detect_source_type(str(archive)), "unsupported_archive")
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
      markdown = render_markdown(EvidenceReport(title="Phoenix Source Inventory", sources=[inventory.source], inventories=[inventory], summary="inventory"))

    self.assertIn("test_record", inventory.key_artifacts)
    self.assertIn("zml_zst", inventory.key_artifacts)
    self.assertEqual(len(inventory.generated_outputs), 1)
    self.assertIn("bounded artifact list (first 20 per group)", markdown)
    self.assertIn("- `zml_zst` (1)", markdown)
    self.assertIn("- `compute.zml.zst`", markdown)
    self.assertIn("- `phoenix_log` (1)", markdown)
    self.assertIn("- `phoenix.log`", markdown)
    self.assertIn("- generated outputs (1):", markdown)
    self.assertIn("- `reports/phoenix_inspector.json`", markdown)
    self.assertNotIn(f"`{root / 'compute.zml.zst'}`", markdown)
    self.assertNotIn("## Signal and Check Findings", markdown)
    self.assertNotIn("## Timebase and Alignment", markdown)

  def test_inventory_markdown_bounds_artifact_groups(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      for index in range(22):
        (root / f"run_{index:02}.zml.zst").write_text("", encoding="utf-8")

      inventory = build_inventory(resolve_source(str(root), "inventory"))
      markdown = render_markdown(EvidenceReport(title="Phoenix Source Inventory", sources=[inventory.source], inventories=[inventory], summary="inventory"))

    self.assertIn("- `zml_zst` (22)", markdown)
    self.assertIn("- `run_00.zml.zst`", markdown)
    self.assertIn("- `run_19.zml.zst`", markdown)
    self.assertNotIn("- `run_20.zml.zst`", markdown)
    self.assertIn("- ... 2 more", markdown)

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

  def test_hil_empty_match_statuses_are_blocked_not_ok(self) -> None:
    for legacy_status in ("no_matches", "no_hil_jobs"):
      with self.subTest(legacy_status=legacy_status):
        report = packet_report("Recent HIL Sources", {"status": legacy_status, "source": {"input": "filters"}}, [])

        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.blockers[0].code, legacy_status)
        self.assertEqual(report.blockers[0].category, "missing_artifact")


  def test_remote_gha_inventory_markdown_surfaces_packet_evidence_and_followups(self) -> None:
    gha_url = "https://github.com/ZiplineTeam/FlightSystems/actions/runs/25931994941"
    job_url = f"{gha_url}/job/987654321"
    s3_root = "s3://platform2-testing-logs/hil/run-25931994941/"
    packet = {
      "status": "ok",
      "source": {"input": gha_url, "kind": "github_run", "repo": "ZiplineTeam/FlightSystems", "run_id": "25931994941"},
      "github": {"run": {"run_id": "25931994941", "title": "P2 Zip System HIL Build & Test", "workflow": "p2-zip-system-hil-build.yml", "status": "completed", "conclusion": "failure", "url": gha_url}},
      "candidates": [{"job_name": "HIL zip_autokiosk", "run_id": "25931994941", "job_id": "987654321", "job_conclusion": "failure", "job_url": job_url}],
      "jobs": [{
        "candidate": {"job_name": "HIL zip_autokiosk", "run_id": "25931994941", "job_id": "987654321", "job_conclusion": "failure", "job_url": job_url},
        "github": {"job": {"name": "HIL zip_autokiosk", "status": "completed", "conclusion": "failure", "runner_name": "hil-runner-1", "started_at": "2026-06-01T00:00:00Z", "completed_at": "2026-06-01T00:10:00Z", "url": job_url}},
        "s3": {
          "roots": [s3_root],
          "s3_links": [f"{s3_root}phoenix_logs/phoenix.log"],
          "baraza_links": ["https://baraza.example/missions/P2M_1"],
          "inventories": [{
            "s3_uri": s3_root,
            "count": 42,
            "total_size": 123456,
            "truncated": False,
            "key_artifact_hints": [
              {"category": "zml", "type": "compressed ZML", "uri": f"{s3_root}run.zml.zst", "size": 111, "note": "Validator and journal signal streams."},
              {"category": "phoenix_log", "type": "phoenix.log", "uri": f"{s3_root}phoenix_logs/phoenix.log", "size": 222},
            ],
            "test_record_artifacts": [{"uri": f"{s3_root}test_record.json", "type": "test_record.json", "size": 333}],
            "baraza": {"links": ["https://baraza.example/missions/P2M_1"], "mission_ids": ["P2M_1"]},
          }],
          "test_record_uris": [f"{s3_root}test_record.json"],
        },
        "test_records": [{"s3_uri": f"{s3_root}test_record.json", "test_name": "zip_autokiosk", "result": "failed", "query_matches": [{"field": "test_info.name"}], "baraza_urls": [{"url": "https://baraza.example/missions/P2M_1"}], "mission_info_identifiers": [{"kind": "mission", "value": "P2M_1"}, {"kind": "flight", "value": "FLT_1"}]}],
        "log_summary": {
          "validator_failures": [{"line": 12, "text": "FAIL_VALIDATORS pose check"}],
          "alarm_error_lines": [{"line": 30, "text": "ALARM geofence"}],
          "artifact_hint_lines": [{"line": 45, "text": s3_root}],
          "failed_scenarios_or_tests": ["zip_autokiosk"],
        },
      }],
      "next_steps": ["Open validator output locally after fetching artifacts."],
    }

    args = type("Args", (), {"command": "inventory", "source": gha_url, "backend": "auto", "systems_root": "/no-systems", "format": "markdown", "out_dir": None})()
    with patch("phoenix_inspector.hil.build_summary_packet", return_value=packet):
      report = cli.dispatch(args)
    markdown = render_markdown(report)

    self.assertEqual(report.status, "ok")
    self.assertIn("## Remote Evidence Inventory", markdown)
    self.assertIn("25931994941", markdown)
    self.assertIn("HIL zip_autokiosk", markdown)
    self.assertIn(job_url, markdown)
    self.assertIn(s3_root, markdown)
    self.assertIn("run.zml.zst", markdown)
    self.assertIn("test_record.json", markdown)
    self.assertIn("https://baraza.example/missions/P2M_1", markdown)
    self.assertIn("P2M_1", markdown)
    self.assertIn("FLT_1", markdown)
    self.assertIn("Validator failures: 1", markdown)
    self.assertIn("FAIL_VALIDATORS pose check", markdown)
    self.assertIn("ALARM geofence", markdown)
    self.assertIn("## Proves / Does Not Prove", markdown)
    self.assertIn("## Output Paths", markdown)
    self.assertNotIn("## Evidence Table", markdown)
    self.assertNotIn("## Signal and Check Findings", markdown)
    self.assertNotIn("## Timebase and Alignment", markdown)
    self.assertNotIn("Run `phoenix_inspector inventory <source>` first", markdown)
    self.assertFalse(any(command == f'python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" inventory {gha_url}' for command in report.next_commands))
    self.assertTrue(any(command.endswith(f"inventory {s3_root}") for command in report.next_commands))
    self.assertTrue(any("search-logs /tmp/LOCAL_HIL_BUNDLE" in command for command in report.next_commands))
    self.assertTrue(any("Phoenix Inspector has no remote download command" in command for command in report.next_commands))

  def test_remote_gha_inventory_without_artifacts_suggests_discovery_and_local_bundle(self) -> None:
    gha_url = "https://github.com/ZiplineTeam/FlightSystems/actions/runs/25931994941"
    packet = {"status": "ok", "source": {"input": gha_url, "kind": "github_run", "run_id": "25931994941"}}
    args = type("Args", (), {"command": "inventory", "source": gha_url, "backend": "auto", "systems_root": "/no-systems", "format": "markdown", "out_dir": None})()

    with patch("phoenix_inspector.hil.build_summary_packet", return_value=packet):
      report = cli.dispatch(args)
    markdown = render_markdown(report)

    self.assertNotIn("Run `phoenix_inspector inventory <source>` first", markdown)
    self.assertIn("recent-hil --job-name HIL --conclusion failure --max-matches 5", markdown)
    self.assertIn("search-logs /tmp/LOCAL_HIL_BUNDLE", markdown)
    self.assertFalse(any(command == f'python3 "$HOME/dotfiles/scripts/phoenix_inspector.py" inventory {gha_url}' for command in report.next_commands))

  def test_packet_and_archive_sources_are_unsupported_inventory_sources(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      packet = root / "test_record.json"
      packet.write_text(json.dumps({"test_info": {"name": "zip", "result": "failed"}}), encoding="utf-8")
      archive = root / "hil-run.zip"
      archive.write_bytes(b"PK")

      packet_inventory = build_inventory(resolve_source(str(packet), "inventory"))
      archive_inventory = build_inventory(resolve_source(str(archive), "inventory"))

    self.assertEqual(packet_inventory.source.resolved_type, "unsupported_packet_json")
    self.assertEqual(packet_inventory.blockers[0].code, "unsupported_packet_json_source")
    self.assertEqual(packet_inventory.artifacts, [])
    self.assertEqual(archive_inventory.source.resolved_type, "unsupported_archive")
    self.assertEqual(archive_inventory.blockers[0].code, "unsupported_archive_source")
    self.assertEqual(archive_inventory.artifacts, [])

  def test_markdown_report_has_stable_sections(self) -> None:
    markdown = render_markdown(EvidenceReport(title="Sections", proves=["p"], does_not_prove=["d"]))

    for heading in ("Summary", "Source and Inventory", "Evidence Table", "Signal and Check Findings", "Timebase and Alignment", "Proves / Does Not Prove", "Blockers and Missing Evidence", "Output Paths", "Next Commands"):
      self.assertIn(f"## {heading}", markdown)

  def test_emit_no_out_dir_preserves_stdout_format(self) -> None:
    markdown_output = cli.emit(EvidenceReport(title="Stdout Markdown", summary="hello"), type("Args", (), {"format": "markdown", "out_dir": None})())
    json_output = cli.emit(EvidenceReport(title="Stdout JSON", summary="hello"), type("Args", (), {"format": "json", "out_dir": None})())

    self.assertTrue(markdown_output.startswith("# Stdout Markdown\n"))
    self.assertEqual(json.loads(json_output)["title"], "Stdout JSON")

  def test_emit_markdown_out_dir_prints_report_and_lists_written_file(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      source = root / "source"
      out_dir = root / "reports"
      source.mkdir()
      (source / "test_record.json").write_text('{"test_info":{"name":"fixture","result":"failed"}}\n', encoding="utf-8")

      with patch("sys.argv", ["phoenix_inspector.py", "inventory", str(source), "--format", "markdown", "--out-dir", str(out_dir)]):
        args = cli.parse_args()
      report = cli.dispatch(args)
      output = cli.emit(report, args)
      markdown_path = out_dir / "phoenix-source-inventory.md"

      self.assertTrue(markdown_path.is_file())
      self.assertTrue(output.startswith("# Phoenix Source Inventory\n"))
      self.assertIn("## Output Paths", output)
      self.assertIn(str(markdown_path), output)
      self.assertNotEqual(output, f"{markdown_path}\n")
      self.assertEqual(markdown_path.read_text(encoding="utf-8"), output)

  def test_emit_json_out_dir_prints_json_report_and_lists_written_file(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      out_dir = Path(temp_dir) / "reports"
      output = cli.emit(EvidenceReport(title="JSON Contract", summary="hello"), type("Args", (), {"format": "json", "out_dir": str(out_dir)})())
      json_path = out_dir / "json-contract.json"
      data = json.loads(output)

      self.assertTrue(json_path.is_file())
      self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), data)
      self.assertEqual(data["title"], "JSON Contract")
      self.assertIn(str(json_path), data["output_paths"])

  def test_local_text_zml_topics_extract_and_compare(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      fail = root / "fail.zml"
      passing = root / "pass.zml"
      fail.write_text('{"topic":"/nav","timestamp":1,"fields":{"pose":{"x":1},"arr":[{"v":2}]}}\n{"topic":"/nav","timestamp":2,"fields":{"pose":{"x":5},"arr":[{"v":3}]}}\n', encoding="utf-8")
      passing.write_text('{"topic":"/nav","timestamp":1,"fields":{"pose":{"x":1},"arr":[{"v":2}]}}\n{"topic":"/nav","timestamp":2,"fields":{"pose":{"x":3},"arr":[{"v":3}]}}\n', encoding="utf-8")
      csv_path = root / "extract.csv"

      topics = topics_report(str(fail), "/nav", "local-text", "/no-systems", "json")
      extract_args = type("Args", (), {"source": str(fail), "topic": "/nav", "field": ["pose.x", "arr[*].v"], "start": None, "end": None, "center": None, "duration": None, "backend": "local-text", "systems_root": "/no-systems", "csv": str(csv_path), "format": "json"})()
      extracted = extract_report(extract_args)
      compare_args = type("Args", (), {"fail": str(fail), "pass_source": str(passing), "topic": "/nav", "field": ["pose.x"], "preset": None, "start": None, "end": None, "center": None, "duration": None, "backend": "local-text", "systems_root": "/no-systems", "time_tolerance": 0.0, "numeric_tolerance": 0.0, "csv": None, "format": "json"})()
      compared = compare_report(compare_args)

      self.assertEqual(topics.status, "ok")
      self.assertEqual(extracted.status, "ok")
      self.assertTrue(csv_path.is_file())
      self.assertEqual(compared.status, "ok")
      self.assertEqual(compared.signal_results[0].backend, "local-text")
      self.assertIn("first_divergences", compared.extra["legacy_packet"]["comparison"])

  def test_extract_all_fields_preserves_local_text_fields_in_csv(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      source = root / "run.zml"
      csv_path = root / "all-fields.csv"
      source.write_text('{"topic":"/nav","timestamp":1,"fields":{"pose":{"x":1},"phase":"ARMED"}}\n{"topic":"/nav","timestamp":2,"fields":{"pose":{"x":2},"phase":"BOUND"}}\n', encoding="utf-8")
      args = type("Args", (), {"source": str(source), "topic": "/nav", "field": None, "all_fields": True, "start": None, "end": None, "center": None, "duration": None, "backend": "local-text", "systems_root": "/no-systems", "csv": str(csv_path), "format": "json"})()

      report = extract_report(args)
      with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    self.assertEqual(report.status, "ok")
    self.assertEqual({row["field"] for row in rows}, {"phase", "pose"})
    self.assertTrue(any(row["value"] == "BOUND" for row in rows))

  def test_summary_metrics_cover_transitions_minmax_and_delta(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      csv_path = Path(temp_dir) / "extract.csv"
      with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "topic", "timestamp", "field", "value"])
        writer.writeheader()
        writer.writerows([
          {"path": "run.zml", "topic": "/nav", "timestamp": "1", "field": "phase", "value": "ARMED"},
          {"path": "run.zml", "topic": "/nav", "timestamp": "2", "field": "phase", "value": "ARMED"},
          {"path": "run.zml", "topic": "/nav", "timestamp": "3", "field": "phase", "value": "BOUND"},
          {"path": "run.zml", "topic": "/nav", "timestamp": "1", "field": "pose.x", "value": "1"},
          {"path": "run.zml", "topic": "/nav", "timestamp": "2", "field": "pose.x", "value": "4"},
          {"path": "run.zml", "topic": "/nav", "timestamp": "3", "field": "pose.x", "value": "7"},
        ])
      args = type("Args", (), {"csv": str(csv_path), "metric": ["transitions", "minmax", "delta"], "field": None})()

      report = summary_report(args)
      rows = {(row["field"], row["metric"]): row for row in report.extra["summary_metrics"]["rows"]}
      markdown = render_markdown(report)

    self.assertEqual(report.status, "ok")
    self.assertEqual(rows[("phase", "transitions")]["transition_count"], 1)
    self.assertEqual(rows[("pose.x", "transitions")]["transition_count"], 2)
    self.assertEqual(rows[("pose.x", "minmax")]["min"], 1.0)
    self.assertEqual(rows[("pose.x", "minmax")]["max"], 7.0)
    self.assertEqual(rows[("pose.x", "delta")]["delta"], 6.0)
    self.assertIn("## Summary Metrics", markdown)

  def test_extract_report_uses_direct_known_extract_for_exact_topic_field(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml.zst"
      path.write_text("", encoding="utf-8")
      args = type("Args", (), {"source": str(path), "topic": "/nav", "field": ["x"], "start": None, "end": None, "center": None, "duration": None, "backend": "zml-cli", "systems_root": "/no-systems", "csv": None, "format": "json"})()

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

  def test_cli_inventory_missing_source_prints_full_help(self) -> None:
    output = self.assert_parse_error(["inventory"])

    self.assertIn("source forms:", output)
    self.assertIn("Explicit source path/URL", output)
    self.assertIn("examples:", output)
    self.assertIn("inventory /tmp/hil-run", output)

  def test_cli_extract_missing_required_args_prints_full_help(self) -> None:
    output = self.assert_parse_error(["extract"])

    self.assertIn("--all-fields", output)
    self.assertIn("examples:", output)
    self.assertIn("extract /tmp/run.zml.zst", output)

  def test_cli_summary_missing_csv_prints_full_help(self) -> None:
    output = self.assert_parse_error(["summary"])

    self.assertIn("Summarize CSVs written by extract --csv", output)
    self.assertIn("summary /tmp/pi/nav.csv --metric transitions", output)
    self.assertIn("--metric {transitions,minmax,delta}", output)

  def test_cli_parser_accepts_fuzzy_topics_args(self) -> None:
    with patch("sys.argv", ["phoenix_inspector.py", "topics", "run.zml", "--fuzzy", "controller", "--limit", "5", "--format", "both", "--systems-root", "/custom/Systems"]):
      args = cli.parse_args()

    self.assertEqual(args.fuzzy, "controller")
    self.assertEqual(args.limit, 5)
    self.assertEqual(args.format, "both")
    self.assertEqual(args.systems_root, "/custom/Systems")

  def test_cli_parser_accepts_extract_all_fields_without_field(self) -> None:
    with patch("sys.argv", ["phoenix_inspector.py", "extract", "run.zml", "--topic", "/nav", "--all-fields", "--csv", "out.csv"]):
      args = cli.parse_args()

    self.assertEqual(args.command, "extract")
    self.assertEqual(args.topic, "/nav")
    self.assertTrue(args.all_fields)
    self.assertIsNone(args.field)
    self.assertEqual(args.csv, "out.csv")

  def test_cli_parser_accepts_summary_metrics_args(self) -> None:
    with patch("sys.argv", ["phoenix_inspector.py", "summary", "extract.csv", "--metric", "transitions", "--metric", "delta", "--field", "pose.x"]):
      args = cli.parse_args()

    self.assertEqual(args.command, "summary")
    self.assertEqual(args.csv, "extract.csv")
    self.assertEqual(args.metric, ["transitions", "delta"])
    self.assertEqual(args.field, ["pose.x"])

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

      json_path = out_dir / "zml-field-discovery.json"
      markdown_path = out_dir / "zml-field-discovery.md"

      self.assertEqual(args.format, "both")
      self.assertTrue(json_path.is_file())
      self.assertTrue(markdown_path.is_file())
      json_data = json.loads(json_path.read_text(encoding="utf-8"))
      self.assertTrue(output.startswith("# ZML Field Discovery\n"))
      self.assertIn("## Output Paths", output)
      self.assertIn(str(json_path), output)
      self.assertIn(str(markdown_path), output)
      self.assertNotEqual(output, f"{json_path}\n{markdown_path}\n")
      self.assertEqual(markdown_path.read_text(encoding="utf-8"), output)
      self.assertIn(str(json_path), json_data["output_paths"])
      self.assertIn(str(markdown_path), json_data["output_paths"])

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

  def test_cli_help_presents_lean_public_surface(self) -> None:
    with patch("sys.argv", ["phoenix_inspector.py", "--help"]), patch("sys.stdout", new_callable=io.StringIO) as stdout:
      with self.assertRaises(SystemExit) as raised:
        cli.parse_args()
    root_help = stdout.getvalue()

    self.assertEqual(raised.exception.code, 0)
    for command in ("inventory", "search-logs", "validators", "journal", "topics", "fields", "find-field", "extract", "summary", "compare", "recent-hil"):
      self.assertIn(command, root_help)
    for removed in ("inspect", "spec", "taxonomy", "sync-check"):
      self.assertNotIn(f"  {removed}", root_help)
      self.assertNotIn(f",{removed}", root_help)
      self.assertNotIn(f"{removed},", root_help)

  def test_cli_removed_commands_and_options_are_rejected(self) -> None:
    for argv in (["inspect", "run.zml"], ["spec", "init"], ["taxonomy", "recent-hil"], ["sync-check"]):
      with self.subTest(argv=argv):
        self.assert_parse_error(argv)

    for argv in (["extract", "run.zml", "--topic", "/nav", "--field", "x", "--plot", "plot.png"], ["extract", "run.zml", "--topic", "/nav", "--field", "x", "--plot-dir", "plots"], ["compare", "--fail", "fail.zml", "--pass", "pass.zml", "--spec", "question.yaml"], ["inventory", "run.zml", "--preset", "zip_autokiosk"], ["inventory", "run.zml", "--passing"], ["inventory", "run.zml", "--max-inventory-items", "1"], ["inventory", "run.zml", "--max-test-records", "1"]):
      with self.subTest(argv=argv):
        self.assert_parse_error(argv)

  def test_inventory_extract_and_compare_help_omit_removed_options(self) -> None:
    for command, removed in {
      "inventory": ("--preset", "--passing", "--max-inventory-items", "--max-test-records", "--backend", "--systems-root"),
      "extract": ("--plot", "--plot-dir"),
      "compare": ("--spec",),
    }.items():
      with self.subTest(command=command), patch("sys.argv", ["phoenix_inspector.py", command, "--help"]), patch("sys.stdout", new_callable=io.StringIO) as stdout:
        with self.assertRaises(SystemExit) as raised:
          cli.parse_args()
        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        for option in removed:
          self.assertNotIn(option, help_text)

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

  def test_compare_csv_and_empty_selection_blocker_are_structured(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      fail = root / "fail.zml"
      passing = root / "pass.zml"
      csv_path = root / "compare.csv"
      fail.write_text('{"topic":"/nav","timestamp":1,"fields":{"x":1}}\n', encoding="utf-8")
      passing.write_text('{"topic":"/nav","timestamp":1,"fields":{"x":2}}\n', encoding="utf-8")
      compare_args = type("Args", (), {"fail": str(fail), "pass_source": str(passing), "topic": "/nav", "field": ["x"], "preset": None, "start": None, "end": None, "center": None, "duration": None, "backend": "local-text", "systems_root": "/no-systems", "time_tolerance": 0.0, "numeric_tolerance": 0.0, "csv": str(csv_path), "format": "json"})()
      empty_args = type("Args", (), {"fail": str(fail), "pass_source": str(passing), "topic": None, "field": None, "preset": None, "start": None, "end": None, "center": None, "duration": None, "backend": "local-text", "systems_root": "/no-systems", "time_tolerance": 0.0, "numeric_tolerance": 0.0, "csv": None, "format": "json"})()

      compared = compare_report(compare_args)
      blocked = compare_report(empty_args)

      self.assertEqual(compared.status, "ok")
      self.assertTrue(csv_path.is_file())
      self.assertEqual(blocked.status, "blocked")
      self.assertEqual(blocked.blockers[0].code, "compare_has_no_signal_selection")

  def test_compare_preset_uses_preset_recipe(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      fail = root / "fail.zml"
      passing = root / "pass.zml"
      fail.write_text('{"topic":"nav.state+","timestamp":1,"fields":{"clock_bias":10}}\n', encoding="utf-8")
      passing.write_text('{"topic":"nav.state+","timestamp":1,"fields":{"clock_bias":2}}\n', encoding="utf-8")
      args = type("Args", (), {"fail": str(fail), "pass_source": str(passing), "topic": None, "field": None, "preset": "gnss-timing", "start": None, "end": None, "center": None, "duration": None, "backend": "local-text", "systems_root": "/no-systems", "time_tolerance": 0.0, "numeric_tolerance": 0.0, "csv": None, "format": "json"})()

      report = compare_report(args)

    topic_names = [item["name"] for item in report.extra["legacy_packet"]["query"]["topics"]]
    self.assertEqual(report.status, "ok")
    self.assertIn("nav.state+", topic_names)

if __name__ == "__main__":
  unittest.main()
