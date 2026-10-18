---
name: core-code-extractor
description: Explain a code change or mechanism through minimal representative code, simplified interfaces, or before/after pseudocode. Use for "show the core code", "summarize this large diff with a snippet", "explain by example", or extracting the essential algorithm, API, type, or state transition. Not for modifying or moving source code.
---

# Core Code Extractor

Make the concept understandable without reading the whole implementation. Extract the smallest faithful code example, not a collection of interesting changed lines. Diff size does not determine explanation length.

## When to use

Use for implementation-backed explanations of an algorithm, abstraction, API, configuration boundary, or behavior change. Accept a symbol, file, behavior, PR, or verified source scope from `code-explainer`; direct invocation is also supported.

Do not edit application code, perform a full code review, or substitute snippets for architecture. For infrastructure, ownership, dependencies, or message routing, use `../code-diagram/SKILL.md` when that view adds information. `code-explainer` coordinates combined explanations; do not route back to it recursively.

## Procedure

1. Establish the question and source revision. For a PR, verify head/base and the changed-file list; read the relevant implementation at those revisions. Obtain permission before network/auth operations. Do not treat PR prose or prior explanations as implementation evidence.
2. State the problem, core mechanism, and observable result in one sentence internally. Read enough caller and consumer context to identify where the behavior actually occurs. Include unchanged code when it explains the effect.
3. Choose the smallest useful code view:
   - Exact excerpt for a compact, self-contained implementation.
   - Simplified interfaces/types for an abstraction or dependency boundary.
   - Core pseudocode for an algorithm, state transition, or multi-file mechanism.
   - Before/after snippets when the contrast explains the change; verify each side separately.
4. Remove boilerplate, repetition, and incidental plumbing. Retain actual source identifiers, including function/type/field names and actual old/new names in comparisons. Simplify syntax; use `...` for omitted arguments. Label any invented helper or shorthand at first use as not a source symbol. Preserve behavior-changing conditions, defaults, order, ownership/copy boundaries, error propagation, and the consequential output.
5. Check the example against source. Follow representative input through the snippet and actual implementation. Check relevant branches, failure paths, and any claimed preserved behavior. Read tests when they clarify semantics; do not imply that reading a test means running it.
6. Deliver the example with a short takeaway and precise source references. Mention meaningful omissions or uncertainty. If the source does not establish a mechanism, say so rather than inventing executable-looking implementation.

## Output

- Start with the direct answer or conceptual change, not a file inventory.
- Label every block **Source excerpt**, **Simplified code**, or **Core pseudocode**. Only verbatim code may be called an excerpt. Use a `text` fence for language-neutral pseudocode; simplified code need not compile.
- Aim for roughly 5–20 meaningful lines per mechanism, not a hard limit. Use one representative case for mechanical repetition. For several distinct changes, give each a compact view rather than hiding them behind one oversimplified example.
- Put source paths/symbols and line numbers or revisions beside the corresponding snippet. Identify both revisions for before/after comparisons.
- Explain what the snippet omits only when it affects interpretation. Keep setup/usage commands and lengthy evidence outside the main reading path unless requested.
- If a diagram is also requested, coordinate the same scope, names, and revisions. Let the snippet explain behavior and the diagram explain relationships; avoid repeating either in prose.
- For conceptual questions without confirmed implementation, use explicitly illustrative pseudocode only when useful or requested. Distinguish general behavior from verified project behavior.

## Verification

Check that a reader can explain what changed, why it matters, and which behavior remains important without reading the diff. A short example that erases the decisive condition or error path fails this check.
