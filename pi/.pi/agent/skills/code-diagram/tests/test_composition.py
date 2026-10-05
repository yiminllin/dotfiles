"""ID-based tree columns, meaningful comparison rows, and label association."""

import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from render import DiagramError, render
from review_edges import review


def annotated_tree() -> dict:
    return {
        "kind": "tree",
        "root": {
            "id": "owner",
            "name": "Owner",
            "children": [
                {"id": "extra", "name": "Extra"},
                {"id": "transport", "name": "Transport"},
            ],
        },
        "annotations": {
            "owner": "Owns both paths",
            "transport": "Separate request and response queues",
        },
        "annotation_width": 22,
    }


def test_annotations_follow_ids_when_nodes_are_inserted_or_reordered() -> None:
    spec = annotated_tree()
    for children in (spec["root"]["children"], list(reversed(spec["root"]["children"]))):
        spec["root"]["children"] = children
        before = deepcopy(spec)
        result = render(spec)
        assert result == render(spec) and spec == before
        assert any(
            "Transport" in row and "Separate request and" in row for row in result.splitlines()
        )
        assert not any("Extra" in row and "Separate" in row for row in result.splitlines())
        assert "response queues" in result
        assert (
            len(
                {
                    row.index(note)
                    for row in result.splitlines()
                    for note in ("Owns both paths", "Separate request and", "response queues")
                    if note in row
                }
            )
            == 1
        )


def test_comparison_aligns_shared_ids_not_ordinal_rows() -> None:
    before = annotated_tree()
    before.pop("kind")
    after = deepcopy(before)
    after["root"]["name"] = "Gateway"
    after["root"]["children"].pop(0)
    result = render({"kind": "before_after", "before": before, "after": after})
    assert any(row.count("Transport") == 2 for row in result.splitlines())
    assert any(row.count("Separate request and") == 2 for row in result.splitlines())
    assert "Extra" in result and "Gateway" in result


@pytest.mark.parametrize("problem", ["unknown", "duplicate", "order", "wide"])
def test_tree_composition_rejects_unfaithful_alignment(problem: str) -> None:
    before = annotated_tree()
    if problem == "unknown":
        before["annotations"]["missing"] = "Not a node"
    elif problem == "duplicate":
        before["root"]["children"][0]["id"] = "owner"
    elif problem == "wide":
        before["root"]["name"] = "X" * 121
    else:
        after = deepcopy(before)
        after["root"]["children"].reverse()
        before.pop("kind")
        after.pop("kind")
        with pytest.raises(DiagramError, match="different order"):
            render({"kind": "before_after", "before": before, "after": after})
        return
    with pytest.raises(DiagramError):
        render(before)


@pytest.mark.parametrize("char", ["\x00", "\x1b", "\x7f", "\v", "\f"])
def test_renderer_rejects_invisible_control_characters(char: str) -> None:
    with pytest.raises(DiagramError, match="printable ASCII"):
        render({"kind": "flow", "nodes": [{"name": "Name" + char + "value"}], "arrows": []})


@pytest.mark.parametrize("row,error", [(14, "within 4 cells"), (2, "ambiguous")])
def test_graph_label_must_belong_to_its_own_connector(row: int, error: str) -> None:
    spec = {
        "kind": "graph",
        "canvas": [40, 18],
        "nodes": [
            {"id": "a", "name": "Sender", "rect": [0, 0, 12, 4]},
            {"id": "b", "name": "Reader", "rect": [28, 0, 39, 4]},
        ],
        "edges": [
            {
                "from": "a",
                "to": "b",
                "points": [[12, 1], [28, 1]],
                "label": "forward",
                "label_at": [16, row],
            },
            {
                "from": "b",
                "to": "a",
                "points": [[28, 3], [12, 3]],
                "label": "reverse",
                "label_at": [16, 5],
            },
        ],
    }
    with pytest.raises(DiagramError, match=error):
        render(spec)


def test_call_edges_and_explicit_transport_classification() -> None:
    edge = {
        "sender": "Caller",
        "via": "invoke callee",
        "receiver": "Callee",
        "kind": "call",
        "proof": [{"path": "example.rs", "needle": "callee();"}],
    }
    inventory = {"revision": "ab" * 20, "edges": [edge]}
    assert "invoke callee" in review(
        inventory, lambda _revision, _path: "fn caller() { callee(); }"
    )
    edge["transport"] = "gRPC"
    with pytest.raises(DiagramError, match="only for network"):
        review(inventory, lambda _revision, _path: "fn caller() { callee(); }")
