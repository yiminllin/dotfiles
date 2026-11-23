# PR Human Review Guide Output Templates

Follow `../SKILL.md` for review procedure, labels, permissions, and persistent updates. Return raw Markdown or JSON without an outer fence.

## Shared contract

Use the six sections below. Through `../../code-explainer/SKILL.md`, follow the snippet and diagram procedures; preserve renderer output unchanged. Show one explicit before/after comparison at the same abstraction level, with source references for each revision. A companion view may be labeled after-only. Disclose missing evidence instead of inventing a side.

Use two passes: whole-PR understanding first, then granular review of each chunk in the same top-down order. In Diffview, put the numbered rendered overview in the existing top-level `diagram` field. Each `[n]` maps to the nth entry in `chunks`; use the existing stable chunk IDs for navigation and references. Show exact source names and types. Do not use a numbered text list instead of the overview. Give the whole-PR route as a short numbered list; start every second-pass chunk with a one-sentence purpose/change summary. Place relevant proposed comments inside that chunk, next to its source checks, not in a detached end-of-guide list. Include all changed files and all substantive review items, without a count cap. Separate findings from questions and validation gaps; state when no evidence-backed findings were established. Proposed comments need author-facing wording, evidence, impact or reason for asking, and uncertainty.

## Markdown skeleton

````markdown
## Goal
<one high-level sentence: problem and intended outcome>

## Behavior change
- Before (`<base SHA>`): <old behavior>
- After (`<head SHA>`): <same path, new behavior>
- Key difference: <observable consequence>

## PR flow
```text
<source-backed BEFORE / AFTER diagram, or labeled AFTER ONLY companion>
```
Sources: <paths/symbols and revisions; identify unchanged context>

## Core code
**Core pseudocode — Before (`<base SHA>`)**
```text
<old mechanism>
```
**Core pseudocode — After (`<head SHA>`)**
```text
<same mechanism and abstraction level; expose the difference>
```
Sources: <actual symbols and verified path:line ranges for each side, with revisions; place beside each block>

## Review route
### 🧭 Pass 1 — Whole PR
<check intent, end-to-end behavior, boundaries, and cross-cutting risks>
1. <chunk name> — <short role and connection to the next chunk>
<continue in recommended order>

### 🔬 Pass 2 — Chunk 1: <name matching pass 1>
<one-sentence summary of this chunk's purpose/change>
- **Source** — `path:line-range` / `actual_symbol` (revision, LEFT/RIGHT) [🔎 read carefully]
  - Verify: <specific behavior or invariant>
- **💬 Suggested review comments — Findings**
  - **<severity> — Finding** — `path:lines` (LEFT/RIGHT)
    - Proposed comment: "<concern; requested change/evidence where appropriate>"
    - Evidence / why: <trigger, impact, source support, and uncertainty>
- **💬 Suggested review comments — Open questions / validation gaps**
  - <same anchored comment format, labeled Question or Verification gap>
<repeat chunks through wiring, core behavior, effects/errors, tests, and supporting details; do not invent comments for empty chunks>

## Review focus
<cross-cutting items only; do not repeat chunk comments. State explicitly if no evidence-backed findings were established.>

### Validation / coverage
- Review depth: <deeply inspected versus mapped/skimmed; remaining scope>
- Observed checks: <actually run and results; distinguish inspected tests and PR claims>
- Gaps / internal follow-ups: <missing evidence or validation>
- Comment status: <draft only; nothing posted>

### Context
- Boundary: <exact comparison and mode>
- Base/head: <exact SHAs>
- PR: <number/title/URL, if supplied or verified>
````

Use `Source excerpt` or `Simplified code` labels when appropriate. If the diagram provides the paired comparison, one labeled after-only code block is sufficient.

## JSON skeleton

