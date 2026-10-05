---
name: code-diagram
description: Draw a concise, source-backed ASCII diagram of code, a subsystem, or a PR. Use for architecture/data-flow maps, "diagram this PR", or "summarize what changed in this PR" when a visual explanation is wanted.
---

# Code Diagram

Explain one coherent code mechanism with a readable, source-backed ASCII diagram. Use closed boxes and directed, labeled connectors for transfers; a tree for a real hierarchy; and aligned before/after views for a change. Do not default to Mermaid, images, or bracketed route lists.

## 1. Agree on the view

Establish purpose, format, scope, and detail level. Reuse decisions the user already supplied. Ask only about missing choices that materially affect the result. Propose source-informed scope instead of requiring unfamiliar file names. Use `ask_user_question` when available; use small script-rendered previews for visual choices. Otherwise ask briefly and stop.

Default to two stages:
1. Render a concise, source-backed draft with short component and relationship labels. Show it and wait for explicit scope/layout approval.
2. Preserve approved node identities, connections, and lane order while adding verified symbols and messages. If source inspection requires a material structural change, show a revised draft first.

Silence is not approval. A request for a draft gets only a draft. An explicit one-shot request may skip the checkpoint. Invoke the bundled renderer for every architecture diagram; copy its output unchanged. Never hand-space a replacement to bypass a layout error.

## 2. Establish source and scope

For a PR, obtain the actual head/base SHAs and changed-file list from metadata, with read-only network permission when needed. Do not infer the PR head from a merge title or today's checkout. If metadata is unavailable, ask for revisions. Read implementation/tests at those revisions, including unchanged relays or consumers needed to explain the outcome. Read PR intent without treating an existing drawing as implementation evidence. Source wins when prose or a reference diagram disagrees.

For an aggregate/stack PR, inspect the integrated commit range, not just its final commit. Verify ancestry and individual PR attribution before calling a stage "Built by #...". A PR tree can include future descendants. Mark those as future/context; a commit list is not an architecture diagram.

Write down the **changed mechanism, enabling input, and observable effect** before selecting layout. Include the principal consumer or consequence inside the diagram. Keep additional verified context only when it explains that story. Do not invent edges, corresponding stages, output values, or concrete topic examples.

| Purpose | Required explanation |
|---|---|
| Ownership/dependencies | True owner or direct dependency; for removal/movement, old and new boundaries plus any remaining direct dependency. Keep these links separate from runtime flow. |
| Calls/errors | Actual call sites and implementations. For errors, draw the return direction from failure through callers to the last verified handler. Do not infer logging/flushing on a failed step. |
| Messages | Producer, transport gateway, queue/translation bridge, consumer, and central outcome. Show separate request/response directions. A bridge does not itself speak the gateway's network protocol. |
| Setup/configuration | Input flag/config, gate, created resources/files, launched process, and meaningful false/default outcome. Distinguish a supplied path from the creator that writes its file and the process that reads it. |
| Migration | Replaced configuration/generation path, new path, and common destination. Cover each named mapping in the requested scope without repeating the unchanged runtime tail. |
| Scenarios/validators | Named stimulus, real message/state path, distinct checked outcomes, and any explicitly unimplemented/uncovered boundary. An assertion alone does not establish the intervening route. |
| Formatted output | Explain production of the output and include a representative verified data/tree row. Quote a fixture or derive punctuation/columns from the formatter; mark variable values illustrative. A source-output excerpt is not a new architecture drawing and may retain its native glyphs. |

For parallel computes or transports, keep distinct sender/gateway/queue paths separate until their actual shared owner. Group equivalent instances only with an explicit label such as "A/B, separate endpoints". Trace cross-compute publication and relay to the active consumer. Separate heartbeat state from command acceptance; receipt does not prove health or acceptance. Show concrete conflicting topics/inputs when they motivate the change, after checking historical configuration.

## 3. Review relationships before drawing

Inventory each central `(sender, relationship/message, receiver, outcome)` separately. Group messages only when receiver and outcome match. Read producer and consumer context, not merely matching declarations.

Run `python3 <SKILL_DIR>/review_edges.py` with the inventory JSON on stdin. For before/after views, check the BEFORE inventory at the base SHA and the AFTER inventory at the head SHA. Do not use current anchors to justify deleted old relationships.

Legal `kind` values: `call`, `message` (local data), `network`, `dependency`, `ownership`, `configuration`, `error`.

Classify actual network crossings independently: gRPC/QUIC requests and responses are `network`, not ordinary `message`. Supply `transport`, the actual `on_wire` envelope, and source anchors with both `send` and `receive` roles. A payload inside an envelope is not the envelope. Local bridge enqueue/drain edges remain local relationships.

