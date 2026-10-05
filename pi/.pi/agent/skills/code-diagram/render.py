"""Render a small, source-verified diagram specification on a fixed ASCII grid."""

from __future__ import annotations

import argparse
import json
import re
import sys
from itertools import pairwise, zip_longest
from pathlib import Path

MIN_WIDTH = 27
MAX_WIDTH = 49
MAX_CANVAS_WIDTH = 120
MAX_CANVAS_HEIGHT = 100
POINT_DIMENSIONS = 2
RECT_COORDINATES = 4
MIN_BOX_WIDTH = 7
MIN_BOX_HEIGHT = 3
MIN_PATH_CELLS = 4
MAX_LABEL_DISTANCE = 4
LANE_GAP = "    "

Node = tuple[str, str | None]
Flow = tuple[list[Node], list[str]]


class DiagramError(ValueError):
    """The diagram specification cannot be laid out faithfully."""


def text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DiagramError(f"{where} must be a nonempty, trimmed string")
    if not value.isascii() or not value.isprintable():
        raise DiagramError(f"{where} must be single-line printable ASCII without tabs")
    return value


def keys(value: object, required: set[str], allowed: set[str], where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise DiagramError(f"{where} must be an object")
    missing = required - value.keys()
    unknown = value.keys() - allowed
    if missing or unknown:
        raise DiagramError(f"{where}: missing {sorted(missing)}, unknown {sorted(unknown)}")
    return value


def flow_spec(value: object, where: str) -> Flow:
    spec = keys(value, {"nodes", "arrows"}, {"nodes", "arrows"}, where)
    nodes = spec["nodes"]
    arrows = spec["arrows"]
    if not isinstance(nodes, list) or not nodes:
        raise DiagramError(f"{where}.nodes must contain at least one node")
    if not isinstance(arrows, list) or len(arrows) != len(nodes) - 1:
        raise DiagramError(f"{where}.arrows must have exactly one label per adjacent node pair")
    parsed_nodes = []
    for index, node in enumerate(nodes):
        name = f"{where}.nodes[{index}]"
        item = keys(node, {"name"}, {"name", "detail"}, name)
        parsed_nodes.append(
            (
                text(item["name"], f"{name}.name"),
                text(item["detail"], f"{name}.detail") if "detail" in item else None,
            )
        )
    return parsed_nodes, [text(label, f"{where}.arrows[{i}]") for i, label in enumerate(arrows)]


def width_for(*flows: Flow) -> int:
    names = (len(line) for nodes, _ in flows for node in nodes for line in node if line)
    segments = (
        len(piece.strip())
        for _, arrows in flows
        for arrow in arrows
        for piece in re.findall(r"[^. ]+\.|[^. ]+| +", arrow)
    )
    width = max(MIN_WIDTH, max([*names, *segments]) + 4)
    width += (width + 1) % 2  # Odd width gives one exact center column.
    if width > MAX_WIDTH:
        raise DiagramError(f"diagram needs {width} columns (maximum {MAX_WIDTH}); shorten a label")
    return width


def wrap_label(label: str, width: int) -> list[str]:
    limit = width - 4
    pieces = re.findall(r"[^. ]+\.|[^. ]+| +", label)
    lines: list[str] = []
    current = ""
    for piece in pieces:
        candidate = current + piece
        if len(candidate.strip()) > limit and current.strip():
            lines.append(current.strip())
            current = piece.lstrip()
        else:
            current = candidate
        if len(current.strip()) > limit:
            raise DiagramError(f"arrow label segment exceeds {limit} columns: {current!r}")
    if current.strip():
        lines.append(current.strip())
    return lines


def render_flow(
    flow: Flow,
    width: int,
    edge_heights: list[int] | None = None,
    node_heights: list[int] | None = None,
) -> list[str]:
    nodes, arrows = flow
    center = width // 2
    border = "+" + "-" * (width - 2) + "+"
    joined = "+" + "-" * (center - 1) + "+" + "-" * (width - center - 2) + "+"
    lines = []
    for index, (name, detail) in enumerate(nodes):
        lines.append(border)
        lines.extend(
            "| " + label.ljust(width - 4) + " |" for label in (name, detail) if label is not None
        )
        if node_heights is not None and node_heights[index] > 1 + (detail is not None):
            lines.append("| " + " " * (width - 4) + " |")
        lines.append(joined if index < len(arrows) else border)
        if index < len(arrows):
            parts = wrap_label(arrows[index], width)
            lines.extend(part.center(width).rstrip() for part in parts)
            if edge_heights is not None:
                lines.extend([""] * (edge_heights[index] - len(parts)))
            lines.extend((" " * center + "|", " " * center + "v"))
    return lines


def tree_column(value: object) -> list[tuple[str | None, str, str]]:
    """Compose separately laid-out tree and note columns using node IDs."""
    spec = keys(value, {"root"}, {"root", "annotations", "annotation_width"}, "tree")
    rows: list[tuple[str | None, str, str, str]] = []
    ids: set[str] = set()

    def visit(node_value: object, prefix: str, last: bool, where: str, root: bool = False) -> None:
        node = keys(node_value, {"name"}, {"id", "name", "via", "children"}, where)
        node_id = text(node["id"], f"{where}.id") if "id" in node else None
        if node_id is not None:
            if node_id in ids:
                raise DiagramError(f"duplicate tree node id {node_id!r}")
            ids.add(node_id)
        name = text(node["name"], f"{where}.name")
        via = text(node["via"], f"{where}.via") if "via" in node else None
        if root and via:
            raise DiagramError("root cannot have a 'via' relationship")
        children = node.get("children", [])
        if not isinstance(children, list):
            raise DiagramError(f"{where}.children must be an array")
        line = ("" if root else prefix + ("\\-- " if last else "+-- ")) + name
        if via:
            line += f"  [{via}]"
        child_prefix = "" if root else prefix + ("    " if last else "|   ")
        continuation = child_prefix + ("|" if children else "")
        rows.append((node_id, line, "" if root else prefix + "|", continuation))
        for index, child in enumerate(children):
            visit(child, child_prefix, index == len(children) - 1, f"{where}.children[{index}]")

    visit(spec["root"], "", True, "root", root=True)
    notes = spec.get("annotations", {})
    if not isinstance(notes, dict) or any(key not in ids for key in notes):
        raise DiagramError("annotations must map existing tree node IDs to text")
    note_width = spec.get("annotation_width", 32)
    if type(note_width) is not int or note_width < 1:
        raise DiagramError("annotation_width must be a positive integer")
    wrapped = {
        key: wrap_label(text(note, f"annotations[{key!r}]"), note_width + 4)
        for key, note in notes.items()
    }
    width = max(len(line) for _, line, _, _ in rows)
    left: list[tuple[str | None, str, str]] = []
    anchors: dict[str, int] = {}
    for node_id, line, padding, continuation in rows:
        if node_id is not None:
            anchors[node_id] = len(left)
        left.append((node_id, line, padding))
        left.extend((None, continuation, continuation) for _ in wrapped.get(node_id, [])[1:])
    right = [""] * len(left)
    for node_id, lines in wrapped.items():
        start = anchors[node_id]
        right[start : start + len(lines)] = lines
    result = [
        (node_id, (line.ljust(width) + LANE_GAP + note).rstrip() if notes else line, padding)
        for (node_id, line, padding), note in zip(left, right, strict=True)
    ]
    if max(len(line) for _, line, _ in result) > MAX_CANVAS_WIDTH:
        raise DiagramError("tree columns exceed 120 columns; shorten detail or use a symbol legend")
    return result


def render_tree(root: object) -> list[str]:
    return [line for _, line, _ in tree_column({"root": root})]


def render_tree_comparison(before: object, after: object) -> list[str]:
    left, right = tree_column(before), tree_column(after)
    left_ids = {node_id for node_id, _, _ in left if node_id is not None}
    shared = left_ids & {node_id for node_id, _, _ in right if node_id is not None}
    order = [node_id for node_id, _, _ in left if node_id in shared]
    if order != [node_id for node_id, _, _ in right if node_id in shared]:
        raise DiagramError("shared tree IDs have different order; use separate figures")
    width = max(len("BEFORE"), *(len(line) for _, line, _ in left))
    if (
        width + len(LANE_GAP) + max(len("AFTER"), *(len(line) for _, line, _ in right))
        > MAX_CANVAS_WIDTH
    ):
        raise DiagramError("tree comparison exceeds 120 columns; shorten detail or split figures")
    lines = ["BEFORE".ljust(width) + LANE_GAP + "AFTER"]
    a = b = 0
    for node_id in [*order, None]:
        ai = (
            next((i for i in range(a, len(left)) if left[i][0] == node_id), len(left))
            if node_id is not None
            else len(left)
        )
        bi = (
            next((i for i in range(b, len(right)) if right[i][0] == node_id), len(right))
            if node_id is not None
            else len(right)
        )
        pad_left = left[ai][2] if ai < len(left) else ""
        pad_right = right[bi][2] if bi < len(right) else ""
        for lrow, rrow in zip_longest(left[a:ai], right[b:bi]):
            ltext = lrow[1] if lrow is not None else pad_left
            rtext = rrow[1] if rrow is not None else pad_right
            lines.append((ltext.ljust(width) + LANE_GAP + rtext).rstrip())
        if node_id is not None:
            lines.append((left[ai][1].ljust(width) + LANE_GAP + right[bi][1]).rstrip())
        a, b = ai + 1, bi + 1
    return lines


def render_routes(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise DiagramError("diagram.routes must contain at least one route")
    lines: list[str] = []
    for index, route in enumerate(value):
        where = f"diagram.routes[{index}]"
        item = keys(route, {"name", "nodes", "arrows"}, {"name", "nodes", "arrows"}, where)
        flow = flow_spec({key: val for key, val in item.items() if key != "name"}, where)
        if lines:
            lines.append("")
        lines.append(text(item["name"], f"{where}.name"))
        lines.extend(render_flow(flow, width_for(flow)))
    return lines


class _GraphCanvas:
    """A character grid with occupied cells, named rectangles, and distinct ports."""

    def __init__(self, canvas: object) -> None:
        if (
            not isinstance(canvas, list)
            or len(canvas) != POINT_DIMENSIONS
            or any(type(n) is not int for n in canvas)
            or not 1 <= canvas[0] <= MAX_CANVAS_WIDTH
            or not 1 <= canvas[1] <= MAX_CANVAS_HEIGHT
        ):
            raise DiagramError("canvas must be [width, height], at most 120 x 100")
        self.width, self.height = canvas
        self.cells: dict[tuple[int, int], str] = {}
        self.rectangles: dict[str, tuple[int, int, int, int]] = {}
        self.used_ports: set[tuple[int, int]] = set()
        self.paths: list[set[tuple[int, int]]] = []
        self.labels: list[set[tuple[int, int]]] = []

    def point(self, value: object, where: str) -> tuple[int, int]:
        if (
            not isinstance(value, list)
            or len(value) != POINT_DIMENSIONS
            or any(type(n) is not int for n in value)
            or not 0 <= value[0] < self.width
            or not 0 <= value[1] < self.height
        ):
            raise DiagramError(f"{where} must be an integer [x, y] inside the canvas")
        return value[0], value[1]

    def paint(self, x: int, y: int, char: str, where: str) -> None:
        if not 0 <= x < self.width or not 0 <= y < self.height:
            raise DiagramError(f"{where} exceeds the canvas at {(x, y)}")
        if (x, y) in self.cells:
            raise DiagramError(f"{where} overlaps a box, connector, or label at {(x, y)}")
        self.cells[x, y] = char

    def node(self, value: object, where: str) -> None:
        node = keys(value, {"id", "name", "rect"}, {"id", "name", "detail", "rect"}, where)
        node_id = text(node["id"], f"{where}.id")
        if node_id in self.rectangles:
            raise DiagramError(f"{where}: duplicate node id {node_id!r}")
        rect = node["rect"]
        if not isinstance(rect, list) or len(rect) != RECT_COORDINATES:
            raise DiagramError(f"{where}.rect must be [left, top, right, bottom] inclusive")
        left, top = self.point(rect[:2], f"{where}.rect start")
        right, bottom = self.point(rect[2:], f"{where}.rect end")
        if right - left + 1 < MIN_BOX_WIDTH or bottom - top + 1 < MIN_BOX_HEIGHT:
            raise DiagramError(f"{where}: box must be at least 7 columns x 3 rows")
        labels = wrap_label(text(node["name"], f"{where}.name"), right - left + 1)
        if "detail" in node:
            labels.extend(wrap_label(text(node["detail"], f"{where}.detail"), right - left + 1))
        if len(labels) > bottom - top - 1:
            raise DiagramError(f"{where}: text does not fit; enlarge the rectangle")
        for y in range(top, bottom + 1):
            for x in range(left, right + 1):
                char = " "
                if x in (left, right):
                    char = "+" if y in (top, bottom) else "|"
                elif y in (top, bottom):
                    char = "-"
                self.paint(x, y, char, where)
        for y, label in enumerate(labels, start=top + 1):
            for x, char in enumerate(label, start=left + 2):
                self.cells[x, y] = char
        self.rectangles[node_id] = left, top, right, bottom

    def port(self, node_id: str, p: tuple[int, int], neighbor: tuple[int, int]) -> None:
        left, top, right, bottom = self.rectangles[node_id]
        x, y = p
        nx, ny = neighbor
        if not (
            (x == left and top < y < bottom and nx < x and ny == y)
            or (x == right and top < y < bottom and nx > x and ny == y)
            or (y == top and left < x < right and ny < y and nx == x)
            or (y == bottom and left < x < right and ny > y and nx == x)
        ):
            raise DiagramError(f"edge must attach outward to a non-corner boundary of {node_id!r}")
        if p in self.used_ports:
            raise DiagramError("reused port would create an ambiguous junction")
        self.used_ports.add(p)
        self.cells[p] = "+"

    def path(self, value: object, where: str) -> list[tuple[int, int]]:
        if not isinstance(value, list) or len(value) < POINT_DIMENSIONS:
            raise DiagramError(f"{where}.points must contain at least two points")
        points = [self.point(p, f"{where}.points[{i}]") for i, p in enumerate(value)]
        path = [points[0]]
        for (ax, ay), (bx, by) in pairwise(points):
            if (ax == bx) == (ay == by):
                raise DiagramError(f"{where}: segments must be nonzero and orthogonal")
            dx, dy = (bx > ax) - (bx < ax), (by > ay) - (by < ay)
            path.extend(
                (ax + dx * n, ay + dy * n) for n in range(1, abs(bx - ax) + abs(by - ay) + 1)
            )
        if len(path) < MIN_PATH_CELLS or len(set(path)) != len(path):
            raise DiagramError(f"{where}: path needs arrow space and cannot retrace itself")
        if not (
            path[-3][0] == path[-2][0] == path[-1][0] or path[-3][1] == path[-2][1] == path[-1][1]
        ):
            raise DiagramError(f"{where}: reserve a straight approach for the arrowhead")
        return path

    def edge(self, value: object, where: str) -> None:
        required = {"from", "to", "points", "label", "label_at"}
        edge = keys(value, required, required | {"label_width"}, where)
        source = text(edge["from"], f"{where}.from")
        target = text(edge["to"], f"{where}.to")
        if source not in self.rectangles or target not in self.rectangles or source == target:
            raise DiagramError(f"{where}: endpoints must name distinct existing nodes")
        path = self.path(edge["points"], where)
        self.port(source, path[0], path[1])
        self.port(target, path[-1], path[-2])
        for i, (x, y) in enumerate(path[1:-1], start=1):
            px, py = path[i - 1]
            nx, ny = path[i + 1]
            if i == len(path) - 2:
                char = ">" if nx > x else "<" if nx < x else "v" if ny > y else "^"
            else:
                char = "-" if py == y == ny else "|" if px == x == nx else "+"
            self.paint(x, y, char, where)
        label = text(edge["label"], f"{where}.label")
        label_width = edge.get("label_width", len(label))
        if type(label_width) is not int or label_width < 1:
            raise DiagramError(f"{where}.label_width must be a positive integer")
        lx, ly = self.point(edge["label_at"], f"{where}.label_at")
        cells = set()
        for y, line in enumerate(wrap_label(label, label_width + 4), start=ly):
            for x, char in enumerate(line, start=lx):
                self.paint(x, y, char, f"{where}.label")
                if char != " ":
                    cells.add((x, y))
        self.paths.append(set(path[1:-1]))
        self.labels.append(cells)

    def check_labels(self) -> None:
        for index, cells in enumerate(self.labels):
            distances = [
                min(
                    (
                        abs(x - px) + abs(y - py),
                        0 if y < py and ((px - 1, py) in path or (px + 1, py) in path) else 1,
                    )
                    for x, y in cells
                    for px, py in path
                )
                for path in self.paths
            ]
            own = distances[index]
            if own[0] > MAX_LABEL_DISTANCE:
                raise DiagramError(
                    f"graph.edges[{index}]: label must be within 4 cells of its connector"
                )
            if any(distance <= own for i, distance in enumerate(distances) if i != index):
                raise DiagramError(
                    f"graph.edges[{index}]: label is ambiguous or nearer another connector"
                )

    def lines(self) -> list[str]:
        last_row = max(y for _, y in self.cells)
        return [
            "".join(self.cells.get((x, y), " ") for x in range(self.width)).rstrip()
            for y in range(last_row + 1)
        ]


def render_graph(spec: dict[str, object]) -> list[str]:
    grid = _GraphCanvas(spec["canvas"])
    nodes, edges = spec["nodes"], spec["edges"]
    if not isinstance(nodes, list) or not nodes:
        raise DiagramError("graph.nodes must contain at least one node")
    if not isinstance(edges, list):
        raise DiagramError("graph.edges must be an array")
    for index, node in enumerate(nodes):
        grid.node(node, f"graph.nodes[{index}]")
    for index, edge in enumerate(edges):
        grid.edge(edge, f"graph.edges[{index}]")
    grid.check_labels()
    return grid.lines()


def render_comparison(before: Flow, after: Flow) -> list[str]:
    width = width_for(before, after)
    edge_heights = [
        max(
            len(wrap_label(arrows[index], width))
            for _, arrows in (before, after)
            if index < len(arrows)
        )
        for index in range(max(len(before[1]), len(after[1])))
    ]
    node_heights = [
        max(1 + (nodes[index][1] is not None) for nodes, _ in (before, after) if index < len(nodes))
        for index in range(max(len(before[0]), len(after[0])))
    ]
    left = ["BEFORE", *render_flow(before, width, edge_heights, node_heights)]
    right = ["AFTER", *render_flow(after, width, edge_heights, node_heights)]
    return [
        (a.ljust(width) + LANE_GAP + b).rstrip() for a, b in zip_longest(left, right, fillvalue="")
    ]


def render(value: object) -> str:
    spec = keys(
        value,
        {"kind"},
        {
            "kind",
            "nodes",
            "arrows",
            "before",
            "after",
            "root",
            "annotations",
            "annotation_width",
            "routes",
            "canvas",
            "edges",
        },
        "diagram",
    )
    kind = text(spec["kind"], "diagram.kind")
    if kind == "flow":
        flow = flow_spec({key: val for key, val in spec.items() if key != "kind"}, "diagram")
        lines = render_flow(flow, width_for(flow))
    elif kind == "before_after":
        keys(spec, {"kind", "before", "after"}, {"kind", "before", "after"}, "diagram")
        if isinstance(spec["before"], dict) and "root" in spec["before"]:
            lines = render_tree_comparison(spec["before"], spec["after"])
        else:
            before = flow_spec(spec["before"], "diagram.before")
            after = flow_spec(spec["after"], "diagram.after")
            lines = render_comparison(before, after)
    elif kind == "tree":
        keys(spec, {"kind", "root"}, {"kind", "root", "annotations", "annotation_width"}, "diagram")
        lines = [
            line
            for _, line, _ in tree_column(
                {key: value for key, value in spec.items() if key != "kind"}
            )
        ]
    elif kind == "routes":
        keys(spec, {"kind", "routes"}, {"kind", "routes"}, "diagram")
        lines = render_routes(spec["routes"])
    elif kind == "graph":
        fields = {"kind", "canvas", "nodes", "edges"}
        keys(spec, fields, fields, "diagram")
        lines = render_graph(spec)
    else:
        raise DiagramError(f"unknown diagram kind: {kind!r}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", nargs="?", default="-", help="JSON path or - for stdin")
    args = parser.parse_args()
    try:
        if args.spec == "-":
            spec = json.load(sys.stdin)
        else:
            with Path(args.spec).open(encoding="utf-8") as file:
                spec = json.load(file)
        sys.stdout.write(render(spec))
    except (DiagramError, json.JSONDecodeError, OSError) as error:
        parser.exit(2, f"diagram: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
