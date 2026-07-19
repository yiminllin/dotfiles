from __future__ import annotations

import json
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zml_audit.backends import BACKEND_CHOICES, AutoBackend, BackendResult, ZmlCliBackend, ZmlConvBackend, build_zml_conv_command, select_backend
from zml_audit.compare import compare_runs
from zml_audit.extract import filter_samples, parse_samples, parse_time_arg
from zml_audit.fields import flatten_field_paths
from zml_audit.models import Blocker, TimeWindow, TopicSpec
from zml_audit.presets import expand_specs
from zml_audit.render import render_csv, render_json, render_markdown
from zml_audit.sources import resolve_source
from zml_audit.stats import summarize_topic
from zml_audit.topics import fuzzy_topic_matches
from zml_audit.zml_cli import ZmlCli, ZmlResult
from zml_signal_audit import build_audit_packet, build_compare_packet, build_fields_packet, build_topics_packet, build_window, parse_args, rank_direct_extract_candidates


class FakeZml:
  def __init__(self, stdout: str) -> None:
    self.stdout = stdout

  def list_topics(self, path: str) -> ZmlResult:
    return ZmlResult(stdout="/test1\n")

  def print_topic(self, path: str, topic: str) -> ZmlResult:
    return ZmlResult(stdout=self.stdout)


class FakeTopicsZml:
  def __init__(self, topics: str) -> None:
    self.topics = topics

  def list_topics(self, path: str) -> ZmlResult:
    return ZmlResult(stdout=self.topics)


class FakeFieldsZml:
  def __init__(self, reads: dict[str, str]) -> None:
    self.reads = reads
    self.read_calls: list[str] = []

  def list_topics(self, path: str) -> ZmlResult:
    return ZmlResult(stdout="\n".join(self.reads) + "\n")

  def read_topic(self, path: str, topic: str, window: TimeWindow) -> ZmlResult:
    self.read_calls.append(topic)
    return ZmlResult(stdout=self.reads.get(topic, ""), metadata={"selected": "fake", "operation": "read topic"})


class FakeMetadataZml:
  def __init__(self, metadata: str, reads: dict[str, str] | None = None, topics: list[str] | None = None) -> None:
    self.metadata = metadata
    self.reads = reads or {}
    self.topics = topics
    self.metadata_calls = 0
    self.read_calls: list[str] = []

  def list_topics(self, path: str) -> ZmlResult:
    if self.topics is None:
      return ZmlResult(blocker=Blocker(tool="fake", message="topic listing unavailable"), metadata={"selected": "fake", "unsupported_operation": True})
    return ZmlResult(stdout="\n".join(self.topics) + "\n", backend="fake", metadata={"selected": "fake", "operation": "list topics"})

  def field_metadata(self, path: str) -> ZmlResult:
    self.metadata_calls += 1
    return ZmlResult(stdout=self.metadata, backend="fake-metadata", metadata={"selected": "fake-metadata", "source": "metadata"})

  def read_topic(self, path: str, topic: str, window: TimeWindow) -> ZmlResult:
    self.read_calls.append(topic)
    return ZmlResult(stdout=self.reads.get(topic, ""), backend="fake", metadata={"selected": "fake", "operation": "read topic"})


class FakeSchemaDiscoveryZml:
  def __init__(self, topics_by_path: dict[str, list[str]], reads: dict[tuple[str, str], str]) -> None:
    self.topics_by_path = topics_by_path
    self.reads = reads

  def field_metadata(self, path: str) -> BackendResult:
    return BackendResult(stdout="", backend="fake", metadata={"selected": "fake", "source": "metadata"})

  def list_topics(self, path: str) -> BackendResult:
    return BackendResult(stdout="\n".join(self.topics_by_path.get(path, [])) + "\n", backend="fake", metadata={"selected": "fake", "operation": "list topics"})

  def read_topic(self, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...] = ()) -> BackendResult:
    return BackendResult(stdout=self.reads.get((path, topic), ""), backend="fake", metadata={"selected": "fake", "operation": "read topic"})


