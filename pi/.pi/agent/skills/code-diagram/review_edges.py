"""Check that a diagram's essential edge inventory has historical source anchors.

An anchor's presence does not prove the proposed relationship: inspect the cited
code and the rendered diagram before accepting the edge.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import subprocess
import sys
from collections.abc import Callable
from functools import cache
from pathlib import PurePosixPath
from urllib.parse import quote

from render import DiagramError, keys, text


def source_at(revision: str, path: str, github: bool) -> str:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"], capture_output=True, text=True, check=False
    )
    if result.returncode == 0:
        return result.stdout
    if not github:
        raise DiagramError(
            f"cannot read {revision}:{path} locally; inspect it manually or use --github with approval"
        )
    url = f"repos/ZiplineTeam/FlightSystems/contents/{quote(path, safe='/')}?ref={revision}"
    result = subprocess.run(["gh", "api", url], capture_output=True, text=True, check=False)
    if result.returncode:
        raise DiagramError(f"cannot read {revision}:{path}: {result.stderr.strip()[:180]}")
    try:
        return base64.b64decode(json.loads(result.stdout)["content"]).decode("utf-8")
    except (ValueError, KeyError, UnicodeError, binascii.Error) as error:
        raise DiagramError(f"invalid GitHub source for {revision}:{path}") from error


MIN_ANCHOR_LENGTH = 8


def checked_proof(
    proof: object,
    where: str,
    revision: str,
    on_wire: str | None,
    source: Callable[[str], str],
) -> tuple[str, str | None]:
    anchor = keys(proof, {"path", "needle"}, {"path", "needle", "role"}, where)
    path = text(anchor["path"], f"{where}.path")
    if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or "\\" in path:
        raise DiagramError(f"{where}.path must be a repo-relative source path")
    needle = text(anchor["needle"], f"{where}.needle")
    if len(needle) < MIN_ANCHOR_LENGTH:
        raise DiagramError(f"{where}.needle is too short to identify a source line")
    role = anchor.get("role")
    if role is not None:
        role = text(role, f"{where}.role")
        if on_wire is None or role not in {"send", "receive"}:
            raise DiagramError(f"{where}.role must be send or receive on a network edge")
        if on_wire not in needle:
            raise DiagramError(f"{where}.needle must mention {on_wire!r}")
    matching = [i for i, line in enumerate(source(path).splitlines(), 1) if needle in line]
    if not matching:
        raise DiagramError(f"{where}: {needle!r} not found at {revision}:{path}")
    return f"{path}:{matching[0]}", role


def review(spec: object, read_source: Callable[[str, str], str]) -> str:
    item = keys(spec, {"revision", "edges"}, {"revision", "edges"}, "inventory")
    revision = text(item["revision"], "revision")
    if not re.fullmatch(r"[0-9a-f]{40}|HEAD", revision):
        raise DiagramError("revision must be a full commit SHA or HEAD")
    edges = item["edges"]
    if not isinstance(edges, list) or not edges:
        raise DiagramError("edges must contain at least one verified relationship")

    @cache
    def source(path: str) -> str:
        return read_source(revision, path)

    lines = []
    for index, edge in enumerate(edges):
        where = f"edges[{index}]"
        entry = keys(
            edge,
            {"sender", "via", "receiver", "kind", "proof"},
            {"sender", "via", "receiver", "kind", "proof", "on_wire", "transport"},
            where,
        )
        sender = text(entry["sender"], f"{where}.sender")
        via = text(entry["via"], f"{where}.via")
        receiver = text(entry["receiver"], f"{where}.receiver")
        kind = text(entry["kind"], f"{where}.kind")
        if kind not in {
            "call",
            "message",
            "network",
            "dependency",
            "ownership",
            "configuration",
            "error",
        }:
            raise DiagramError(f"{where}.kind is unknown: {kind}")
        if sender == receiver:
            raise DiagramError(f"{where} is a self-loop; verify the actual sender of the response")
        proofs = entry["proof"]
        if not isinstance(proofs, list) or not proofs:
            raise DiagramError(f"{where}.proof needs a source anchor")
        on_wire = entry.get("on_wire")
        transport = entry.get("transport")
        if kind == "network":
            if transport is not None:
                text(transport, f"{where}.transport")
            on_wire = text(on_wire, f"{where}.on_wire")
            if on_wire not in via:
                raise DiagramError(f"{where}.via must name the on-wire envelope {on_wire!r}")
        elif on_wire is not None or transport is not None:
            raise DiagramError(f"{where}.on_wire and transport are only for network edges")
        checked = [
            checked_proof(proof, f"{where}.proof[{i}]", revision, on_wire, source)
            for i, proof in enumerate(proofs)
        ]
        if kind == "network" and {role for _, role in checked} != {"send", "receive"}:
            raise DiagramError(f"{where}.proof needs send and receive anchors for {on_wire}")
        lines.append(f"{sender} --{via}--> {receiver} [{', '.join(c for c, _ in checked)}]")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--github",
        action="store_true",
        help="fetch missing historical source from GitHub (requires prior approval)",
    )
    args = parser.parse_args()
    try:
        sys.stdout.write(
            review(json.load(sys.stdin), lambda rev, path: source_at(rev, path, args.github))
        )
    except (DiagramError, json.JSONDecodeError) as error:
        parser.exit(2, f"evidence: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
