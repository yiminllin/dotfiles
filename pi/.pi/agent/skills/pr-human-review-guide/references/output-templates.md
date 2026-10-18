# PR Human Review Guide Output Templates

Follow `../SKILL.md` for review procedure, labels, permissions, and persistent updates. Return raw Markdown or JSON without an outer fence.

## Shared contract

Use the six sections below. Through `../../code-explainer/SKILL.md`, follow the snippet and diagram procedures; preserve renderer output unchanged. Show one explicit before/after comparison at the same abstraction level, with source references for each revision. A companion view may be labeled after-only. Disclose missing evidence instead of inventing a side.

Keep the overview concise and the route top-down. Include all changed files and all substantive review items, without a count cap. Separate findings from questions and validation gaps; state when no evidence-backed findings were established. Proposed comments need author-facing wording, evidence, impact or reason for asking, and uncertainty.

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
Sources: <paths/symbols, lines, and revisions>

## Review route
1. **Entry point** — `path` / `symbol` [read carefully]
   - Why here: <role and connection to the next stage>
   - Verify: <specific behavior or invariant>
<continue through wiring, core behavior, effects/errors, tests, and supporting details>

## Review focus
### Suggested review comments — Findings
<group by route stage/file; state explicitly if none were established>

### Suggested review comments — Open questions / validation gaps
<same grouping and comment format>

Comment format:
- **<severity/category> — <Finding/Question/Verification gap>** — `path:lines` (LEFT/RIGHT)
  - Proposed comment: "<concern or question; requested change/evidence where appropriate>"
  - Evidence / why: <trigger, impact, source support, and uncertainty>

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
  "diagram": ["unchanged renderer output; label BEFORE / AFTER or AFTER ONLY"],
  "core_code": [
    {
      "label": "Core pseudocode",
      "title": "Before: mechanism at base SHA",
      "code": ["old mechanism"],
      "sources": ["path:symbol:lines at base SHA"]
    },
    {
      "label": "Core pseudocode",
      "title": "After: same mechanism at head SHA",
      "code": ["same abstraction level; expose the difference"],
      "sources": ["path:symbol:lines at head SHA"]
    }
  ],
  "files": [
    {
      "path": "path/from/diff",
      "stage": "Entry point",
      "reason": "symbol — why here; what to verify [read carefully]",
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

Order `files` by the review route. Include stage, symbol, what to verify, and depth in `reason` for older viewers. Unchanged entry points belong in diagram/code references, not the changed-file list.

Keep file-specific comments in `suggestions`; prefix `body` with `Finding:`, `Question:`, or `Verification gap:`. Use `why` for supporting evidence. Reserve `high_risk` for cross-cutting items without duplicating comments; internal follow-ups belong in `validation.gaps`. Empty lists are valid. `end_line` and `why` are optional; use `null` for approximate lines. Anchor LEFT to `base_oid` and RIGHT to `head_oid`; preserve stable suggestion IDs.

## Viewer compatibility

The current popup shows `summary`, `diagram`, ordered files/reasons, and only the first three `high_risk` items. Suggestions use the review-comment integration. It does not display `behavior_change`, `core_code`, `stage`, or `validation`. Store the full guide anyway; in persistent sessions, explain hidden content and remaining risks in visible Pi conversation. Do not claim full popup support or create a second Markdown artifact. Raw artifact requests still return only the artifact.