class ZmlAuditPureTests(unittest.TestCase):
  def test_source_resolution_enumerates_only_provided_directory(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      (root / "a.zml").write_text("", encoding="utf-8")
      nested = root / "nested"
      nested.mkdir()
      (nested / "b.zml.zst").write_text("", encoding="utf-8")

      resolution = resolve_source(temp_dir)

    self.assertEqual(resolution.kind, "directory")
    self.assertEqual(len(resolution.candidates), 2)

  def test_remote_source_is_structured_blocker(self) -> None:
    resolution = resolve_source("s3://bucket/path/zml_log_0.zml.zst")

    self.assertEqual(resolution.kind, "remote")
    self.assertIn("not downloaded", resolution.blockers[0].message)

  def test_source_resolution_refuses_filesystem_root(self) -> None:
    resolution = resolve_source("/")

    self.assertEqual(resolution.kind, "refused_directory")
    self.assertIn("broad directory", resolution.blockers[0].message)

  def test_source_resolution_refuses_broad_user_and_system_roots(self) -> None:
    self.assertEqual(resolve_source("/Systems").kind, "refused_directory")
    self.assertEqual(resolve_source(str(Path.home())).kind, "refused_directory")

  def test_source_resolution_bounds_directory_traversal(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      for index in range(3):
        (root / f"{index}.zml").write_text("", encoding="utf-8")

      resolution = resolve_source(temp_dir, max_candidates=2)

    self.assertEqual(len(resolution.candidates), 2)
    self.assertTrue(resolution.blockers)

  def test_window_normalization_supports_center_duration(self) -> None:
    window = TimeWindow(center=100.0, duration=20.0).normalized()

    self.assertEqual(window.start, 90.0)
    self.assertEqual(window.end, 110.0)
    self.assertTrue(window.contains(100.0))
    self.assertFalse(window.contains(111.0))

  def test_build_window_rejects_center_without_duration(self) -> None:
    args = SimpleNamespace(start=None, end=None, center="10", duration=None)

    with self.assertRaises(ValueError):
      build_window(args)

  def test_preset_expands_to_auditable_topic_specs(self) -> None:
    specs = expand_specs(["/custom"], ["x"], "prod-nav")

    self.assertIn("nav.gnc_state", [spec.name for spec in specs])
    self.assertIn(TopicSpec("/custom", ("x",)), specs)

  def test_zml_conv_bazel_fallback_runs_from_systems_root(self) -> None:
    calls = []

    def runner(command, **kwargs):
      calls.append((command, kwargs))
      return SimpleNamespace(returncode=0, stdout='{"topic":"/nav","timestamp":1}\n', stderr="")

    with patch("zml_audit.backends.shutil.which", side_effect=lambda binary: "/usr/bin/bazel" if binary == "bazel" else None), patch("zml_audit.backends.Path.exists", return_value=True):
      result = ZmlConvBackend(runner=runner, systems_root="/custom/Systems").read_topic("run.zml", "/nav", TimeWindow())

    command, kwargs = calls[0]
    self.assertIsNone(result.blocker)
    self.assertEqual(command[:4], ["bazel", "run", "//tools/zml_conv:zml_conv", "--"])
    self.assertEqual(kwargs["cwd"], "/custom/Systems")
    self.assertEqual(result.metadata["systems_root"], "/custom/Systems")
    self.assertEqual(result.metadata["cwd"], "/custom/Systems")
    self.assertEqual(result.metadata["zml_conv_invocation"], "bazel")

  def test_auto_zml_conv_prefers_bazel_when_systems_root_exists(self) -> None:
    calls = []

    def runner(command, **kwargs):
      calls.append((command, kwargs))
      return SimpleNamespace(returncode=0, stdout='{"topic":"/nav","timestamp":1}\n', stderr="")

    with patch("zml_audit.backends.shutil.which", side_effect=lambda binary: f"/usr/bin/{binary}" if binary in {"bazel", "zml_conv"} else None), patch("zml_audit.backends.Path.exists", return_value=True):
      result = AutoBackend(factories=[lambda: ZmlConvBackend(runner=runner, systems_root="/Systems", prefer_bazel=True)]).read_topic("run.zml", "/nav", TimeWindow())

    self.assertIsNone(result.blocker)
    self.assertEqual(calls[0][0][:4], ["bazel", "run", "//tools/zml_conv:zml_conv", "--"])
    self.assertEqual(result.metadata["requested"], "auto")
    self.assertEqual(result.metadata["systems_root"], "/Systems")

  def test_custom_systems_root_is_passed_to_selected_backend_and_query(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      with patch("zml_signal_audit.select_backend", return_value=FakeZml("#0 @1.0 ~1.0 /test1 {'x': 1}\n")) as selected:
        packet = build_audit_packet(str(path), [TopicSpec("/test1", ("x",))], TimeWindow(), backend_name="zml-conv", systems_root="/custom/Systems")

    selected.assert_called_once_with("zml-conv", 60.0, "/custom/Systems")
    self.assertEqual(packet["query"]["backend"]["systems_root"], "/custom/Systems")

  def test_standalone_zml_cli_does_not_require_systems_root(self) -> None:
    calls = []

    def runner(command, **kwargs):
      calls.append((command, kwargs))
      return SimpleNamespace(returncode=0, stdout="/nav\n", stderr="")

    with patch("zml_audit.backends.shutil.which", return_value="/usr/bin/zml"):
      result = ZmlCliBackend(runner=runner).list_topics("run.zml")

    self.assertIsNone(result.blocker)
    self.assertIsNone(calls[0][1]["cwd"])
    self.assertNotIn("systems_root", result.metadata)

  def test_preset_aliases_expand_to_new_bundles(self) -> None:
    old_alias = expand_specs([], [], "truth-vs-nav")
    new_alias = expand_specs([], [], "prod-nav-truth-vs-nav")
    gnss = expand_specs([], [], "gnss-timing")

    self.assertEqual(old_alias, new_alias)
    self.assertIn(TopicSpec("nav.state+", ("clock_bias", "clock_bias_m", "clock_bias_s", "clock_drift", "clock_drift_mps", "clock_drift_sps")), gnss)

  def test_iso_time_arg_parses_to_epoch(self) -> None:
    self.assertEqual(parse_time_arg("1970-01-01T00:00:10Z"), 10.0)

  def test_json_lines_parser_extracts_requested_fields(self) -> None:
    samples = parse_samples(
      '\n'.join(
        [
          '{"topic":"/nav","timestamp":1,"x":2,"mode":"A"}',
          '{"topic":"/nav","timestamp":2,"x":4,"mode":"B"}',
        ]
      ),
      fields=("x",),
    )

    self.assertEqual([sample.fields for sample in samples], [{"x": 2}, {"x": 4}])

  def test_zml_conv_json_lines_use_monotonic_ns_and_expand_nested_arrays(self) -> None:
    samples = parse_samples(
      "\n".join(
        json.dumps(row)
        for row in [
          {"log_monotonic_ns": 400000000, "observations": [{"signals": [{"frequency": "GPS_L1", "pseudorange_m": 23576937.48}]}]},
          {"log_monotonic_ns": 500000000, "observations": [{"signals": [{"frequency": "GPS_L1", "pseudorange_m": 23576938.0}]}]},
        ]
      ),
      default_topic="/SIL.gnss.observation_epochs",
      fields=("observations[*].signals[*].pseudorange_m",),
    )

    self.assertEqual([sample.timestamp for sample in samples], [0.4, 0.5])
    self.assertEqual(samples[0].metadata, {"timestamp_source": "log_monotonic_ns", "timestamp_unit": "ns", "timebase": "log_monotonic"})
    self.assertEqual(samples[0].fields, {"observations[0].signals[0].pseudorange_m": 23576937.48})

  def test_zml_conv_json_lines_fall_back_to_gps_epoch_fraction(self) -> None:
    samples = parse_samples(
      json.dumps({"gps_epoch_time.seconds": 1383703200, "gps_epoch_time.fraction": 0.25, "value": 1}),
      default_topic="/gps",
      fields=("value",),
    )

    self.assertEqual(samples[0].timestamp, 1383703200.25)
    self.assertEqual(samples[0].metadata, {"timestamp_source": "gps_epoch_time", "timebase": "gps_epoch_time"})

  def test_parser_extracts_nested_requested_field_paths(self) -> None:
    samples = parse_samples('{"topic":"/nav","timestamp":1,"fields":{"pose":{"position":{"x":2}},"mode":"A"}}', fields=("pose.position.x",))

    self.assertEqual(samples[0].fields, {"pose.position.x": 2})

  def test_parser_resolves_literal_dotted_keys_inside_arrays(self) -> None:
    samples = parse_samples(
      json.dumps({"topic": "/gnss", "timestamp": 1, "observations": [{"satellite.svid": 3}, {"satellite": {"svid": 4}}]}),
      fields=("observations[*].satellite.svid",),
    )

    self.assertEqual(samples[0].fields, {"observations[0].satellite.svid": 3, "observations[1].satellite.svid": 4})

  def test_parser_expands_index_list_and_dict_wildcards(self) -> None:
    samples = parse_samples(
      '{"topic":"/gnss","timestamp":1,"fields":{"gnss_epoch":{"measurements":[{"pseudorange":10},{"pseudorange":20}]},"foo":{"bar":{"value":3},"baz":{"value":4}},"a":{"timestamp":5},"b":{"timestamp":6}}}',
      fields=("gnss_epoch.measurements[0].pseudorange", "gnss_epoch.measurements[*].pseudorange", "foo.*.value", "*.timestamp"),
    )

    self.assertEqual(
      samples[0].fields,
      {
        "gnss_epoch.measurements[0].pseudorange": 10,
        "gnss_epoch.measurements[1].pseudorange": 20,
        "foo.bar.value": 3,
        "foo.baz.value": 4,
        "a.timestamp": 5,
        "b.timestamp": 6,
      },
    )

  def test_parser_marks_field_expansion_truncation(self) -> None:
    fields = {f"k{index:04d}": index for index in range(1001)}
    samples = parse_samples('{"topic":"/wide","timestamp":1,"fields":' + str(fields).replace("'", '"') + "}", fields=("*",))

    self.assertEqual(len(samples[0].fields), 1000)
    self.assertEqual(samples[0].metadata, {"field_expansion_truncated": True, "expanded_field_limit": 1000})

  def test_text_parser_supports_timestamp_and_key_values(self) -> None:
    samples = parse_samples("1.0 topic=/nav x=2.5 mode=A\n2.0 topic=/nav x=3.5 mode=A")

    self.assertEqual(samples[0].timestamp, 1.0)
    self.assertEqual(samples[1].fields["x"], 3.5)

  def test_zml_print_parser_uses_at_timestamp_topic_and_payload(self) -> None:
    samples = parse_samples("#0 @1.0 ~2.0 /test1 {'foo': 0, 'bar': 'baz'}\n#1 @2.0 3.0 /test2 {'foo': 1}")

    self.assertEqual(len(samples), 2)
    self.assertEqual(samples[0].timestamp, 1.0)
    self.assertEqual(samples[0].topic, "/test1")
    self.assertEqual(samples[0].fields, {"foo": 0, "bar": "baz"})
    self.assertEqual(samples[1].timestamp, 2.0)
    self.assertEqual(samples[1].topic, "/test2")
    self.assertEqual(samples[1].fields, {"foo": 1})

  def test_zml_print_parser_honors_field_filter(self) -> None:
    samples = parse_samples("#0 @1.0 ~2.0 /test1 {'foo': 0, 'bar': 1}", fields=("bar",))

    self.assertEqual(samples[0].fields, {"bar": 1})

  def test_stats_compute_rate_numeric_stats_and_transitions(self) -> None:
    spec = TopicSpec("/nav", ("x", "mode"))
    samples = parse_samples("1 topic=/nav x=1 mode=A\n2 topic=/nav x=3 mode=B\n3 topic=/nav x=5 mode=B")
    summary = summarize_topic(spec, samples)

    self.assertTrue(summary.present)
    self.assertEqual(summary.sample_count, 3)
    self.assertEqual(summary.approximate_rate_hz, 1.0)
    self.assertEqual(summary.fields["x"].mean, 3.0)
    self.assertEqual(summary.fields["mode"].transition_count, 1)
    self.assertEqual(summary.fields["mode"].transition_details, [{"timestamp": 2.0, "from_value": "A", "to_value": "B"}])

  def test_transition_detail_limit_is_applied(self) -> None:
    spec = TopicSpec("/nav", ("mode",))
    samples = parse_samples("1 topic=/nav mode=A\n2 topic=/nav mode=B\n3 topic=/nav mode=C")
    summary = summarize_topic(spec, samples, transition_limit=1)

    self.assertEqual(summary.fields["mode"].transition_details, [{"timestamp": 2.0, "from_value": "A", "to_value": "B"}])

  def test_filter_samples_applies_topic_and_window(self) -> None:
    spec = TopicSpec("/nav")
    samples = parse_samples("1 topic=/nav x=1\n2 topic=/other x=9\n3 topic=/nav x=3")

    filtered = filter_samples(samples, spec, TimeWindow(start=2.0, end=4.0))

    self.assertEqual([sample.timestamp for sample in filtered], [3.0])

  def test_compare_reports_topic_and_field_deltas(self) -> None:
    spec = TopicSpec("/nav", ("x",))
    fail_samples = parse_samples("1 topic=/nav x=1\n2 topic=/nav x=5")
    pass_samples = parse_samples("1 topic=/nav x=1\n2 topic=/nav x=3")
    fail_summary = summarize_topic(spec, fail_samples)
    pass_summary = summarize_topic(spec, pass_samples)

    comparison = compare_runs({"/nav": fail_summary}, {"/nav": pass_summary}, {"/nav": fail_samples}, {"/nav": pass_samples})

    self.assertEqual(comparison["topics"][0]["fields"][0]["mean_delta"], 1.0)
    self.assertEqual(comparison["first_divergences"][0]["field"], "x")

  def test_compare_tolerances_align_timestamps_and_numeric_values(self) -> None:
    spec = TopicSpec("/nav", ("x",))
    fail_samples = parse_samples("1.00 topic=/nav x=1.00")
    pass_samples = parse_samples("1.05 topic=/nav x=1.04")
    fail_summary = summarize_topic(spec, fail_samples)
    pass_summary = summarize_topic(spec, pass_samples)

    comparison = compare_runs(
      {"/nav": fail_summary},
      {"/nav": pass_summary},
      {"/nav": fail_samples},
      {"/nav": pass_samples},
      time_tolerance=0.1,
      numeric_tolerance=0.05,
    )

    self.assertEqual(comparison["timestamp_alignment"][0]["matched_sample_count"], 1)
    self.assertEqual(comparison["timestamp_alignment"][0]["unmatched_fail_sample_count"], 0)
    self.assertEqual(comparison["first_divergences"], [])

  def test_zero_numeric_tolerance_keeps_exact_equality_semantics(self) -> None:
    spec = TopicSpec("/nav", ("x",))
    fail_samples = parse_samples('{"topic":"/nav","timestamp":1,"x":"1"}')
    pass_samples = parse_samples('{"topic":"/nav","timestamp":1,"x":1}')

    comparison = compare_runs(
      {"/nav": summarize_topic(spec, fail_samples)},
      {"/nav": summarize_topic(spec, pass_samples)},
      {"/nav": fail_samples},
      {"/nav": pass_samples},
      numeric_tolerance=0,
    )

    self.assertEqual(comparison["first_divergences"][0]["field"], "x")
    self.assertEqual(comparison["first_divergences"][0]["fail_value"], "1")

  def test_first_divergence_requires_matching_timestamps(self) -> None:
    spec = TopicSpec("/nav", ("x",))
    fail_samples = parse_samples("1 topic=/nav x=1\n2 topic=/nav x=9")
    pass_samples = parse_samples("3 topic=/nav x=1\n4 topic=/nav x=2")
    fail_summary = summarize_topic(spec, fail_samples)
    pass_summary = summarize_topic(spec, pass_samples)

    comparison = compare_runs({"/nav": fail_summary}, {"/nav": pass_summary}, {"/nav": fail_samples}, {"/nav": pass_samples})

    self.assertEqual(comparison["first_divergences"][0]["reason"], "no_common_timestamps")
    self.assertNotIn("field", comparison["first_divergences"][0])

  def test_compare_blocks_directory_with_multiple_candidates(self) -> None:
    with tempfile.TemporaryDirectory() as fail_dir, tempfile.TemporaryDirectory() as pass_dir:
      fail_root = Path(fail_dir)
      pass_root = Path(pass_dir)
      (fail_root / "a.zml").write_text("", encoding="utf-8")
      (fail_root / "b.zml").write_text("", encoding="utf-8")
      (pass_root / "only.zml").write_text("", encoding="utf-8")

      packet = build_compare_packet(fail_dir, pass_dir, [TopicSpec("/nav")], TimeWindow())

    self.assertEqual(packet["status"], "blocked")
    self.assertIn("requires exactly one candidate", packet["blockers"][-1]["message"])
    self.assertEqual(packet["comparison"], {})

  def test_topics_packet_filters_with_contains_and_regex(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_topics_packet(str(path), ["nav"], [r"state\+$"], zml=FakeTopicsZml("/nav\n/imu/raw\n/compute_a.nav.state+\n"))

    self.assertEqual(packet["status"], "ok")
    self.assertEqual(packet["files"][0]["topics"], ["/compute_a.nav.state+"])

  def test_fuzzy_topic_matches_rank_substrings_tokens_and_approximate_names(self) -> None:
    topics = ["/compute_a.nav.gnc_state+", "/controller/main_state", "/imu/raw", "/control/controllr_status"]

    controller_matches = fuzzy_topic_matches(topics, "controller", limit=2)
    nav_matches = fuzzy_topic_matches(topics, "gnc state", limit=1)

    self.assertEqual(controller_matches[0].topic, "/controller/main_state")
    self.assertEqual(controller_matches[0].reason, "substring")
    self.assertIn("controllr", controller_matches[1].topic)
    self.assertEqual(nav_matches[0].topic, "/compute_a.nav.gnc_state+")
    self.assertEqual(nav_matches[0].reason, "token_overlap")

  def test_topics_packet_fuzzy_limits_matches_and_records_scores(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_topics_packet(str(path), [], [], zml=FakeTopicsZml("/controller/main_state\n/control/controllr_status\n/nav/state\n"), fuzzy="controller", limit=1)

    matches = packet["files"][0]["topic_matches"]
    self.assertEqual(packet["files"][0]["topics"], ["/controller/main_state"])
    self.assertEqual(matches[0]["topic"], "/controller/main_state")
    self.assertGreater(matches[0]["score"], 0.8)
    self.assertEqual(packet["query"]["fuzzy"], "controller")

  def test_flatten_field_paths_includes_nested_arrays_and_wildcards(self) -> None:
    fields, metadata = flatten_field_paths({"message": {"flight_phase_for_controller": "BOUND"}, "measurements": [{"pseudorange": 10}, {"pseudorange": 20}]})

    self.assertEqual(metadata, {})
    self.assertEqual(fields["message.flight_phase_for_controller"], "BOUND")
    self.assertEqual(fields["measurements[0].pseudorange"], 10)
    self.assertEqual(fields["measurements[*].pseudorange"], 10)
    self.assertEqual(fields["measurements[1].pseudorange"], 20)

  def test_field_discovery_ranks_field_match_over_topic_only_controller_match(self) -> None:
    zml = FakeFieldsZml(
      {
        "/compute_a.zip_executive.cloud_bound_status": '{"topic":"/compute_a.zip_executive.cloud_bound_status","timestamp":1,"fields":{"message":{"flight_phase_for_controller":"BOUND"}}}\n',
        "/controller/main_state": '{"topic":"/controller/main_state","timestamp":1,"fields":{"message":{"state":"READY"}}}\n',
      }
    )
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_fields_packet(str(path), fuzzy="controller", sample_top=25, zml=zml)

    matches = packet["files"][0]["field_matches"]
    self.assertEqual(packet["status"], "ok")
    self.assertEqual(matches[0]["topic"], "/compute_a.zip_executive.cloud_bound_status")
    self.assertEqual(matches[0]["field_path"], "message.flight_phase_for_controller")
    self.assertEqual(matches[0]["zml_path"], str(path))
    self.assertEqual(matches[0]["source"], "sample")
    self.assertTrue(all(match["field_path"] != "message.state" for match in matches))

  def test_field_discovery_uses_metadata_without_sampling_when_fields_are_indexed(self) -> None:
    metadata = json.dumps({"topics": [{"topic": "/controller/main_state", "fields": ["message.state"]}, {"topic": "/compute_a.zip_executive.cloud_bound_status", "fields": ["message.flight_phase_for_controller"]}]})
    zml = FakeMetadataZml(metadata)
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_fields_packet(str(path), fuzzy="flight_phase_for_controller", zml=zml)

    matches = packet["files"][0]["field_matches"]
    discovery = packet["files"][0]["field_discovery"]
    self.assertEqual(packet["status"], "ok")
    self.assertEqual(zml.metadata_calls, 1)
    self.assertEqual(zml.read_calls, [])
    self.assertEqual(matches[0]["field_path"], "message.flight_phase_for_controller")
    self.assertEqual(matches[0]["source"], "metadata")
    self.assertEqual(matches[0]["confidence"], "high")
    self.assertEqual(discovery["backend_source"], "metadata")

  def test_field_discovery_prefers_backend_metadata_over_static_schema_fallback(self) -> None:
    metadata = json.dumps({"topics": [{"topic": "/compute_a.backend.topic", "fields": ["backend_only_field"]}]})
    zml = FakeMetadataZml(metadata)
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "zip-0001" / "compute_a" / "compute_a.zml.zst"
      path.parent.mkdir(parents=True)
      path.write_text("", encoding="utf-8")

      packet = build_fields_packet(str(path), fuzzy="backend_only_field", zml=zml)
      schema_packet = build_fields_packet(str(path), fuzzy="flight_phase_for_controller", zml=zml, systems_root="/custom/Systems")

    matches = packet["files"][0]["field_matches"]
    schema_matches = schema_packet["files"][0]["field_matches"]
    self.assertEqual(zml.metadata_calls, 2)
    self.assertEqual(matches[0]["topic"], "/compute_a.backend.topic")
    self.assertEqual(matches[0]["field_path"], "backend_only_field")
    self.assertEqual(matches[0]["source"], "metadata")
    self.assertEqual(schema_matches[0]["topic"], "/compute_a.zip_executive.cloud_bound_status")
    self.assertEqual(schema_matches[0]["source"], "schema")

  def test_field_discovery_prefers_present_schema_topic_over_path_likely_non_present_topic(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      compute_a = root / "zip-0001" / "compute_a" / "compute_a.zml.zst"
      compute_b = root / "zip-0001" / "compute_b" / "compute_b.zml.zst"
      compute_a.parent.mkdir(parents=True)
      compute_b.parent.mkdir(parents=True)
      compute_a.write_text("", encoding="utf-8")
      compute_b.write_text("", encoding="utf-8")
      zml = FakeSchemaDiscoveryZml(
        {
          str(compute_a): ["/SIL.zip_executive.cloud_bound_status"],
          str(compute_b): ["/compute_a.zip_executive.cloud_bound_status"],
        },
        {},
      )

      packet = build_fields_packet(temp_dir, fuzzy="flight_phase_for_controller", zml=zml)

    matches = [match for file_result in packet["files"] for match in file_result.get("field_matches", [])]
    present_matches = [match for match in matches if match.get("topic_presence") == "present"]
    non_present_matches = [match for match in matches if match.get("topic_presence") == "not_present"]
    self.assertEqual(packet["status"], "ok")
    self.assertTrue(present_matches)
    self.assertTrue(non_present_matches)
    self.assertEqual(matches[0]["topic_presence"], "present")
    self.assertTrue(matches[0]["extractable"])
    self.assertLess(matches.index(present_matches[0]), matches.index(non_present_matches[0]))

  def test_field_discovery_top_present_schema_match_extracts_from_selected_file(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      compute_a = root / "zip-0001" / "compute_a" / "compute_a.zml.zst"
      compute_b = root / "zip-0001" / "compute_b" / "compute_b.zml.zst"
      compute_a.parent.mkdir(parents=True)
      compute_b.parent.mkdir(parents=True)
      compute_a.write_text("", encoding="utf-8")
      compute_b.write_text("", encoding="utf-8")
      topics_by_path = {
        str(compute_a): ["/SIL.zip_executive.cloud_bound_status"],
        str(compute_b): ["/compute_a.zip_executive.cloud_bound_status"],
      }
      reads = {
        (str(compute_a), "/SIL.zip_executive.cloud_bound_status"): '{"topic":"/SIL.zip_executive.cloud_bound_status","timestamp":1,"fields":{"flight_phase_for_controller":"BOUND"}}\n',
        (str(compute_b), "/compute_a.zip_executive.cloud_bound_status"): '{"topic":"/compute_a.zip_executive.cloud_bound_status","timestamp":1,"fields":{"flight_phase_for_controller":"BOUND"}}\n',
      }
      zml = FakeSchemaDiscoveryZml(topics_by_path, reads)

      fields_packet = build_fields_packet(temp_dir, fuzzy="flight_phase_for_controller", zml=zml)
      selected = next(match for file_result in fields_packet["files"] for match in file_result.get("field_matches", []) if match.get("topic_presence") == "present")
      extract_packet = build_audit_packet(selected["zml_path"], [TopicSpec(selected["topic"], (selected["field_path"],))], TimeWindow(), zml=zml, direct_known_extract=True)

    topic = extract_packet["files"][0]["topics"][0]
    self.assertTrue(selected["extractable"])
    self.assertEqual(extract_packet["status"], "ok")
    self.assertTrue(topic["present"])
    self.assertEqual(topic["sample_count"], 1)
    self.assertEqual(topic["fields"]["flight_phase_for_controller"]["first"], "BOUND")

  def test_schema_field_metadata_reports_systems_root(self) -> None:
    zml = FakeMetadataZml("")
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "zip-0001" / "compute_a" / "compute_a.zml.zst"
      path.parent.mkdir(parents=True)
      path.write_text("", encoding="utf-8")

      packet = build_fields_packet(str(path), fuzzy="flight_phase_for_controller", zml=zml, systems_root="/custom/Systems")

    metadata = packet["files"][0]["backend"]["list_topics"]
    self.assertEqual(metadata["selected"], "raw-schema")
    self.assertEqual(metadata["systems_root"], "/custom/Systems")
    self.assertIn("cwd", metadata)

  def test_field_discovery_does_not_cache_path_specific_metadata_failure(self) -> None:
    class PathMetadataBackend:
      name = "path-metadata"

      def __init__(self) -> None:
        self.metadata_calls: list[str] = []

      def field_metadata(self, path: str) -> BackendResult:
        self.metadata_calls.append(path)
        if path.endswith("a.zml"):
          return BackendResult(blocker=Blocker(tool=self.name, message="metadata command failed for this file"), backend=self.name, metadata={"selected": self.name, "operation": "field metadata"})
        return BackendResult(stdout=json.dumps({"topics": [{"topic": "/b", "fields": ["target_field"]}]}), backend=self.name, metadata={"selected": self.name, "source": "metadata"})

    backend = PathMetadataBackend()
    with tempfile.TemporaryDirectory() as temp_dir:
      first = Path(temp_dir) / "a.zml"
      second = Path(temp_dir) / "b.zml"
      first.write_text("", encoding="utf-8")
      second.write_text("", encoding="utf-8")

      packet = build_fields_packet(temp_dir, fuzzy="target_field", zml=AutoBackend(factories=[lambda: backend]))

    matches = [match for file_result in packet["files"] for match in file_result.get("field_matches", [])]
    self.assertEqual(backend.metadata_calls, [str(first), str(second)])
    self.assertEqual(matches[0]["zml_path"], str(second))
    self.assertEqual(matches[0]["field_path"], "target_field")

  def test_field_discovery_does_not_cache_repeated_timeouts_before_later_match(self) -> None:
    class TimeoutThenMatchBackend:
      name = "timeout-then-match"

      def __init__(self) -> None:
        self.metadata_calls: list[str] = []

      def field_metadata(self, path: str) -> BackendResult:
        self.metadata_calls.append(path)
        if path.endswith(("a.zml", "b.zml")):
          return BackendResult(blocker=Blocker(tool=self.name, message="field metadata timed out after 1.5s"), backend=self.name, metadata={"selected": self.name})
        return BackendResult(stdout=json.dumps({"topics": [{"topic": "/c", "fields": ["target_field"]}]}), backend=self.name, metadata={"selected": self.name, "source": "metadata"})

    backend = TimeoutThenMatchBackend()
    with tempfile.TemporaryDirectory() as temp_dir:
      paths = [Path(temp_dir) / name for name in ("a.zml", "b.zml", "c.zml")]
      for path in paths:
        path.write_text("", encoding="utf-8")

      packet = build_fields_packet(temp_dir, fuzzy="target_field", zml=AutoBackend(factories=[lambda: backend]))

    matches = [match for file_result in packet["files"] for match in file_result.get("field_matches", [])]
    self.assertEqual(backend.metadata_calls, [str(path) for path in paths])
    self.assertEqual(matches[0]["zml_path"], str(paths[2]))
    self.assertEqual(matches[0]["field_path"], "target_field")

  def test_empty_metadata_success_reports_sampling_needed_when_not_sampling(self) -> None:
    zml = FakeMetadataZml("")
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_fields_packet(str(path), fuzzy="target_field", zml=zml)

    discovery = packet["files"][0]["field_discovery"]
    markdown = render_markdown(packet)
    self.assertEqual(packet["status"], "ok")
    self.assertEqual(packet["files"][0]["field_matches"], [])
    self.assertEqual(discovery["needs_sampling"], True)
    self.assertIn("needs `--sample-top`", markdown)

  def test_field_discovery_samples_only_top_metadata_candidates_when_requested(self) -> None:
    metadata = json.dumps(
      {
        "topics": [
          {"topic": "/best", "fields": ["message.flight_phase_for_controller"]},
          {"topic": "/second", "fields": ["message.flight_phase_for_controller"]},
        ]
      }
    )
    zml = FakeMetadataZml(metadata, {"/best": '{"topic":"/best","timestamp":1,"fields":{"message":{"flight_phase_for_controller":"BOUND"}}}\n'})
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_fields_packet(str(path), fuzzy="flight_phase_for_controller", sample_top=1, zml=zml)

    matches = packet["files"][0]["field_matches"]
    self.assertEqual(zml.read_calls, ["/best"])
    self.assertEqual(matches[0]["source"], "metadata+sample")
    self.assertEqual(matches[0]["example_value"], "BOUND")

  def test_field_discovery_fallback_sampling_respects_topic_ranking_bound(self) -> None:
    zml = FakeFieldsZml(
      {
        "/zzz": '{"topic":"/zzz","timestamp":1,"fields":{"target_field":1}}\n',
        "/target/topic": '{"topic":"/target/topic","timestamp":1,"fields":{"target_field":2}}\n',
      }
    )
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_fields_packet(str(path), fuzzy="target_field", topic_fuzzy="target", max_topics_sampled=1, zml=zml)

    self.assertEqual(packet["status"], "ok")
    self.assertEqual(zml.read_calls, ["/target/topic"])
    self.assertEqual(packet["files"][0]["field_matches"][0]["topic"], "/target/topic")

  def test_fields_packet_renders_json_markdown_and_records_bounds(self) -> None:
    zml = FakeFieldsZml(
      {
        "/nav": "\n".join(
          [
            '{"topic":"/nav","timestamp":1,"fields":{"pose":{"x":1},"items":[{"value":2}]}}',
            '{"topic":"/nav","timestamp":2,"fields":{"pose":{"x":3},"items":[{"value":4}]}}',
          ]
        ),
      }
    )
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_fields_packet(str(path), fuzzy="value", topic=["/nav"], sample_limit=1, limit=5, zml=zml)

    json_text = render_json(packet)
    markdown = render_markdown(packet)
    discovery = packet["files"][0]["field_discovery"]

    self.assertIn('"mode": "fields"', json_text)
    self.assertIn("# ZML Field Discovery", markdown)
    self.assertIn("items[*].value", json_text)
    self.assertEqual(discovery["bounds"]["sample_limit_per_topic"], 1)
    self.assertEqual(discovery["sampled_topics"][0]["omitted_sample_count"], 1)

  def test_field_discovery_reports_topic_and_field_truncation(self) -> None:
    zml = FakeFieldsZml(
      {
        "/topic_a": '{"topic":"/topic_a","timestamp":1,"fields":{"k0":0,"k1":1,"k2":2}}\n',
        "/topic_b": '{"topic":"/topic_b","timestamp":1,"fields":{"k0":0}}\n',
      }
    )
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_fields_packet(str(path), fuzzy="k", sample_top=1, max_topics_sampled=1, max_fields_per_topic=1, zml=zml)

    discovery = packet["files"][0]["field_discovery"]
    self.assertEqual(discovery["omitted_topic_count"], 1)
    self.assertEqual(discovery["sampled_topics"][0]["field_count"], 1)
    self.assertGreater(discovery["sampled_topics"][0]["omitted_field_count"], 0)

  def test_topics_packet_preserves_remote_blocker(self) -> None:
    packet = build_topics_packet("s3://bucket/path/run.zml.zst", [], [], zml=FakeTopicsZml("/nav\n"))

    self.assertEqual(packet["status"], "blocked")
    self.assertEqual(packet["blockers"][0]["tool"], "source")

  def test_audit_blocks_non_empty_unparsed_zml_stdout(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_audit_packet(str(path), [TopicSpec("/test1")], TimeWindow(), zml=FakeZml("not parseable output"))

    self.assertEqual(packet["status"], "blocked")
    self.assertEqual(packet["blockers"][0]["tool"], "parser")
    self.assertIn("non-empty", packet["blockers"][0]["message"])

  def test_direct_exact_file_topic_field_skips_topic_listing(self) -> None:
    class DirectZml:
      def __init__(self) -> None:
        self.list_calls = 0

      def list_topics(self, path: str) -> BackendResult:
        self.list_calls += 1
        raise AssertionError("direct known extract should not list topics for an exact file")

      def read_topic(self, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...] = ()) -> BackendResult:
        return BackendResult(stdout='{"topic":"/target","timestamp":1,"fields":{"x":7,"y":8}}\n', backend="direct", metadata={"selected": "direct"})

    zml = DirectZml()
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml.zst"
      path.write_text("", encoding="utf-8")

      packet = build_audit_packet(str(path), [TopicSpec("/target", ("x",))], TimeWindow(), zml=zml, direct_known_extract=True)

    self.assertEqual(zml.list_calls, 0)
    self.assertEqual(packet["status"], "ok")
    self.assertEqual(packet["files"][0]["backend"]["list_topics"]["skipped"], True)
    self.assertEqual(packet["files"][0]["topics"][0]["fields"]["x"]["first"], 7)

  def test_direct_directory_topic_field_selects_by_topic_list_only(self) -> None:
    class DirectoryZml:
      def __init__(self, target_paths: set[str]) -> None:
        self.target_paths = target_paths
        self.list_calls: list[str] = []
        self.read_calls: list[tuple[str, str]] = []

      def list_topics(self, path: str) -> BackendResult:
        self.list_calls.append(path)
        topics = "/target\n/other\n" if path in self.target_paths else "/other\n"
        return BackendResult(stdout=topics, backend="fake", metadata={"selected": "fake"})

      def read_topic(self, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...] = ()) -> BackendResult:
        self.read_calls.append((path, topic))
        if topic != "/target":
          raise AssertionError("direct directory extraction should not sample unrelated topics")
        return BackendResult(stdout='{"topic":"/target","timestamp":1,"fields":{"x":3}}\n', backend="fake", metadata={"selected": "fake"})

    with tempfile.TemporaryDirectory() as temp_dir:
      root = Path(temp_dir)
      first = root / "a.zml"
      second = root / "b.zml.zst"
      third = root / "c.zml"
      for path in (first, second, third):
        path.write_text("", encoding="utf-8")
      zml = DirectoryZml({str(first), str(second)})

      packet = build_audit_packet(temp_dir, [TopicSpec("/target", ("x",))], TimeWindow(), zml=zml, direct_known_extract=True)

    selection = packet["files"][0]["backend"]["selection"]
    self.assertEqual(zml.list_calls, [str(first)])
    self.assertEqual(zml.read_calls, [(str(first), "/target")])
    self.assertEqual(selection["strategy"], "ranked_first_topic_match")
    self.assertEqual(selection["matching_candidate_count"], 1)
    self.assertEqual(selection["ambiguous"], True)
    self.assertEqual(selection["ambiguity_reason"], "uninspected_candidates_not_ruled_out")
    self.assertEqual(selection["uninspected_candidate_count"], 2)
    self.assertEqual(selection["selected_path"], str(first))

  def test_direct_extract_candidate_ranking_penalizes_opposite_compute_side(self) -> None:
    candidates = ("/logs/zip-0001/compute_b/compute_b.zml.zst", "/logs/zip-0001/compute_a/compute_a.zml.zst")

    ranked = rank_direct_extract_candidates(candidates, "/compute_a.zip_executive.cloud_bound_status")

    self.assertEqual(ranked[0], "/logs/zip-0001/compute_a/compute_a.zml.zst")

  def test_audit_does_not_block_when_window_filters_all_parsed_samples(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_audit_packet(str(path), [TopicSpec("/test1")], TimeWindow(start=10.0, end=20.0), zml=FakeZml("#0 @1.0 ~2.0 /test1 {'foo': 0}"))

    self.assertEqual(packet["status"], "ok")
    self.assertFalse(packet["files"][0]["topics"][0]["present"])

  def test_csv_renderer_includes_stats_and_sample_rows(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_audit_packet(str(path), [TopicSpec("/test1", ("foo",))], TimeWindow(), zml=FakeZml("#0 @1.0 ~2.0 /test1 {'foo': 7}"), include_samples=True)

    csv_text = render_csv(packet)

    self.assertIn("row_type,source,file,topic,timestamp,field,value", csv_text)
    self.assertIn("field_stats", csv_text)
    self.assertIn("sample", csv_text)
    self.assertIn("foo,7", csv_text)

  def test_csv_sample_export_is_bounded_with_marker_row(self) -> None:
    stdout = "\n".join(
      [
        "#0 @1.0 ~2.0 /test1 {'foo': 1}",
        "#1 @2.0 ~3.0 /test1 {'foo': 2}",
        "#2 @3.0 ~4.0 /test1 {'foo': 3}",
      ]
    )
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_audit_packet(str(path), [TopicSpec("/test1", ("foo",))], TimeWindow(), zml=FakeZml(stdout), include_samples=True, csv_sample_limit=2)

    topic = packet["files"][0]["topics"][0]
    csv_text = render_csv(packet)

    self.assertEqual(topic["sample_count"], 3)
    self.assertEqual(len(topic["samples"]), 2)
    self.assertEqual(topic["sample_export"]["total_count"], 3)
    self.assertEqual(topic["sample_export"]["included_count"], 2)
    self.assertEqual(topic["sample_export"]["omitted_sample_row_count"], 1)
    self.assertIn("sample_export_truncated", csv_text)
    self.assertIn("omitted_sample_rows", csv_text)

  def test_csv_renderer_includes_expanded_stats_and_bounds_sample_rows(self) -> None:
    stdout = "\n".join(
      [
        "#0 @1.0 ~2.0 /test1 {'items': [{'x': 1}, {'x': 2}]}",
        "#1 @2.0 ~3.0 /test1 {'items': [{'x': 3}, {'x': 4}]}",
      ]
    )
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_audit_packet(str(path), [TopicSpec("/test1", ("items[*].x",))], TimeWindow(), zml=FakeZml(stdout), include_samples=True, csv_sample_limit=1)

    topic = packet["files"][0]["topics"][0]
    csv_text = render_csv(packet)

    self.assertEqual(sorted(topic["fields"]), ["items[0].x", "items[1].x"])
    self.assertEqual(len(topic["samples"]), 1)
    self.assertIn("items[0].x,1", csv_text)
    self.assertNotIn("items[1].x,2", csv_text)
    self.assertNotIn("items[0].x,3", csv_text)
    self.assertEqual(topic["sample_export"]["total_sample_row_count"], 4)
    self.assertEqual(topic["sample_export"]["included_sample_row_count"], 1)
    self.assertEqual(topic["sample_export"]["partial_sample_count"], 1)
    self.assertIn("sample_export_truncated", csv_text)

  def test_audit_reports_field_expansion_truncation_without_blocking(self) -> None:
    fields = {f"k{index:04d}": index for index in range(1001)}
    stdout = "#0 @1.0 ~2.0 /test1 " + str(fields)
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_audit_packet(str(path), [TopicSpec("/test1", ("*",))], TimeWindow(), zml=FakeZml(stdout), include_samples=True, csv_sample_limit=2)

    topic = packet["files"][0]["topics"][0]
    csv_text = render_csv(packet)

    self.assertEqual(packet["status"], "ok")
    self.assertEqual(topic["field_expansion"], {"truncated_sample_count": 1, "expanded_field_limit_per_sample": 1000})
    self.assertEqual(len(topic["fields"]), 1000)
    self.assertIn("field_expansion_truncated", csv_text)

  def test_markdown_renderer_includes_stable_sections(self) -> None:
    packet = {
      "mode": "audit",
      "status": "ok",
      "source": {"input": "run.zml", "kind": "file", "candidates": ["run.zml"]},
      "files": [{"path": "run.zml", "topics": [summarize_topic(TopicSpec("/nav"), parse_samples("1 topic=/nav x=1")).to_dict()]}],
    }

    markdown = render_markdown(packet)

    self.assertIn("# ZML Signal Audit", markdown)
    self.assertIn("## Sources", markdown)
    self.assertIn("/nav", markdown)

  def test_markdown_compare_renders_field_deltas(self) -> None:
    spec = TopicSpec("/nav", ("x",))
    fail_samples = parse_samples("1 topic=/nav x=1\n2 topic=/nav x=5")
    pass_samples = parse_samples("1 topic=/nav x=1\n2 topic=/nav x=3")
    comparison = compare_runs(
      {"/nav": summarize_topic(spec, fail_samples)},
      {"/nav": summarize_topic(spec, pass_samples)},
      {"/nav": fail_samples},
      {"/nav": pass_samples},
    )

    markdown = render_markdown({"mode": "compare", "status": "ok", "comparison": comparison})

    self.assertIn("## Field deltas", markdown)
    self.assertIn("mean_delta", markdown)
    self.assertIn("1.0", markdown)

  def test_zml_cli_missing_binary_returns_blocker(self) -> None:
    with patch("zml_audit.backends.shutil.which", return_value=None):
      result = ZmlCli().list_topics("run.zml")

    self.assertIsNotNone(result.blocker)
    self.assertIn("not available", result.blocker.message)

  def test_explicit_backend_unavailable_blocks_without_fallback(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      with patch("zml_audit.backends.shutil.which", return_value=None):
        packet = build_topics_packet(str(path), [], [], backend_name="zml-cli")

    self.assertEqual(packet["status"], "blocked")
    self.assertEqual(packet["blockers"][0]["tool"], "zml-cli")
    self.assertNotIn("fallbacks", packet["files"][0].get("backend", {}))

  def test_auto_backend_falls_back_only_for_unavailable_backends(self) -> None:
    class MissingBackend:
      name = "missing"

      def available_blocker(self) -> Blocker:
        return Blocker(tool="missing", message="not installed")

    class GoodBackend:
      name = "good"

      def available_blocker(self) -> None:
        return None

      def list_topics(self, path: str) -> BackendResult:
        return BackendResult(stdout="/nav\n", backend=self.name, metadata={"selected": self.name})

    result = AutoBackend(factories=[MissingBackend, GoodBackend]).list_topics("run.zml")

    self.assertIsNone(result.blocker)
    self.assertEqual(result.stdout, "/nav\n")
    self.assertEqual(result.metadata["requested"], "auto")
    self.assertEqual(result.metadata["fallbacks"][0]["backend"], "missing")

  def test_auto_backend_caches_unavailable_backend_probe_within_command(self) -> None:
    class MissingBackend:
      name = "missing"
      probe_count = 0

      def available_blocker(self) -> Blocker:
        MissingBackend.probe_count += 1
        return Blocker(tool="missing", message="not installed")

    auto = AutoBackend(factories=[MissingBackend])

    auto.list_topics("a.zml")
    auto.list_topics("b.zml")

    self.assertEqual(MissingBackend.probe_count, 1)

  def test_auto_audit_uses_zml_conv_read_when_no_listing_backend_exists(self) -> None:
    class ReadOnlyZmlConv:
      name = "zml-conv"

      def read_topic(self, path: str, topic: str, window: TimeWindow) -> BackendResult:
        return BackendResult(stdout='{"identifier":"/nav","log_ts":1,"x":2}\n', backend=self.name, metadata={"selected": self.name})

    class MissingBackend:
      name = "missing"

      def available_blocker(self) -> Blocker:
        return Blocker(tool="missing", message="not installed")

    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_audit_packet(str(path), [TopicSpec("/nav", ("x",))], TimeWindow(), zml=AutoBackend(factories=[ReadOnlyZmlConv, MissingBackend]))

    self.assertEqual(packet["status"], "ok")
    self.assertEqual(packet["blockers"], [])
    self.assertEqual(packet["files"][0]["backend"]["list_topics"]["unsupported_operation"], True)
    self.assertEqual(packet["files"][0]["topics"][0]["fields"]["x"]["first"], 2)

  def test_auto_topics_still_blocks_when_no_listing_backend_exists(self) -> None:
    class ReadOnlyZmlConv:
      name = "zml-conv"

      def read_topic(self, path: str, topic: str, window: TimeWindow) -> BackendResult:
        return BackendResult(stdout="", backend=self.name)

    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      packet = build_topics_packet(str(path), [], [], zml=AutoBackend(factories=[ReadOnlyZmlConv]))

    self.assertEqual(packet["status"], "blocked")
    self.assertEqual(packet["files"][0]["backend"]["unsupported_operation"], True)

  def test_auto_backend_does_not_fallback_after_backend_command_failure(self) -> None:
    class FailingBackend:
      name = "failing"

      def available_blocker(self) -> None:
        return None

      def read_topic(self, path: str, topic: str, window: TimeWindow) -> BackendResult:
        return BackendResult(blocker=Blocker(tool="failing", message="input failed"), backend=self.name, metadata={"selected": self.name})

    class GoodBackend:
      name = "good"

      def available_blocker(self) -> None:
        return None

      def read_topic(self, path: str, topic: str, window: TimeWindow) -> BackendResult:
        return BackendResult(stdout="should not be used", backend=self.name)

    result = AutoBackend(factories=[FailingBackend, GoodBackend]).read_topic("run.zml", "/nav", TimeWindow())

    self.assertIsNotNone(result.blocker)
    self.assertEqual(result.blocker.tool, "failing")
    self.assertEqual(result.metadata["selected"], "failing")

  def test_auto_backend_read_returns_blocker_when_no_backend_is_usable(self) -> None:
    with patch("zml_audit.backends.shutil.which", return_value=None):
      result = select_backend("auto", systems_root="/missing/Systems").read_topic("run.zml", "/nav", TimeWindow())

    self.assertIsNotNone(result.blocker)
    self.assertEqual(result.blocker.tool, "auto")
    self.assertEqual(result.metadata["requested"], "auto")
    self.assertEqual([fallback["backend"] for fallback in result.metadata["fallbacks"]], ["zml-conv", "zml-cli"])

  def test_auto_backend_uses_raw_fallback_for_exact_requested_fields(self) -> None:
    commands: list[list[str]] = []

    def runner(command, **kwargs):
      commands.append(command)
      if command[-2] == "print":
        return SimpleNamespace(returncode=139, stdout="", stderr="segfault")
      return SimpleNamespace(returncode=0, stdout="#0 @1.0 1.0 /nav deadbeef\n", stderr="")

    with patch("zml_audit.backends.shutil.which", return_value="/usr/bin/zml"), patch("zml_audit.raw.decode_print_raw_stdout", return_value=('{"topic":"/nav","timestamp":1,"fields":{"x":4}}\n', None)):
      result = AutoBackend(factories=[lambda: ZmlCliBackend(runner=runner)]).read_topic("run.zml", "/nav", TimeWindow(), fields=("x",))

    self.assertIsNone(result.blocker)
    self.assertEqual(result.metadata["selected"], "zml-print-raw")
    self.assertEqual(result.metadata["decoded_failures"][0]["backend"], "zml-cli")
    self.assertIn("failed", result.metadata["decoded_failures"][0]["reason"])
    self.assertEqual([command[-2] for command in commands], ["print", "print_raw"])
    self.assertIn('"x":4', result.stdout)

  def test_supported_backend_choices_exclude_python_adapter(self) -> None:
    self.assertEqual(BACKEND_CHOICES, ("auto", "zml-conv", "zml-cli", "local-text"))
    with self.assertRaises(ValueError):
      select_backend("python")

  def test_auto_backend_default_order_is_zml_conv_then_zml_cli(self) -> None:
    backend = select_backend("auto", systems_root="/custom/Systems")

    self.assertEqual([backend._backend(index).name for index in range(len(backend.factories))], ["zml-conv", "zml-cli"])

  def test_field_metadata_probe_has_no_python_adapter_fallback(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "run.zml"
      path.write_text("", encoding="utf-8")

      with patch("zml_audit.backends.shutil.which", return_value=None):
        packet = build_fields_packet(str(path), fuzzy="target_field", no_sample=True, zml=select_backend("auto", systems_root="/missing/Systems"), systems_root="/missing/Systems")

    fallbacks = packet["files"][0]["field_discovery"]["metadata_probe"]["fallbacks"]
    self.assertEqual([fallback["backend"] for fallback in fallbacks], ["zml-conv", "zml-cli"])

  def test_zml_conv_command_pushes_down_start_and_end_times(self) -> None:
    command = build_zml_conv_command("run.zml", "/nav", TimeWindow(start=10.0, end=20.0), prefix=["zml-conv"])

    self.assertEqual(command[:7], ["zml-conv", "--input", "run.zml", "--output", "-", "--identifier", "/nav"])
    self.assertIn("--format", command)
    self.assertEqual(command[command.index("--start-ts") + 1], "1970-01-01T00:00:10Z")
    self.assertEqual(command[command.index("--end-ts") + 1], "1970-01-01T00:00:20.000001Z")

  def test_cli_parser_accepts_backend_for_topics_audit_and_compare(self) -> None:
    cases = [
      ["zml_signal_audit.py", "topics", "run.zml", "--backend", "zml-cli", "--systems-root", "/custom/Systems"],
      ["zml_signal_audit.py", "audit", "run.zml", "--topic", "/nav", "--backend", "zml-conv", "--systems-root", "/custom/Systems"],
      ["zml_signal_audit.py", "compare", "--fail", "fail.zml", "--pass", "pass.zml", "--topic", "/nav", "--backend", "zml-cli", "--systems-root", "/custom/Systems"],
    ]
    for argv in cases:
      with self.subTest(argv=argv), patch.object(sys, "argv", argv):
        args = parse_args()

      self.assertEqual(args.backend, argv[argv.index("--backend") + 1])
      self.assertEqual(args.systems_root, "/custom/Systems")

  def test_cli_parser_accepts_fuzzy_topic_search(self) -> None:
    with patch.object(sys, "argv", ["zml_signal_audit.py", "topics", "run.zml", "--fuzzy", "controller", "--limit", "5"]):
      args = parse_args()

    self.assertEqual(args.fuzzy, "controller")
    self.assertEqual(args.limit, 5)

  def test_cli_parser_accepts_field_discovery_args(self) -> None:
    with patch.object(sys, "argv", ["zml_signal_audit.py", "fields", "run.zml", "--fuzzy", "phase", "--topic-fuzzy", "cloud", "--sample-limit", "2", "--sample-top", "1", "--max-zmls", "5", "--workers", "2", "--max-topics", "6", "--max-topics-sampled", "3", "--max-fields-per-topic", "4", "--format", "both", "--out-dir", "/tmp/zml-fields"]):
      args = parse_args()

    self.assertEqual(args.command, "fields")
    self.assertEqual(args.fuzzy, "phase")
    self.assertEqual(args.topic_fuzzy, "cloud")
    self.assertEqual(args.sample_limit, 2)
    self.assertEqual(args.sample_top, 1)
    self.assertEqual(args.max_zmls, 5)
    self.assertEqual(args.workers, 2)
    self.assertEqual(args.max_topics, 6)
    self.assertEqual(args.max_topics_sampled, 3)
    self.assertEqual(args.max_fields_per_topic, 4)
    self.assertEqual(args.format, "both")


if __name__ == "__main__":
  unittest.main()
