# Explicit box layout

Use `render.py` with `kind: "graph"` for a branching box diagram or two-way flow. Supply the verified relationships first, then specify their geometry. The renderer does not discover relationships or choose a layout.

## Specification

```json
{
  "kind": "graph",
  "canvas": [45, 9],
  "nodes": [
    {"id": "client", "name": "Client", "detail": "writer", "rect": [0, 0, 12, 4]},
    {"id": "server", "name": "Server", "detail": "reader", "rect": [30, 0, 42, 4]}
  ],
  "edges": [
    {"from": "client", "to": "server", "points": [[12, 1], [30, 1]], "label": "Request", "label_at": [16, 0]},
    {"from": "server", "to": "client", "points": [[30, 3], [12, 3]], "label": "Response", "label_at": [16, 4]}
  ]
}
```

```text
+-----------+   Request       +-----------+
| Client    +---------------->+ Server    |
| writer    |                 | reader    |
|           +<----------------+           |
+-----------+   Response      +-----------+
```

- Coordinates are zero-based character columns and rows, not pixels.
- `canvas` is `[width, height]`, at most 120 columns and 100 rows. Prefer at most 100 columns.
- Each node has a unique `id`, a `name`, an optional `detail`, and inclusive `rect: [left, top, right, bottom]` coordinates. Reserve enough interior rows for its wrapped text.
- Every edge names existing `from` and `to` IDs. Its `points` start on the source perimeter and end on the destination perimeter. Intermediate points describe orthogonal bends. Segments must move horizontally or vertically, not diagonally.
- Endpoints must attach outward to non-corner boundary cells. A port becomes `+`; the arrowhead sits immediately outside the destination. Reserve at least two cells outside the destination for a straight approach.
- Each edge has one `label` and a `label_at: [x, y]` position. Optional `label_width` wraps at spaces or `.` boundaries, never `_`. Identifier segments are not truncated. The nearest visible label character must be within four grid cells of its connector (horizontal plus vertical distance), and closest to that connector. Equal-distance placement prefers a label above a horizontal connector; any remaining tie is rejected. Prefer labels immediately above horizontal arrows. Leave blank rows for wrapping.
- Request and response arrows are separate edges with separate ports and labels. Do not use an unlabeled bidirectional line to hide different messages.
- The renderer rejects overlapping boxes, paths through boxes, intersecting/retraced paths, reused ports, and labels that collide or leave the canvas. It will not guess a junction or repair a route. Use separate ports on the actual shared owner for fan-in/fan-out. Split into separate figures if routes cannot fit clearly.

## Trees and annotated columns

```json
{"kind":"tree","root":{"id":"owner","name":"Owner","children":[{"id":"transport","name":"Transport","via":"owns"},{"id":"adapter","name":"Adapter","via":"owns"}]},"annotations":{"transport":"Separate request/response queues","adapter":"Publishes to the World graph"},"annotation_width":32}
```

Nodes accept optional unique `id`, required `name`, optional `via`, and optional `children`. Put annotations in a separate map keyed by existing node IDs, not padded into node names. The renderer lays out the tree, records node rows, wraps the annotation column, then joins the columns using those IDs. Annotation wrapping preserves branch stems. Default `annotation_width` is 32. The complete output must fit within 120 columns; shorten optional detail or use a symbol legend if an intact identifier cannot fit.

## Before/after trees

```json
{"kind":"before_after","before":{"root":{"id":"owner","name":"Owner","children":[{"id":"removed","name":"Old dependency"},{"id":"transport","name":"Transport"}]}},"after":{"root":{"id":"owner","name":"Owner","children":[{"id":"transport","name":"Transport"}]}}}
```

Each side uses the tree schema above, without `kind`, including optional annotations. Corresponding IDs align even when another stage is inserted or removed. Supply the same ID only for verified corresponding entities/roles; different owners must not acquire the same ID merely to force alignment. Shared IDs must retain traversal order. Otherwise use separate figures. Padding carries the waiting branch's stem instead of inventing a node. Old and new evidence must be checked at their respective revisions.

The existing `before_after` flow schema remains supported: each side supplies `nodes` and `arrows`. Flow rows align by stage position, not node identity. Do not imply correspondence between unrelated stages.

## Templates

- **Box flow:** Use the graph example above for a left-to-right workflow. Use `flow` for a simple vertical sequence when width is limited. Keep actions or owners in boxes and payloads on arrows. Route branches into a shared downstream stage instead of repeating it.
- **Before/after boxes:** Use `{"kind":"before_after","before":{...},"after":{...}}` with graph fields (`canvas`, `nodes`, `edges`) on each side. It renders two stacked panels in one block. Put matched stages on the same columns and relative rows in both specs. Use optional `before_label` and `after_label` for scope labels. Preserve the distinction between stage identity and its displayed name.
- **Numbered overview:** Use the graph schema. Prefix the relevant node name or arrow label with `[1]`, `[2]`, etc. Reserve space for each callout in the layout. Reuse those IDs in the detail headings. Label the changed handoff, not an unrelated box.
- **Tree:** Use the tree templates above for ownership, dependencies, and symbol moves. In a comparison, leave unmatched entries opposite blank rows or branch stems, not unrelated symbols.

For a delta comparison, set `"changed": true` on graph or flow nodes with verified changes (including additions and removals on the side where they exist). The renderer paints only their horizontal borders with equals signs. For a changed transfer between unchanged owners, mark its label (e.g. `[changed] JobBundle`); keep the connector and box borders unchanged. Omit changed flags for neutral architecture views. Compare source evidence, not display strings, when deciding which elements changed.

At the selected detail level, use plain roles, exact symbols and types, or a mix. Keep exact types intact; when one would make the layout too wide, use a short verified label and a nearby symbol key. Preserve stable layout when revising an approved diagram.

Always invoke the renderer on JSON through stdin and copy its output unchanged into a fenced `text` block. A rejected layout requires correcting the specification, not hand-editing the diagram.
