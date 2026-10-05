"""Generic fixed-grid contract for the code-diagram renderer."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from render import DiagramError, render


def test_flow_aligns_varied_box_widths_and_preserves_edge_labels() -> None:
    for size in (1, 14, 35, 45):
        name = "S" * size
        diagram = render(
            {
                "kind": "flow",
                "nodes": [
                    {"name": "HTTP client", "detail": "sends request"},
                    {"name": name},
                    {"name": "Database"},
                ],
                "arrows": [
                    "GET /v1/orders on http.request.received",
                    "SQL query orders.by_id",
                ],
            }
        )
        lines = diagram.splitlines()
        box_lines = [line for line in lines if line.startswith(("+", "|"))]
        assert len({len(line) for line in box_lines}) == 1
        center = len(box_lines[0]) // 2
        assert all(line.index("+", 1) == center for line in box_lines if line.count("+") == 3)
        assert all(line.index("v") == center for line in lines if line.strip() == "v")
        assert name in diagram
        assert "GET /v1/orders" in diagram
        assert "http." in diagram and "request." in diagram and "received" in diagram
        assert "orders.by_id" in diagram
        assert "\t" not in diagram
        assert all(line == line.rstrip() for line in lines)


def test_before_after_aligns_stages_even_with_unequal_label_and_box_heights() -> None:
    diagram = render(
        {
            "kind": "before_after",
            "before": {
                "nodes": [
                    {"name": "CSV import", "detail": "legacy input"},
                    {"name": "Batch ETL"},
                    {"name": "Database"},
                ],
                "arrows": ["file drop", "normalized rows"],
            },
            "after": {
                "nodes": [
                    {"name": "Event bus"},
                    {"name": "Stream processor", "detail": "validates events"},
                    {"name": "Database"},
                ],
                "arrows": ["CustomerCreated on orders.stream.ingest", "validated record"],
            },
        }
    )
    lines = diagram.splitlines()
    assert lines[0].startswith("BEFORE") and "AFTER" in lines[0]
    assert any("Batch ETL" in line and "Stream processor" in line for line in lines)
    assert any(line.count("Database") == 2 for line in lines)
    assert "file drop" in diagram and "orders." in diagram and "ingest" in diagram
    assert all(line == line.rstrip() for line in lines)


def test_before_after_can_show_an_added_stage_without_dropping_it() -> None:
    diagram = render(
        {
            "kind": "before_after",
            "before": {"nodes": [{"name": "Direct write"}], "arrows": []},
            "after": {
                "nodes": [{"name": "API"}, {"name": "Queue"}, {"name": "Worker"}],
                "arrows": ["JobCreated", "JobReady"],
            },
        }
    )
    assert "Direct write" in diagram
    assert "Queue" in diagram and "Worker" in diagram
    assert all(line == line.rstrip() for line in diagram.splitlines())


def test_tree_shows_nested_siblings_and_relationships() -> None:
    diagram = render(
        {
            "kind": "tree",
            "root": {
                "name": "Build",
                "children": [
                    {
                        "name": "Compiler",
                        "via": "depends on",
                        "children": [{"name": "Parser"}, {"name": "Codegen"}],
                    },
                    {"name": "Linker"},
                ],
            },
        }
    )
    assert "+-- Compiler  [depends on]" in diagram
    assert "|   +-- Parser" in diagram
    assert "|   \\-- Codegen" in diagram
    assert "\\-- Linker" in diagram


def test_routes_keep_parallel_paths_separate_and_repeat_shared_owner() -> None:
    diagram = render(
        {
            "kind": "routes",
            "routes": [
                {
                    "name": "REQUEST: queue A",
                    "nodes": [
                        {"name": "Producer A"},
                        {"name": "Queue A"},
                        {"name": "Shared adapter"},
                    ],
                    "arrows": ["EventCreated", "queued event"],
                },
                {
                    "name": "REQUEST: queue B",
                    "nodes": [
                        {"name": "Producer B"},
                        {"name": "Queue B", "detail": "separate"},
                        {"name": "Shared adapter"},
                    ],
                    "arrows": ["EventCreated", "queued event"],
                },
                {
                    "name": "SHARED",
                    "nodes": [{"name": "Shared adapter"}, {"name": "Consumer"}],
                    "arrows": ["Event on topic.events.received"],
                },
            ],
        }
    )
    first, second, shared = diagram.split("\n\n")
    assert "| Queue A" in first and "| Shared adapter" in first
    assert "| Queue B" in second and "| separate" in second and "| Shared adapter" in second
    assert "Queue B" not in first and "Queue A" not in second
    assert "| Shared adapter" in shared and "| Consumer" in shared
    assert "queued event" in first and "queued event" in second
    assert "Event on topic." in shared and "received" in shared
    assert "[Queue" not in diagram
    assert all(line == line.rstrip() for line in diagram.splitlines())


def test_routes_wrap_long_labels_without_changing_endpoints() -> None:
    diagram = render(
        {
            "kind": "routes",
            "routes": [
                {
                    "name": "LONG",
                    "nodes": [{"name": "Long producer name"}, {"name": "Long consumer name"}],
                    "arrows": [
                        "ObservationEpoch on rtk.active.rtcm3_corrections.wired.observation_epochs"
                    ],
                }
            ],
        }
    )
    assert "| Long producer name" in diagram
    assert "| Long consumer name" in diagram
    assert sum(line.strip() == "v" for line in diagram.splitlines()) == 1
    assert "rtk." in diagram and "observation_epochs" in diagram


def test_cli_renders_stdin_and_reports_invalid_specs_without_output() -> None:
    script = Path(__file__).resolve().parents[1] / "render.py"
    valid = subprocess.run(
        [sys.executable, str(script), "-"],
        input=json.dumps({"kind": "flow", "nodes": [{"name": "Queue"}], "arrows": []}),
        text=True,
        capture_output=True,
        check=False,
    )
    assert valid.returncode == 0
    assert "| Queue" in valid.stdout and not valid.stderr

    invalid = subprocess.run(
        [sys.executable, str(script), "-"],
        input=json.dumps({"kind": "unsupported"}),
        text=True,
        capture_output=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert not invalid.stdout
    assert "unknown diagram kind" in invalid.stderr


def test_single_node_does_not_invent_an_edge() -> None:
    diagram = render({"kind": "flow", "nodes": [{"name": "Queue"}], "arrows": []})
    assert "Queue" in diagram
    assert "v" not in diagram


@pytest.mark.parametrize(
    "spec, error",
    [
        ({"kind": "flow", "nodes": [{"name": "A"}, {"name": "B"}], "arrows": []}, "arrows"),
        ({"kind": "flow", "nodes": [{"name": "A\tB"}], "arrows": []}, "tabs"),
        ({"kind": "flow", "nodes": [{"name": "A"}], "arrows": [], "edges": []}, "unknown"),
        ({"kind": "tree", "root": {"name": "A", "via": "x"}}, "root cannot"),
        ({"kind": "flow", "nodes": [{"name": "x" * 46}], "arrows": []}, "shorten"),
        (
            {
                "kind": "flow",
                "nodes": [{"name": "A"}, {"name": "B"}],
                "arrows": ["long_identifier_" * 4],
            },
            "shorten",
        ),
        ({"kind": "flow", "nodes": [{"name": "A"}], "arrows": ["unused"]}, "arrows"),
        ({"kind": "flow", "nodes": [{"name": "A"}], "arrows": [], "before": {}}, "unknown"),
        ({"kind": "unsupported", "nodes": [], "arrows": []}, "unknown diagram kind"),
        ({"kind": "routes", "routes": []}, "must contain at least one route"),
        (
            {
                "kind": "routes",
                "routes": [{"name": "A", "nodes": [{"name": "x" * 99}], "arrows": []}],
            },
            "shorten",
        ),
        (
            {
                "kind": "routes",
                "routes": [{"name": "A", "nodes": [{"name": "X"}, {"name": "Y"}], "arrows": []}],
            },
            "arrows",
        ),
        (
            {
                "kind": "routes",
                "routes": [{"name": "A", "nodes": [{"name": "X"}], "arrows": [], "edges": []}],
            },
            "unknown",
        ),
    ],
)
def test_invalid_or_unsupported_topology_is_rejected(spec: dict, error: str) -> None:
    with pytest.raises(DiagramError, match=error):
        render(spec)
