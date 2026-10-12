# PR Human Review Guide Output Templates

Use only after `SKILL.md` routes a request into private review mode, using the resolved local or approved live PR boundary. Return raw artifact content without a fenced wrapper.

## Markdown skeleton

```markdown
## TL;DR
- <review route and highest-risk unknown>
- <validation focus>

## High-level summary
<conceptual layers changed>

## Review goal
<optional focused goal>

## Context
- Diff boundary: `<base>...<head>`
- PR metadata: <number/title/URL and head SHA, if verified or supplied>
- Intent: <summary>
- Main risk: <risk>
- Validation focus: <focus>

## Recommended inspection order
1. `path/to/file` — <why first> [read carefully]

## File map
| Area | Files / globs | Review focus |
| ---- | ------------- | ------------ |
| <area> | `path/**` | <focus> |

## File-by-file Diffview guide
### 1. `path/to/file` [read carefully]
**What this diff does**
- <explanation>

**Inspect in Diffview**
- <specific behavior or edge case>

**Suggested local comments/questions**
- **Medium** — `path/to/file:10-20`: <wording>
  - Why it matters: <risk/context>

## Files covered by map only
- `path/**` — <why no detailed section is needed>

## Questions
| Category | Anchor | Question | Why it matters |
| -------- | ------ | -------- | -------------- |
| Verification gap | `path/test` | <question> | <impact> |

## Validation / coverage notes
- <observed checks and gaps>
```

## Structured JSON skeleton

```json
{
  "context": {
    "diff_boundary": "base...head",
    "base_oid": "exact comparison-base SHA when used by Diffview",
    "head_oid": "exact head SHA when used by Diffview",
    "pr_number": null,
    "title": null,
    "url": null
  },
  "summary": "one-sentence takeaway",
  "diagram": ["source-backed ASCII diagram: copy renderer output unchanged"],
  "high_risk": ["at most three important risks or questions"],
  "files": [
    {
      "path": "path/from/diff",
      "reason": "short reason to inspect this file here",
      "suggestions": [
        {
          "id": "stable-observation-id",
          "severity": "Medium",
          "side": "RIGHT",
          "line": 10,
          "end_line": 12,
          "body": "suggested local comment or question",
          "why": "why it matters"
        }
      ]
    }
  ]
}
```

For Diffview artifacts, record the exact comparison base and head SHA in `context.base_oid` and `context.head_oid`. Anchor LEFT suggestions to the comparison base and RIGHT suggestions to the head. Use stable suggestion IDs so refreshed guidance preserves local resolutions. Write one JSON artifact atomically; a separate Markdown artifact is not required.

For diagram-first Diffview requests, load `code-diagram` and its layout instructions. Use its source evidence checks and bundled renderer; preserve every output line, including indentation and blank lines, in `diagram`. Explicitly requested one-shot guide generation does not require a separate layout approval. Aim for one coherent flow within 25 rows and 100 columns. Include the enabling input, changed mechanism, and observable consequence; keep verified unchanged dependencies when they explain the PR. Never invent connections.

Order `files` by recommended review order and give each one a short `reason`. Include all changed files, even when Diffview is filtered to Phoenix ownership. Keep the takeaway to one sentence and risks/questions to at most three. Suggestions should be sparse or empty; detailed conversations belong in review threads. `end_line` and `why` are optional. Use exact paths and `null` for approximate lines.

For a persistent Diffview assistant, generate or refresh the guide only when missing, invalid, stale, lacking a diagram, or explicitly requested. Otherwise reuse it. Do not generate a separate Markdown guide. Explain activity and findings in the visible Pi conversation. When discussion changes understanding or inspection order, update the same guide atomically; do not rewrite it for every reply. Keep revision stamps and still-relevant suggestion IDs. Do not edit Diffview comment state, reviewed-file progress, or ownership filters.
