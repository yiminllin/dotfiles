# PR Human Review Guide Output Templates

Use only after `SKILL.md` routes a request into private local-review mode. Return raw artifact content without a fenced wrapper.

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
- Supplied PR metadata: <number/title/URL, only if provided>
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
  "schema_version": 1,
  "context": {
    "diff_boundary": "base...head",
    "pr_number": null,
    "title": null,
    "url": null
  },
  "summary": "concise review summary",
  "change_map": ["optional short ASCII relationship line"],
  "high_risk": ["risk or unknown"],
  "validation_focus": ["check or gap"],
  "review_strategy": ["ordered review step"],
  "files": [
    {
      "path": "path/from/diff",
      "depth": "read carefully",
      "notes": ["file-level guide note"],
      "suggestions": [
        {
          "severity": "Medium",
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

Order `files` by recommended review order. `change_map`, `review_strategy`, `depth`, `end_line`, and `why` are optional. Use exact paths and `null` for approximate lines. Keep diagrams ASCII-only and concise.
