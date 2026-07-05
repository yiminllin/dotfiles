# PR Human Review Guide Output Templates

Use this reference only after `SKILL.md` has routed the request into private/local human-review-guide mode. These are expanded templates and examples, not permission to post public GitHub comments or PR descriptions.

## Markdown guide skeleton

Use this Diffview/prdv-friendly structure directly as the final response for raw Markdown guide output. Do not wrap the response in a fenced code block.

`read carefully` may be replaced with `deep` when the user requested deep/skim labels.

```markdown
## TL;DR
- <main review route and highest-risk unknowns>
- <most important validation or follow-up focus>

## High-level summary
<plain-language summary of the conceptual layers changed, such as public API/config, routing/wiring, core behavior, validation, and generated/mechanical churn.>

## Review goal
<optional; include only when a specific reviewer or author self-review goal helps focus the pass>

## PR context
- PR: #<number> — <title>
- URL: <url>
- Base/head: `<base>` ← `<head>`
- Intent: <one-paragraph summary>
- Main risk: <blocker/non-blocker judgment and primary risk>
- Validation focus: <short list>

## Recommended inspection order
1. `path/to/file.rs` — <why read first> [read carefully]
2. `path/to/next_file.rs` — <why next> [skim]

## File map
| Area | Files / globs | Review focus |
| ---- | ------------- | ------------ |
| <area> | `path/to/file.rs` or `path/to/**/*.rs` | <what this area owns> |

## File-by-file Diffview guide
Only expand high-signal files here; leave routine/low-risk files summarized in the file map.

### 1. `path/to/file.rs` [read carefully]
**What this diff does**
- <plain-language explanation of the file's diff>

**Inspect in Diffview**
- <specific behavior, edge case, or API/layering point to verify while viewing this file>

**Suggested local comments/questions**
- **Medium** — `path/to/file.rs:10-20`: <suggested local Diffview comment/question>
  - Why it matters: <risk/context>
  - TODO: <optional local follow-up before posting/submitting review>

## Files covered by map only
- `<area/glob>` — <why no detailed section is needed, for example mechanical/generated/docs-only or low-risk follow-through>

## Questions
| Category | Anchor | Question | Why it matters |
| -------- | ------ | -------- | -------------- |
| Clarification | `path/a.rs` | <question> | <impact on review/intent> |
| Curiosity | `path/a.rs`, `path/b.rs` | <question> | <design context> |
| Follow-up | `path/c.rs` | <question> | <non-blocking next step> |
| Verification gap | `path/test.rs` | <question> | <coverage confidence> |
| Blocker | `path/d.rs:10` | <question> | <correctness/safety concern> |

## Validation / coverage notes
- <tests observed>
- <gaps or follow-up validation>

## Public PR body suggestions
<optional/private; include only when useful. Suggestions may identify public-body improvements, but do not edit the PR body or present this private inspection guide as public text.>
```

## Structured JSON guide artifact

When `prdv` or the user explicitly requests a JSON guide artifact, return raw JSON only: no preface, no Markdown, no save-status prose, and no fenced code block.

Order `files` as the recommended human/Diffview review order. Future Diffview `<Tab>`/`<S-Tab>` navigation may use this order, so do not sort alphabetically unless alphabetical is actually the recommended review order.

```json
{
  "schema_version": 1,
  "pr": {
    "number": 123,
    "title": "PR title",
    "url": "https://github.com/org/repo/pull/123",
    "base": "main",
    "head": "feature-branch"
  },
  "summary": "one concise PR-level review summary",
  "change_map": ["optional concise ASCII/plain-text relationship map line"],
  "high_risk": ["highest-risk areas or unknowns"],
  "validation_focus": ["tests/checks or manual validation to focus on"],
  "review_strategy": ["optional review step or ordered route"],
  "files": [
    {
      "path": "path/from/diff",
      "depth": "read carefully",
      "notes": ["file-level guide note for Diffview overlay"],
      "suggestions": [
        {
          "severity": "Medium",
          "line": 10,
          "end_line": 12,
          "body": "suggested local review comment or question",
          "why": "why it matters"
        }
      ]
    }
  ]
}
```

Use exact Diffview file paths. `change_map` is optional; include it only when a concise relationship figure, dataflow, or ownership map helps orient the reviewer. It must be an array of short ASCII/plain-text strings only, with no Mermaid/images, ideally no more than 8-12 lines. `review_strategy` is optional and may be a string or array. `depth`, `end_line`, and `why` are optional. Do not invent exact line numbers; use `null` for approximate anchors. Prefer a short high-signal set of file notes and suggestions over exhaustive coverage.

Guide JSON artifacts do not carry local review replies. Local Diffview overlay/state replies belong only in `diffview-review.json` under the matching parent comment:

```json
{
  "comments": [
    {
      "file": "path/from/diff",
      "line": 10,
      "body": "parent comment",
      "replies": [
        {
          "author": "opencode",
          "body": "concise local reply",
          "created_at": "2026-07-05T00:00:00Z",
          "updated_at": "2026-07-05T00:00:00Z"
        }
      ]
    }
  ]
}
```

`replies` is optional and backward-compatible; omit `updated_at` unless editing an existing local reply. Match parent comments by stable fields (`github_id`, `guide_id`, then file/line/body preview), preserve existing comments and fields, ask if ambiguous, and do not mutate GitHub/external state.

## Good default tone examples

Use concise, evidence-backed, reviewer-friendly wording:

- `Low — path:line-line: Is this intentionally scenario-global rather than per-domain?`
- `Medium — path:line-line: I would expect coverage for <case> because this is the main new behavior.`
- `Curiosity — path:line-line: Longer term, do you expect this to move into <layer>, or is this meant to stay local?`

Avoid:

- vague comments without anchors
- broad redesign requests without evidence
- pretending machine review is authoritative
- style nits that distract from correctness or review order
- generic PR-review prose that is not actionable while stepping through Diffview files
