"""Source-anchor and transport-envelope contract for diagram inventories."""

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from render import DiagramError
from review_edges import review

REVISION = "ab" * 20


def evidence() -> dict:
    return {
        "revision": REVISION,
        "edges": [
            {
                "sender": "CloudMock",
                "via": "ZipBoundCarrier",
                "receiver": "World adapter",
                "kind": "message",
                "proof": [{"path": "world.rs", "needle": "send_zipbound_carrier"}],
            },
            {
                "sender": "QUIC gateway",
                "via": "SyncResponseBatch carrying ZipboundCriticalMessage",
                "receiver": "CMA",
                "kind": "network",
                "on_wire": "SyncResponseBatch",
                "proof": [
                    {"path": "server.rs", "needle": "encode(SyncResponseBatch)", "role": "send"},
                    {"path": "client.rs", "needle": "decode(SyncResponseBatch)", "role": "receive"},
                ],
            },
        ],
    }


def source(_revision: str, path: str) -> str:
    return {
        "world.rs": "fn send_zipbound_carrier() {}\n",
        "server.rs": "encode(SyncResponseBatch)\n",
        "client.rs": "decode(SyncResponseBatch)\n",
    }[path]


def test_review_checks_source_anchors_and_wire_envelope() -> None:
    output = review(evidence(), source)
    assert "CloudMock --ZipBoundCarrier--> World adapter [world.rs:1]" in output
    assert "QUIC gateway --SyncResponseBatch carrying ZipboundCriticalMessage--> CMA" in output
    assert "server.rs:1, client.rs:1" in output


@pytest.mark.parametrize(
    "change, error",
    [
        (lambda spec: spec["edges"][0].update(sender="World adapter"), "self-loop"),
        (lambda spec: spec["edges"][0]["proof"][0].update(needle="never_in_source"), "not found"),
        (lambda spec: spec["edges"][0]["proof"][0].update(path="../secret"), "repo-relative"),
        (
            lambda spec: spec["edges"][1].update(via="bare ZipboundCriticalMessage"),
            "on-wire envelope",
        ),
        (lambda spec: spec["edges"][1]["proof"].pop(), "send and receive"),
        (
            lambda spec: spec["edges"][1]["proof"][0].update(needle="encode(OtherMessage)"),
            "must mention",
        ),
    ],
)
def test_review_rejects_missing_or_misleading_evidence(
    change: Callable[[dict], object], error: str
) -> None:
    spec = evidence()
    change(spec)
    with pytest.raises(DiagramError, match=error):
        review(spec, source)
