"""Closed boxes, explicit ports, and collision-free orthogonal connector geometry."""

import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from render import DiagramError, render


@pytest.fixture
def graph() -> dict:
    return {
        "kind": "graph",
        "canvas": [45, 9],
        "nodes": [
            {"id": "a", "name": "Client", "detail": "writer", "rect": [0, 0, 12, 4]},
            {"id": "b", "name": "Server", "detail": "reader", "rect": [30, 0, 42, 4]},
        ],
        "edges": [
            {
                "from": "a",
                "to": "b",
                "points": [[12, 1], [30, 1]],
                "label": "Request",
                "label_at": [16, 0],
            },
            {
                "from": "b",
                "to": "a",
                "points": [[30, 3], [12, 3]],
                "label": "Response",
                "label_at": [16, 4],
            },
        ],
    }


def test_graph_renders_closed_boxes_and_both_directions_deterministically(graph: dict) -> None:
    expected = (
        "+-----------+   Request       +-----------+\n"
        "| Client    +---------------->+ Server    |\n"
        "| writer    |                 | reader    |\n"
        "|           +<----------------+           |\n"
        "+-----------+   Response      +-----------+\n"
    )
    original = deepcopy(graph)
    assert render(graph) == expected
    assert render(graph) == expected
    assert graph == original


def test_graph_bends_and_vertical_arrow_attach_to_named_target(graph: dict) -> None:
    graph["nodes"][1]["rect"] = [30, 5, 42, 8]
    graph["nodes"][1].pop("detail")
    graph["edges"] = [
        {
            "from": "a",
            "to": "b",
            "points": [[12, 2], [36, 2], [36, 5]],
            "label": "Request",
            "label_at": [16, 1],
        }
    ]
    lines = render(graph).splitlines()
    assert lines[2][12:37] == "+-----------------------+"
    assert lines[3][36] == "|"
    assert lines[4][36] == "v"
    assert lines[5][36] == "+"
    assert "Server" in lines[6]


def test_graph_wraps_exact_identifiers_at_dots(graph: dict) -> None:
    graph["canvas"] = [60, 12]
    graph["nodes"][0]["rect"] = [0, 3, 12, 7]
    graph["nodes"][1]["rect"] = [30, 3, 42, 7]
    graph["edges"][0].update(
        points=[[12, 4], [30, 4]],
        label="Event on topic.events.received",
        label_at=[15, 0],
        label_width=16,
    )
    graph["edges"][1].update(points=[[30, 6], [12, 6]], label_at=[16, 8])
    diagram = render(graph)
    assert "Event on topic." in diagram
    assert "events.received" in diagram
    assert all(line == line.rstrip() for line in diagram.splitlines())


@pytest.mark.parametrize(
    "change,error",
    [
        ({"from": "missing"}, "existing nodes"),
        ({"to": "a"}, "distinct existing"),
        ({"points": [[12, 1], [30, 2]]}, "orthogonal"),
        ({"points": [[12, 1], [12, 1], [30, 1]]}, "nonzero"),
        ({"points": [[0, 1], [30, 1]]}, "attach outward"),
        ({"points": [[12, 0], [30, 0]]}, "non-corner"),
        (
            {"points": [[12, 1], [29, 1], [29, 2], [30, 2]]},
            "straight approach",
        ),
        ({"points": [[12, 1], [20, 1], [20, 2], [10, 2], [10, 1], [30, 1]]}, "retrace"),
        ({"label_at": [3, 2]}, "overlaps"),
        ({"label_at": [40, 6]}, "exceeds"),
        ({"label_at": [45, 2]}, "inside the canvas"),
        ({"label_width": True}, "positive integer"),
    ],
)
def test_graph_rejects_invalid_edge_geometry(graph: dict, change: dict, error: str) -> None:
    graph["edges"][0].update(change)
    with pytest.raises(DiagramError, match=error):
        render(graph)


def test_graph_rejects_connector_through_unrelated_box(graph: dict) -> None:
    graph["nodes"].append({"id": "c", "name": "Other", "rect": [17, 0, 26, 4]})
    with pytest.raises(DiagramError, match="overlaps"):
        render(graph)


def test_graph_rejects_crossing_connectors(graph: dict) -> None:
    graph["canvas"] = [45, 15]
    graph["nodes"].extend(
        [
            {"id": "c", "name": "Input", "rect": [14, 7, 26, 10]},
            {"id": "d", "name": "Output", "rect": [30, 11, 42, 14]},
        ]
    )
    graph["edges"].append(
        {
            "from": "c",
            "to": "d",
            "points": [[20, 7], [20, 2], [36, 2], [36, 11]],
            "label": "Event",
            "label_at": [0, 6],
        }
    )
    with pytest.raises(DiagramError, match="overlaps"):
        render(graph)


@pytest.mark.parametrize("problem", ["overlap", "duplicate", "text", "canvas", "reuse"])
def test_graph_rejects_ambiguous_or_unrenderable_spec(graph: dict, problem: str) -> None:
    if problem == "overlap":
        graph["nodes"][1]["rect"] = [5, 0, 17, 4]
    elif problem == "duplicate":
        graph["nodes"][1]["id"] = "a"
    elif problem == "text":
        graph["nodes"][0]["name"] = "very long symbol name"
        graph["nodes"][0]["detail"] = "another long description"
    elif problem == "canvas":
        graph["canvas"] = [True, 9]
    else:
        graph["edges"].append(deepcopy(graph["edges"][0]))
    with pytest.raises(DiagramError):
        render(graph)
