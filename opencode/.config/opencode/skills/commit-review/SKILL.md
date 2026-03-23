---
name: commit-review
description: Review the changes introduced by one specific git commit and explain them with a one-line TL;DR, modified file summary, and readable per-change analysis including what changed, surrounding hunk context, motivation, and concise natural-language code explanation. Use when a user gives a commit SHA/ref and asks what the commit is doing.
---

# Commit Review

## Goal

Explain one commit accurately at file and hunk level, with clear and readable per-change context.

## Inputs

- Required: one commit reference (`<sha>`, `HEAD~1`, tag, or branch commit).
- Optional: scope hints (specific files/functions to focus on).

If no commit ref is provided, ask one short clarifying question.

## Workflow

1. Resolve and inspect the commit.
   - `git rev-parse --verify <commit>^{commit}`
   - `git show --no-patch --format=fuller <commit>`
   - `git show --name-status --format= <commit>`
   - `git show --find-renames --find-copies --patch --minimal <commit>`
2. Build a one-line intent statement.
   - Use commit subject/body plus the diff's dominant theme.
   - Keep it factual; do not speculate beyond evidence.
3. Summarize modified files.
   - List every changed file with status (`A`, `M`, `D`, `R`, etc.).
   - Give one concise purpose line per file.
4. Analyze each meaningful hunk.
   - State what changed in this hunk.
   - Explain surrounding code context around this hunk.
     - Use `git show <commit>^:<path>` and `git show <commit>:<path>` as needed.
   - If helpful, include where the changed symbols are used.
     - Use `rg -n "<symbol_or_key>"` only when it improves understanding.
   - Explain likely motivation in context of the full commit.
   - Explain the code in concise natural language.
   - Add a detailed walkthrough:
     - Describe exact control/data flow in this hunk (not line-by-line, but concrete).
     - Cover key conditions, transformations, and outputs.
     - Write it as bullets.
     - Start a new bullet whenever the next sentence introduces an unrelated idea.
     - Keep it concise (typically 2-6 bullets, one idea per bullet).
5. Keep accuracy high.
   - Mark uncertain statements as inference.
   - Do not invent hidden intent.
   - If context cannot be found, say so explicitly.
   - For very large commits, prioritize high-impact hunks and state what was sampled.

## Output format

Use this structure in order:

```markdown
TL;DR: <one line>

Modified files
- `<path>` (`<status>`): <what this file change is about>

Per-change analysis
1. `<path>` hunk `<hunk-id-or-lines>`
   **Change:**            <what changed>
   **Hunk context:**      <what nearby code does and how this hunk fits into that flow>
   **Motivation:**        <why this hunk exists in the full commit>
   **Plain-English code:** <concise natural-language explanation>
   **Detailed walkthrough:**
   - <first concrete behavior step>
   - <next unrelated behavior step on a new bullet>
   - <final output/effect of this hunk>
   ---
```

Formatting reference (fake example):

```markdown
1. `example/module.rs` hunk `@@ -40,7 +40,12 @@`
   **Change:**            Adds a feature flag check before request dispatch.
   **Hunk context:**      This sits inside the request handler right after request parsing.
   **Motivation:**        Avoids sending requests when the feature is disabled.
   **Plain-English code:** If the flag is off, return early; otherwise continue normal dispatch.
   **Detailed walkthrough:**
   - Reads `feature_flags.enable_dispatch` from config for the current request.
   - Returns early when the flag is false, so no outbound request is built.
   - Builds the outbound payload and dispatches it when the flag is true.
   ---
```

## Review quality bar

- Prefer precise, evidence-backed claims over broad summaries.
- Keep each hunk to 3-4 concise bullets.
- Avoid repeating the same idea across bullets.
- Prioritize nearby code context over wide call-site enumeration.
- Use bold labels and consistent visual spacing for `Change`, `Hunk context`, `Motivation`, and `Plain-English code`.
- Add a separator line (`---`) between numbered hunk sections for readability.
- Ensure walkthroughs are behaviorally accurate by grounding each claim in the actual hunk and nearby code.
- Keep walkthrough bullets atomic: one independent idea per bullet.
