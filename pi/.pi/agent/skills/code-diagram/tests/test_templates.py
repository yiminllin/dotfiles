"""Comparison styling keeps graph and flow connectors intact."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from render import DiagramError, render


def panel(label: str, *, changed: bool = False) -> dict:
    return {
        "canvas": [43, 5],
        "nodes": [
            {"id": "queue", "name": "Queue", "rect": [0, 0, 10, 4]},
            {
                "id": "worker",
                "name": "Worker",
                "rect": [31, 0, 42, 4],
                **({"changed": True} if changed else {}),
            },
        ],
        "edges": [
            {
                "from": "queue",
                "to": "worker",
                "points": [[10, 2], [31, 2]],
                "label": label,
                "label_at": [13, 1],
            }
        ],
    }


def test_stacked_comparison_preserves_ports_and_marks_selected_box() -> None:
    result = render(
        {
            "kind": "before_after",
            "before_label": "BEFORE THIS PR",
            "after_label": "AFTER THIS PR",
            "before": panel("Job"),
            "after": panel("JobBundle", changed=True),
        }
    )
    before, after = result.strip().split("\n\n")
    assert before.startswith("BEFORE THIS PR\n")
    assert after.startswith("AFTER THIS PR\n")
    assert "+==========+" not in before
    assert after.count("+==========+") == 2
    assert after.count("+---------+") == 2
    assert before.splitlines()[3] == after.splitlines()[3]
    assert "+" + "-" * 19 + ">+" in after.splitlines()[3]


def test_callout_on_handoff_does_not_change_borders() -> None:
    diagram = render({"kind": "graph", **panel("[1] JobBundle")})
    assert "[1] JobBundle" in diagram
    assert "=" not in diagram


def test_flow_delta_keeps_bottom_port() -> None:
    result = render(
        {
            "kind": "flow",
            "nodes": [{"name": "Queue", "changed": True}, {"name": "Worker"}],
            "arrows": ["JobBundle"],
        }
    )
    assert "+============+============+" in result
    assert "+" + "-" * 25 + "+" in result


def test_reject_nonboolean_change_flag() -> None:
    graph = {"kind": "graph", **panel("Job")}
    graph["nodes"][0]["changed"] = "true"
    with pytest.raises(DiagramError, match="changed must be a boolean"):
        render(graph)
