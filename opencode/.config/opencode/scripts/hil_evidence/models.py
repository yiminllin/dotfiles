from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


DEFAULT_REPO = "ZiplineTeam/FlightSystems"
DEFAULT_WORKFLOW = "p2-zip-system-hil-build.yml"
DEFAULT_WORKFLOW_TITLE = "P2 Zip System HIL Build & Test"


JsonDict = dict[str, Any]


@dataclass(frozen=True)
class Source:
    kind: str
    input: str
    repo: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    s3_uri: str | None = None
    local_path: str | None = None

    def to_dict(self) -> JsonDict:
        return {key: value for key, value in self.__dict__.items() if value not in (None, "")}


@dataclass
class Packet:
    mode: str
    source: Source | None = None
    query: JsonDict = field(default_factory=dict)
    status: str = "running"
    github: JsonDict = field(default_factory=dict)
    candidates: list[JsonDict] = field(default_factory=list)
    jobs: list[JsonDict] = field(default_factory=list)
    s3: JsonDict = field(default_factory=dict)
    test_records: list[JsonDict] = field(default_factory=list)
    log_summary: JsonDict = field(default_factory=dict)
    confidence: list[str] = field(default_factory=list)
    ambiguity: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    blockers: list[JsonDict] = field(default_factory=list)
    errors: list[JsonDict] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        packet: JsonDict = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mode": self.mode,
            "status": self.status,
            "source": self.source.to_dict() if self.source else None,
            "query": self.query,
            "github": self.github,
            "candidates": self.candidates,
            "jobs": self.jobs,
            "s3": self.s3,
            "test_records": self.test_records,
            "log_summary": self.log_summary,
            "confidence": self.confidence,
            "ambiguity": self.ambiguity,
            "next_steps": self.next_steps,
            "blockers": self.blockers,
            "errors": self.errors,
        }
        return {key: value for key, value in packet.items() if value not in (None, [], {})}