```json
{"revision":"<full SHA>","edges":[{"sender":"Client","via":"SyncRequestBatch over QUIC","receiver":"Gateway","kind":"network","transport":"QUIC","on_wire":"SyncRequestBatch","proof":[{"path":"src/client.rs","needle":"encode(SyncRequestBatch)","role":"send"},{"path":"src/server.rs","needle":"decode(SyncRequestBatch)","role":"receive"}]}]}
```

Replace example names and needles with actual source. Needles are trimmed single-line printable ASCII, at least eight characters. The checker takes stdin, not a positional `-` argument. If a revision is unavailable locally, use `--github` only with permission, or inspect the sites manually and disclose that automated checking could not run.

A checker failure requires revisiting the edge, not changing its kind or anchor to evade a rule. It checks source-anchor presence and declared network evidence, **not architectural meaning**. It cannot discover an undeclared network crossing. Reconcile the inventory, source context, and drawing manually. Keep the inventory internal unless evidence details were requested.

## 4. Render

Resolve bundled scripts relative to this skill directory. Input is JSON through stdin or a JSON path; output is plain text. No file needs to be written.

```bash
python3 <SKILL_DIR>/render.py - <<'JSON'
{"kind":"flow","nodes":[{"name":"Producer","detail":"one responsibility"},{"name":"Consumer"}],"arrows":["MessageType on topic.name"]}
JSON
```

Read [layout.md](layout.md) for schemas and examples:
- `flow`: one linear transfer or error-return path.
- `graph`: branches, parallel lanes, shared owners, and separate request/response connectors. Explicit IDs, rectangles, ports, and orthogonal routes.
- `tree`: hierarchy with optional node-ID-aligned annotations.
- `before_after`: two flows, or two trees aligned by verified common node IDs. Flow stages align by position; use trees or separate figures when stages do not correspond.
- `routes`: independent boxed linear paths only. Mark repeated owners as the same instance; prefer `graph` for a real shared boundary.

Use concise component labels and one responsibility per box. Put actual relationships/messages beside important arrows. Preserve full concrete topics; wrap at spaces or `.` boundaries, never `_`. If a long symbol overwhelms a box, use a nearby unambiguous symbol legend. Short message keys require an immediate legend identifying the exact envelope/topic; do not replace important concrete conflicts with generic aliases. Keep keys consistent across figures.

Prefer top-to-bottom for long names and left-to-right for short pipelines. Put labels close to their own connectors. Prefer labels above horizontal arrows. The graph renderer rejects collisions, false junctions, detached labels, and unresolved label ambiguity. Correct the specification rather than editing output. Nested ownership boxes are not supported; use an ownership tree or explicit ownership links instead of pretending a containing boundary exists.

Aim for 25–35 rows and at most about 100 columns. Above roughly 45 rows, shorten optional detail, draw a shared tail once, or split named figures without dropping central edges. Trees and comparisons have a 120-column hard limit. Do not invent nodes just to align views.

## 5. Check and deliver

- Follow every connector from sender to arrowhead and actual receiver. Check gateway/bridge handoffs, response direction, distinct queues, gates, and cross-compute consumers.
- Check the changed mechanism and outcome are visible inside the diagram. Reconcile all central inventory edges and requested mappings; remove unsupported connections and low-value repetition.
- For comparisons, verify old/new source revisions and common-node correspondence. For aggregates, check included stages without misattributing future PRs.
- Deliver unchanged renderer output in fenced `text`, a one-sentence takeaway, and important source paths/revisions. State material uncertainty or omitted scope. Label drafts and ask for approval; do not call an unapproved draft final.
- If prompt history is requested, save actual prompts, user feedback, drafts, renderer inputs, final output, revisions, and validation results. Separate supplied instructions from generated content.

## Evaluation

Use the complete agreed PR-description corpus for reference review, not only the latest showcase. Record inclusion/exclusion for every description. Freeze source-informed task prompts, revisions, skill, renderer, and harness. Appropriate per-PR purpose/format/scope prompts are allowed; report guided quality separately from ambiguous-prompt robustness.

Fresh generation must receive no PR descriptions, reference diagrams, READMEs, prior answers, or evaluation artifacts. Use comment-filtered implementation/test views so embedded architecture drawings do not leak through source comments. Audit both prompt inputs and all attempted tool accesses; surviving files or clean fetch traces alone are insufficient. If a reference drawing was exposed, do not call that run diagram-blind.

For staged tests, capture actual approval rather than fabricating feedback. For explicitly one-shot tests, skip the checkpoint. Save specifications and reproduce every displayed diagram exactly. After generation, reveal references and score requested form, geometry, source accuracy, scope coverage, and readability separately. Accept useful verified additions and document stale-reference conflicts. Local tests prove renderer/checker behavior, not FlightSystems runtime correctness or model robustness.