```json
{
  "context": {
    "diff_boundary": "exact inspected boundary",
    "base_oid": "exact comparison-base SHA",
    "head_oid": "exact head SHA",
    "pr_number": null,
    "title": null,
    "url": null
  },
  "summary": "problem and intended outcome",
  "behavior_change": {"before": "old behavior", "after": "new behavior and consequence"},
  "diagram": ["unchanged rendered overview with [1], [2], ... matching chunks in order"],
  "core_code": [
    {
      "label": "Core pseudocode",
      "id": "core-before",
      "title": "Before: mechanism at base SHA",
      "code": ["old mechanism"],
      "sources": [{"path": "path/from/source", "side": "LEFT", "line": 10, "end_line": 12, "revision": "exact base_oid"}]
    },
    {
      "label": "Core pseudocode",
      "id": "core-after",
      "title": "After: same mechanism at head SHA",
      "code": ["same abstraction level; expose the difference"],
      "sources": [{"path": "path/from/source", "side": "RIGHT", "line": 15, "end_line": 17, "revision": "exact head_oid"}]
    }
  ],
  "chunks": [
    {
      "id": "configuration-boundary",
      "title": "Configuration boundary",
      "summary": "Purpose and behavior change for this small review unit.",
      "relationship": "Consumes scenario inputs; supplies the runtime chunk.",
      "depends_on": [],
      "depth": "careful",
      "diagram": ["actual_entry -> [actual_config] -> actual_runtime"],
      "core_code": [
        {
          "id": "config-core",
          "label": "Core pseudocode",
          "title": "actual_symbol — comparable before/after",
          "code": ["before: old mechanism", "after: changed mechanism"],
          "sources": [
            {"path": "source/path", "side": "LEFT", "line": 10, "revision": "exact base_oid"},
            {"path": "source/path", "side": "RIGHT", "line": 15, "revision": "exact head_oid"}
          ]
        }
      ],
      "checks": ["Check that a missing input stops the worker before it starts the job."],
      "hunks": ["<copy exact ID from review-hunks.json>"]
    }
  ],
  "files": [
    {
      "path": "path/from/diff",
      "stage": "1. Entry point",
      "reason": "Chunk summary: purpose and change. actual_symbol — why here; what to verify [🔎 read carefully]",
      "suggestions": [
        {
          "id": "stable-observation-id",
          "severity": "Medium",
          "side": "RIGHT",
          "line": 10,
          "end_line": 12,
          "body": "Finding: proposed author-facing comment",
          "why": "source evidence, impact, and uncertainty"
        }
      ]
    }
  ],
  "high_risk": ["cross-cutting item with anchor and uncertainty"],
  "validation": {
    "review_scope": "deeply inspected versus mapped/skimmed; state if no findings established",
    "observed": ["checks actually run and results"],
    "gaps": ["missing evidence or uncovered scope"]
  }
}
```

For persistent Diffview reviews, read the host-owned `review-hunks.json` beside the guide. Check its pinned context. `chunks` defines the review route: partition every inventory hunk ID into exactly one nonempty semantic chunk, including the inventory's file-level units for renames, binary/mode changes, submodules, and empty files. Attributes accompanying code appear with the first hunk. Copy IDs exactly; do not invent IDs, truncate the partition, or edit the inventory. If it is unavailable, report that rather than fabricate a plan. Group by behavior and dependencies, not file size or line count. A chunk may span files, and different hunks in one file may belong to different chunks. `depends_on` names earlier chunk IDs. Preserve IDs across refinement. Give each chunk its purpose/change, relationship to the whole-PR diagram, local diagram/core code with actual symbols and pinned anchors, checks, and `depth` (`careful` or `skim`). These are slices of the original base/head, not intermediate commits or independently buildable PRs.

Keep one `files` entry per changed path for file metadata and anchored suggestions. Its `reason` describes the file's role; `stage` remains a legacy fallback, not chunk ownership. Unchanged entry points belong in diagram/code references, not the changed-file list. Preserve the whole-PR overview at the top level; granular explanations belong in `chunks`. Neovim validates coverage, displays focused native hunks, and owns per-hunk read progress.

Keep file-specific comments in `suggestions`; prefix `body` with `Finding:`, `Question:`, or `Verification gap:`. Use `why` for supporting evidence. Keep one or two short, concrete reading cues in each section's `checks`. Phrase each cue as an observable behavior or question. Place important cross-cutting concerns in the most relevant section, not only in `high_risk`. Keep audit details in `validation`; the viewer does not display either top-level audit field. Empty lists are valid. `end_line` and `why` are optional; use `null` for approximate lines. Anchor LEFT to `base_oid` and RIGHT to `head_oid`; preserve stable suggestion IDs.

Keep core-code `id` values stable across refinements. Put actual source symbol names in code and block titles; do not replace them with conceptual aliases alone. Use repository-relative source paths, verified numeric ranges, and the exact pinned revision. Sources may reference unchanged context files. Do not invent approximate source targets; leave unverified references as plain strings.

## Viewer compatibility

Guide starts with a short plain-English PR summary, followed by the before/after explanation, source-backed diagram, core code, and section list. Each active section starts with its purpose and `checks` (“What to look for”), followed by code, hunks, and anchored discussions. The viewer does not show a bottom-of-guide audit appendix. The JSON schema still uses `chunks` for semantic sections; preserve its keys and IDs.

`O` collapses overview details while keeping the section list visible. Enter on a section opens its guide beside the focused diff. `Tab` inside the panel switches Guide/Threads; `z` expands it. Threads holds full discussion histories and local actions. GitHub discussion import is read-only; publishing is removed. Native source buffers keep pinned line numbers; unrelated regions are folded, not replaced with intermediate revisions. In code, Tab/Shift-Tab follows hunks across sections, ]r/[r changes sections, and gdv toggles a hunk read. In Guide, v on a section row or V for the selected/active section toggles all its hunks; progress survives regrouping. All changed files restores the full Diffview. There is no separate skim viewer or whole-file progress control. Existing guides, comments, and saved file flags remain readable; legacy guides need regeneration for a validated section plan.

Guide `r` generates/updates and `u` requests refinement in the main Pi session. Enter/`o` opens verified source references or route files. Updates mark changed content and preserve reading positions. Existing string references remain readable; only unambiguous pinned anchors are navigable. These explicit queued model turns are not comment workers. Explain changes and uncertainty in the visible main session. Update the same JSON atomically; do not create a second Markdown artifact. Raw artifact requests still return only the artifact.
