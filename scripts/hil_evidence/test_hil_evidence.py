from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hil_evidence.artifacts import inventory_from_listing, test_record_uris
from hil_evidence.gha import CommandFailure, filter_args, job_matches, list_recent_hil_candidates
from hil_evidence.log_summary import summarize_log
from hil_evidence.models import Packet
from hil_evidence.packet import (
    build_recent_packet,
    build_summary_packet,
    inventory_summaries,
    keep_recent_jobs_confirmed_by_test_record,
    summarize_candidate,
)
from hil_evidence.presets import canonical_preset_names, preset_matches, preset_test_record_query, resolve_preset
from hil_evidence.render import render_markdown
from hil_evidence.sources import normalize_source
from hil_evidence.sync import build_sync_check, extract_default_test_configs
from hil_evidence.test_record import summarize_record
from hil_evidence_cli import parse_args


class HilEvidencePureTests(unittest.TestCase):
    def test_normalize_github_job_url(self) -> None:
        source = normalize_source("https://github.com/ZiplineTeam/FlightSystems/actions/runs/123/job/456")

        self.assertEqual(source.kind, "github_job")
        self.assertEqual(source.repo, "ZiplineTeam/FlightSystems")
        self.assertEqual(source.run_id, "123")
        self.assertEqual(source.job_id, "456")

    def test_log_summary_extracts_failure_and_links(self) -> None:
        summary = summarize_log(
            "\n".join(
                [
                    "Validator failed: missing route segment",
                    "ERROR mission aborted",
                    "FAILED tests/test_autokiosk.py::test_delivery",
                    "S3_WEB_LINK_IN_SUMMARY=\"s3://platform2-testing-logs/p2-zip-system-hil/run/test_record.json\"",
                ]
            )
        )

        self.assertEqual(summary["validator_failures"][0]["line"], 1)
        self.assertIn("tests/test_autokiosk.py::test_delivery", summary["failed_scenarios_or_tests"])
        self.assertEqual(summary["links"]["s3_links"], ["s3://platform2-testing-logs/p2-zip-system-hil/run/test_record.json"])

    def test_log_summary_preserves_tail_matches_after_saturation(self) -> None:
        lines = []
        for index in range(6):
            lines.append(f"Validator failed early {index}")
            lines.append(f"FAILED tests/test_autokiosk.py::test_early_{index}")
        lines.extend(["noise"] * 8001)
        lines.append("Validator failed near tail")
        lines.append("FAILED tests/test_autokiosk.py::test_tail")

        summary = summarize_log("\n".join(lines), max_items=4)

        self.assertEqual(len(summary["validator_failures"]), 4)
        self.assertEqual(summary["validator_failures"][-1]["text"], "Validator failed near tail")
        self.assertIn("tests/test_autokiosk.py::test_tail", summary["failed_scenarios_or_tests"])
        self.assertEqual(summary["scanned_line_count"], len(lines))

        markdown = render_markdown({"status": "partial", "mode": "summarize", "log_summary": summary})
        self.assertIn("Validator failed near tail", markdown)
        self.assertIn("tests/test_autokiosk.py::test_tail", markdown)

    def test_local_test_record_packet_renders_stable_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "test_record.json"
            path.write_text('{"test_info":{"name":"autokiosk","result":"failed"}}', encoding="utf-8")

            packet = build_summary_packet(str(path), preset="autokiosk")
            markdown = render_markdown(packet)

        self.assertEqual(packet["status"], "ok")
        self.assertIn("# HIL/GHA Evidence Packet", markdown)
        self.assertIn("test_record.json", markdown)
        self.assertIn("autokiosk", markdown)

    def test_mismatched_job_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_source("https://github.com/ZiplineTeam/FlightSystems/actions/runs/123", job="https://github.com/ZiplineTeam/FlightSystems/actions/runs/999/job/456")

    def test_local_directory_returns_error_packet(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            packet = build_summary_packet(temp_dir)

        self.assertEqual(packet["status"], "error")
        self.assertIn("local path is not a file", packet["errors"][0]["message"])

    def test_recent_query_keeps_only_test_record_confirmed_jobs(self) -> None:
        packet = Packet(mode="recent", query={})
        packet.jobs = [
            {"candidate": {"job_id": "1"}, "test_records": [{"query_matches": []}]},
            {"candidate": {"job_id": "2"}, "test_records": [{"query_matches": [{"path": "$.test_info.name"}]}]},
        ]

        keep_recent_jobs_confirmed_by_test_record(
            packet,
            [{"job_id": "1"}, {"job_id": "2"}],
            "autokiosk",
            max_matches=3,
            searched_count=2,
        )

        self.assertEqual([job["candidate"]["job_id"] for job in packet.jobs], ["2"])
        self.assertEqual([candidate["job_id"] for candidate in packet.candidates], ["2"])
        self.assertEqual(packet.query["confirmed_test_record_match_count"], 1)

    def test_recent_query_preserves_blocked_unconfirmed_jobs(self) -> None:
        packet = Packet(mode="recent", query={})
        packet.jobs = [
            {"candidate": {"job_id": "1"}, "test_records": [], "blockers": [{"tool": "aws", "message": "blocked"}]},
        ]

        keep_recent_jobs_confirmed_by_test_record(
            packet,
            [{"job_id": "1"}],
            "autokiosk",
            max_matches=3,
            searched_count=1,
        )

        self.assertEqual(packet.status, "partial")
        self.assertEqual(packet.query["unconfirmed_candidate_count"], 1)
        self.assertEqual(packet.query["negative_candidate_count"], 0)
        self.assertEqual(packet.jobs[0]["test_record_confirmation"]["status"], "unconfirmed")
        self.assertEqual(packet.candidates[0]["test_record_confirmation"]["status"], "unconfirmed")

    def test_test_record_discovery_uses_full_inventory_listing(self) -> None:
        listing = "\n".join(
            [
                "2026-05-10 00:00:00          1 p2-zip-system-hil/run/noise.txt",
                "2026-05-10 00:00:01          1 p2-zip-system-hil/run/test_record.json",
            ]
        )

        inventory = inventory_from_listing("s3://platform2-testing-logs/p2-zip-system-hil/run/", listing, max_items=1)

        self.assertTrue(inventory["truncated"])
        self.assertEqual(
            test_record_uris(["s3://platform2-testing-logs/p2-zip-system-hil/run/"], [inventory]),
            ["s3://platform2-testing-logs/p2-zip-system-hil/run/test_record.json"],
        )

    def test_inventory_classifies_zml_and_validator_artifacts(self) -> None:
        listing = "\n".join(
            [
                "2026-05-10 00:00:00        100 p2-zip-system-hil/run/logs/compute.zml.zst",
                "2026-05-10 00:00:01        200 p2-zip-system-hil/run/logs/world.zml",
                "2026-05-10 00:00:02        300 p2-zip-system-hil/run/validation/validator_summary.json",
            ]
        )

        inventory = inventory_from_listing("s3://platform2-testing-logs/p2-zip-system-hil/run/", listing, max_items=10)

        hints = inventory["key_artifact_hints"]
        self.assertEqual([hint["category"] for hint in hints], ["zml", "zml", "validation"])
        self.assertTrue(all(item["key_file"] for item in inventory["items"]))

    def test_inventory_keeps_key_hints_beyond_displayed_items_cap(self) -> None:
        listing = "\n".join(
            [
                "2026-05-10 00:00:00          1 p2-zip-system-hil/run/noise.txt",
                "2026-05-10 00:00:01        200 p2-zip-system-hil/run/logs/late.zml.zst",
            ]
        )

        inventory = inventory_from_listing("s3://platform2-testing-logs/p2-zip-system-hil/run/", listing, max_items=1)

        self.assertTrue(inventory["truncated"])
        self.assertEqual([item["key"] for item in inventory["items"]], ["p2-zip-system-hil/run/noise.txt"])
        self.assertEqual(inventory["key_artifact_hints"][0]["category"], "zml")
        self.assertEqual(
            inventory["key_artifact_hints"][0]["uri"],
            "s3://platform2-testing-logs/p2-zip-system-hil/run/logs/late.zml.zst",
        )

    def test_late_test_record_size_survives_saturated_key_hint_cap(self) -> None:
        listing = "\n".join(
            [
                f"2026-05-10 00:00:{index:02d}        100 p2-zip-system-hil/run/logs/{index}.zml.zst"
                for index in range(26)
            ]
            + ["2026-05-10 00:01:00        999 p2-zip-system-hil/run/test_record.json"]
        )

        inventory = inventory_from_listing("s3://platform2-testing-logs/p2-zip-system-hil/run/", listing, max_items=1)
        markdown = render_markdown(
            {
                "status": "ok",
                "mode": "summarize",
                "s3": {
                    "test_record_uris": test_record_uris(["s3://platform2-testing-logs/p2-zip-system-hil/run/"], [inventory]),
                    "inventories": inventory_summaries([inventory]),
                },
            }
        )

        self.assertEqual(len(inventory["key_artifact_hints"]), 25)
        self.assertFalse(any(hint["category"] == "test_record" for hint in inventory["key_artifact_hints"]))
        self.assertEqual(inventory["test_record_artifacts"][0]["size"], 999)
        self.assertIn("| test_record | test_record.json | s3://platform2-testing-logs/p2-zip-system-hil/run/test_record.json | 999 |", markdown)

    def test_markdown_renders_key_artifacts_and_mission_context(self) -> None:
        packet = {
            "status": "ok",
            "mode": "summarize",
            "jobs": [
                {
                    "candidate": {"job_name": "HIL Test: zip_delivery"},
                    "s3": {
                        "roots": ["s3://platform2-testing-logs/p2-zip-system-hil/run/"],
                        "baraza": {
                            "links": ["https://baraza.example/missions/P2M_abc"],
                            "mission_ids": ["P2M_abc"],
                            "flight_ids": ["P2F_def"],
                            "candidates": [
                                {
                                    "mission_id": "P2M_abc",
                                    "flight_id": "P2F_def",
                                    "link": "https://baraza.example/missions/P2M_abc",
                                }
                            ],
                        },
                        "test_record_uris": ["s3://platform2-testing-logs/p2-zip-system-hil/run/test_record.json"],
                        "inventories": [
                            {
                                "s3_uri": "s3://platform2-testing-logs/p2-zip-system-hil/run/",
                                "count": 4,
                                "key_artifact_hints": [
                                    {
                                        "category": "test_record",
                                        "type": "test_record.json",
                                        "uri": "s3://platform2-testing-logs/p2-zip-system-hil/run/test_record.json",
                                        "size": 456,
                                        "note": "Authoritative test result and manifest.",
                                    },
                                    {
                                        "category": "zml",
                                        "type": "compressed ZML",
                                        "uri": "s3://platform2-testing-logs/p2-zip-system-hil/run/logs/compute.zml.zst",
                                        "size": 1234,
                                        "note": "Validator and journal signal streams.",
                                    }
                                ],
                            }
                        ],
                    },
                    "test_records": [
                        {
                            "s3_uri": "s3://platform2-testing-logs/p2-zip-system-hil/run/test_record.json",
                            "test_name": "zip_delivery",
                            "result": "failed",
                        }
                    ],
                }
            ],
        }

        markdown = render_markdown(packet)

        self.assertIn("### Key S3 artifacts", markdown)
        self.assertIn("s3://platform2-testing-logs/p2-zip-system-hil/run/logs/compute.zml.zst", markdown)
        self.assertIn("| test_record | test_record.json | s3://platform2-testing-logs/p2-zip-system-hil/run/test_record.json | 456 |", markdown)
        self.assertIn("| zml | compressed ZML |", markdown)
        self.assertIn("### Mission context", markdown)
        self.assertIn("https://baraza.example/missions/P2M_abc", markdown)
        self.assertIn("`P2F_def`", markdown)

    def test_markdown_combines_test_record_baraza_link_with_flight_id(self) -> None:
        markdown = render_markdown(
            {
                "status": "ok",
                "mode": "summarize",
                "test_records": [
                    {
                        "s3_uri": "test_record.json",
                        "baraza_urls": [{"url": "https://baraza.example/missions/P2M_record"}],
                        "mission_info_identifiers": [
                            {"kind": "flight", "value": "P2F_record", "source": "mission_info"},
                        ],
                    }
                ],
            }
        )

        self.assertIn("| P2M_record | P2F_record | https://baraza.example/missions/P2M_record | test_record.json |", markdown)

    def test_markdown_mission_context_does_not_invent_baraza_links(self) -> None:
        markdown = render_markdown(
            {
                "status": "ok",
                "mode": "summarize",
                "s3": {"baraza": {"mission_ids": ["P2M_only"], "flight_ids": ["P2F_only"], "candidates": [{"mission_id": "P2M_only", "flight_id": "P2F_only"}]}},
            }
        )

        self.assertIn("Baraza links: not directly observed", markdown)
        self.assertIn("link not directly observed", markdown)
        self.assertNotIn("https://baraza", markdown)

    def test_recent_preset_preserves_github_lookup_errors(self) -> None:
        with patch(
            "hil_evidence.packet.gha.list_recent_hil_candidates",
            return_value=([], [{"tool": "github", "message": "gh run list failed"}], {"preset": "autokiosk"}),
        ):
            packet = build_recent_packet(preset="autokiosk", max_matches=3)

        self.assertEqual(packet["status"], "error")
        self.assertEqual(packet["errors"][0]["message"], "gh run list failed")

    def test_recent_autokiosk_defaults_use_broader_search_bound(self) -> None:
        with patch("hil_evidence.gha.list_runs", return_value=[]) as list_runs:
            _, _, query = list_recent_hil_candidates(preset="zip_autokiosk", passing=True, max_matches=3)

        self.assertEqual(query["limit"], 1000)
        self.assertEqual(query["lookback_hours"], 3000.0)
        list_runs.assert_called_once()
        self.assertEqual(list_runs.call_args.args[1], 1000)

    def test_recent_autokiosk_alias_uses_same_search_bound(self) -> None:
        with patch("hil_evidence.gha.list_runs", return_value=[]):
            _, _, canonical_query = list_recent_hil_candidates(preset="zip_autokiosk")
            _, _, alias_query = list_recent_hil_candidates(preset="autokiosk")

        self.assertEqual(alias_query["limit"], canonical_query["limit"])
        self.assertEqual(alias_query["lookback_hours"], canonical_query["lookback_hours"])

    def test_recent_explicit_limit_and_lookback_override_autokiosk_defaults(self) -> None:
        with patch("hil_evidence.gha.list_runs", return_value=[]):
            _, _, query = list_recent_hil_candidates(preset="zip_autokiosk", limit=7, lookback_hours=12.5)

        self.assertEqual(query["limit"], 7)
        self.assertEqual(query["lookback_hours"], 12.5)

    def test_recent_cli_leaves_search_bound_defaults_unset(self) -> None:
        with patch("sys.argv", ["hil_evidence_cli.py", "recent", "--preset", "zip_autokiosk"]):
            args = parse_args()

        self.assertIsNone(args.limit)
        self.assertIsNone(args.lookback_hours)

        with patch(
            "sys.argv",
            ["hil_evidence_cli.py", "recent", "--preset", "zip_autokiosk", "--limit", "7", "--lookback-hours", "12.5"],
        ):
            args = parse_args()

        self.assertEqual(args.limit, 7)
        self.assertEqual(args.lookback_hours, 12.5)

    def test_recent_packet_leaves_search_bound_defaults_to_gha(self) -> None:
        with patch(
            "hil_evidence.packet.gha.list_recent_hil_candidates",
            return_value=([], [], {"preset": "zip_autokiosk", "limit": 1000, "lookback_hours": 3000.0}),
        ) as list_candidates:
            build_recent_packet(preset="zip_autokiosk", max_matches=3)

        kwargs = list_candidates.call_args.kwargs
        self.assertIsNone(kwargs["limit"])
        self.assertIsNone(kwargs["lookback_hours"])

    def test_presets_cover_canonical_systems_hil_kinds_and_aliases(self) -> None:
        names = set(canonical_preset_names())

        self.assertTrue(
            {
                "zip_delivery",
                "zip_delivery_ev3",
                "zip_autokiosk",
                "zip_delivery_real_dock",
                "mission_suite",
                "dock_hil_full_suite",
                "return_to_service",
                "return_to_service_ev3",
            }.issubset(names)
        )
        self.assertEqual(resolve_preset("autokiosk"), resolve_preset("zip_autokiosk"))
        self.assertEqual(resolve_preset("real-dock-delivery"), resolve_preset("zip_delivery_real_dock"))
        self.assertEqual(preset_test_record_query("real-dock-delivery"), "phoenix_delivery_real_dock")

    def test_preset_job_matching_uses_exact_hil_test_token(self) -> None:
        args = filter_args(preset="zip_delivery")

        self.assertTrue(job_matches({"name": "Zip Droid Delivery Test / HIL Test: zip_delivery"}, args, None))
        self.assertFalse(job_matches({"name": "EV3 Zip Droid Delivery Test / HIL Test: zip_delivery_ev3"}, args, None))
        self.assertFalse(job_matches({"name": "Real Dock / HIL Test: zip_delivery_real_dock"}, args, None))

    def test_preset_run_matching_accepts_experimental_manual_title_with_token_boundaries(self) -> None:
        title = "P2 Zip System HIL Build & Test - Manual Run - (experimental) ZIP_DELIVERY_V4 -> runs phoenix_zip_delivery"

        self.assertTrue(preset_matches(title, "zip_delivery_v4", "run_title_fragments"))
        self.assertFalse(preset_matches(title, "zip_delivery", "run_title_fragments"))

    def test_preset_test_record_query_is_exact_for_pytest_parameters(self) -> None:
        ev3_record = {"test_info": {"name": "test_missions[phoenix_delivery_ev3]"}}
        delivery_record = {"test_info": {"name": "test_missions[phoenix_delivery]"}}

        self.assertEqual(summarize_record(ev3_record, "test_record.json", "phoenix_delivery", exact_query=True)["query_matches"], [])
        self.assertTrue(summarize_record(delivery_record, "test_record.json", "phoenix_delivery", exact_query=True)["query_matches"])
        self.assertTrue(summarize_record(ev3_record, "test_record.json", "phoenix_delivery")["query_matches"])

    def test_recent_generic_filters_and_explicit_test_record_query_are_threaded(self) -> None:
        with patch(
            "hil_evidence.packet.gha.list_recent_hil_candidates",
            return_value=([], [], {"preset": "zip_delivery"}),
        ) as list_candidates:
            packet = build_recent_packet(
                preset="zip_delivery",
                job_name="HIL Test: zip_delivery",
                title="Manual Run",
                branch="develop",
                status=["completed"],
                conclusion=["success"],
                test_record_query="custom_query",
                max_matches=3,
            )

        kwargs = list_candidates.call_args.kwargs
        self.assertEqual(kwargs["job_name"], "HIL Test: zip_delivery")
        self.assertEqual(kwargs["title"], "Manual Run")
        self.assertEqual(kwargs["branch"], "develop")
        self.assertEqual(kwargs["status"], ["completed"])
        self.assertEqual(kwargs["conclusion"], ["success"])
        self.assertIsNone(kwargs["max_matches"])
        self.assertEqual(packet["query"]["test_record_query"], "custom_query")
        self.assertEqual(packet["query"]["test_record_query_source"], "explicit")

    def test_sync_check_static_parser_and_report_shape(self) -> None:
        source = '''
from enum import StrEnum, auto

class ValidTest(StrEnum):
    ZIP_DELIVERY = auto()

class TestConfig:
    _TEST_TARGETS = {
        ValidTest.ZIP_DELIVERY: ("phoenix", "-k test_missions[phoenix_delivery]"),
    }

class DefaultTestConfigs:
    @staticmethod
    def _defaults():
        return {
            ValidTest.ZIP_DELIVERY: ("version_set.json", ["p2-hil"], "Zip Droid Delivery Test"),
        }
'''
        with tempfile.TemporaryDirectory() as temp_dir:
            systems_root = Path(temp_dir)
            config_path = systems_root / "hil/ci/workflow/utils/default_test_configs.py"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(source, encoding="utf-8")

            extracted = extract_default_test_configs(config_path)
            with patch("hil_evidence.sync.PRESETS", {"zip_delivery": resolve_preset("zip_delivery")}), patch(
                "hil_evidence.sync.alias_targets",
                return_value={},
            ):
                report = build_sync_check(str(systems_root))

        self.assertEqual(extracted["zip_delivery"].display_name, "Zip Droid Delivery Test")
        self.assertEqual(extracted["zip_delivery"].test_record_query, "phoenix_delivery")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["counts"]["systems_canonical"], 1)
        self.assertEqual(report["missing_presets"], [])
        self.assertEqual(report["extra_presets"], [])

    def test_explicit_job_stops_when_metadata_unavailable(self) -> None:
        packet = Packet(mode="summarize")
        failure = CommandFailure(["gh", "api", "repos/example/actions/jobs/2"], 1, "", "not found")

        with patch("hil_evidence.packet.gha.job_api", side_effect=failure), patch("hil_evidence.packet.gha.job_log") as job_log:
            summarize_candidate(
                packet,
                "example/repo",
                {"run_id": "1", "job_id": "2"},
                max_inventory_items=1,
                max_test_records=1,
                test_record_query=None,
                require_job_metadata=True,
            )

        job_log.assert_not_called()
        self.assertEqual(packet.jobs[0]["blockers"][0]["message"], "gh job API failed for 2")


if __name__ == "__main__":
    unittest.main()
