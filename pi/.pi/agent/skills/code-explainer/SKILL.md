---
name: code-explainer
description: Explain code behavior and PR concepts with source evidence; choose core code snippets, pseudocode, diagrams, or a direct answer. Use for "explain this PR", "show the core change", "explain with code and a diagram", call paths, callers/callees, entry points, subsystem maps, safe edit locations, and error explanations.
---

# Code Explainer

## Overview

Explain the concept, not the size of the diff. Investigate source, identify the problem and core mechanism, then choose the smallest faithful explanation. Answer directly, translate jargon, and mark uncertainty. Coordinate code examples and diagrams when useful; do not require either for a simple question.

## Goals

- Explain the purpose and role of the code in plain language.
- Identify key entry points, responsibilities, and data flow.
- Highlight important dependencies and boundaries.
- Describe inputs, outputs, and side effects.
- Use file evidence with line numbers or short snippets; be explicit about uncertainty and gaps.
- Keep the response short while still correct; avoid unnecessary expansion.

## Input flexibility

Accept any of the following as the starting point:
- Function/symbol name
- File path
- Directory path
- Module/package name (language inferred when possible)
- PR URL/number or a commit range
- Error message / log snippet / stack trace
- Behavior or change request, e.g. "where should this change go?" or "map this subsystem before editing"

If the request is ambiguous, ask only one short clarifying question (e.g., "Do you want the whole module, or just a specific file?").

## Choose the explanation

Investigate enough source to choose the view. Load these procedures as needed; they are not separate agents:

| What the reader needs | Action |
|---|---|
| A definition, location, narrow behavior, or error cause | Answer directly using the investigation workflows below. |
| An algorithm, API, type, state transition, or core change | Read `../core-code-extractor/SKILL.md` and follow its snippet procedure. |
| Architecture, ownership, dependencies, or message/data flow | Read `../code-diagram/SKILL.md` and follow its source-checking and rendering procedure. |
| Both behavior and relationships, or an explicit request for both | Load both specialists; combine complementary views of the same verified scope. |

Choose only useful views and honor explicit format requests. When combining views, use consistent names and put snippets beside the corresponding stages. Cover distinct major mechanisms, not every changed file. Follow the selected specialist's approval rules, including the diagram draft checkpoint.

## Workflow

1. Identify the starting scope (symbol, behavior, file, directory, or change). Infer language from extension when possible.
2. Locate top-level docs (README, module docs, docs/system) nearest to the scope; skim for purpose.
3. Read the main entry points (public functions, traits, structs/classes, or binaries) for responsibilities and inputs/outputs.
4. Identify key collaborators: dependencies, interfaces, or major subsystems it connects to.
5. Trace minimal, representative call paths only if needed to clarify behavior.
6. Double-check the most important claims by re-reading the relevant code regions.
7. Select the explanation view above; summarize the core mechanism and consequence with file references and material uncertainty.

### PR / change workflow

1. Verify head/base revisions and changed files; obtain permission before network/auth operations. Read implementation and necessary unchanged callers/consumers at those revisions, not today's checkout. Use PR prose for intent, not proof; distinguish this PR from stack context or future work.
2. Default to explicit before/after when both revisions are available and the contrast explains the change. Have the selected specialists generate the code or structural comparison. One comparison is enough; do not force paired views in both formats. Preserve actual old/new symbol names.
3. Verify each side independently. If source is missing, ask for it or disclose the limitation; never invent the missing side. Use an after-only view for conceptual questions or an explicit after-only request.
4. Check that the reader can identify the old behavior, new behavior, and consequential difference—not only the final design.

### Error-message workflow (use when input is an error/log/stack trace)

1. Parse the error text and extract the concrete signal: error code, exception type, log message, or assertion text.
2. Locate the origin in code: search for the exact string, error code, or the throwing/return site; then read the surrounding function.
3. Identify the immediate trigger conditions from code (preconditions, validation checks, Result/Err paths).
4. Enumerate upstream inputs or sources that could satisfy those trigger conditions (config, env vars, message fields, file IO, network responses, clock/time, external deps).
5. Trace the shortest confirmed call path from entrypoint to the error site; mark inferred edges as "likely."
6. Summarize “why this error happens” in one paragraph, then list concrete input sources that can cause it with file references.
7. If multiple sites emit the same error message, enumerate them and explain how to disambiguate (call site, log tags, error codes).

### Repo-map / change-location workflow (use before implementation or when asked where behavior lives)

1. Restate the requested behavior or planned change and the assumed subsystem boundary.
2. Identify likely entry points: public API, CLI, config, route, UI action, job/worker, test fixture, or message/event source.
3. Map the shortest relevant flow through layers: caller/adapter -> orchestration/wiring -> core logic -> persistence/external IO/side effects.
4. List owning files and symbols by layer, with confidence labels.
5. Identify guardrails, validation checkpoints, state transitions, and branch conditions that could change the edit location or risk.
6. Recommend likely safe edit locations and what each location would affect; separate confirmed edit points from likely candidates.
7. Call out unknowns and the fastest next read/search/test to resolve each one.

Do not propose a broad redesign. The goal is a compact map and safe-change guidance, not implementation.

## Search strategy

Use the available file search and read tools and open only the relevant files. Avoid speculation; label inferred links as "likely."

Common patterns:
- Rust: `fn name`, `impl Type { fn name`, `trait .*fn name`, calls: `name(`, `Type::name(`, `self.name(`.
- Go: `func name(`, `func (.*) name(`, calls: `name(`, `obj.name(`.
- Python: `def name(`, calls: `name(`, `obj.name(`.
- JS/TS: `function name(`, `const name = (` / `= async (`, calls: `name(`, `obj.name(`.
- Java/Kotlin: `class`, `fun`, `void`, `public .* name(`, calls: `name(`, `obj.name(`.
- C/C++: `name(` with signature matches; confirm by reading the definition file.

If the language uses dynamic dispatch (interfaces/traits/virtual), mark those edges as "likely" unless you can confirm concrete implementers.

## Explain the "why"

For the scope requested, answer:
- "What problem does this code solve?"
- "How does it fit into the subsystem?"
- "What are the main responsibilities and data flow?"

If intent is unclear, scan adjacent docs or README in the same subsystem. If still unclear, say "unknown" and state what you checked.

## Evidence rules

- Every factual claim must be backed by a file reference.
- Prefer line-number references; include a short snippet when line numbers are unavailable or when clarifying intent.
- Mark edges "confirmed" only when you can see the call site.
- Mark edges "likely" when inferred (dynamic dispatch, generated code, macros).
- If you cannot locate a definition or doc, say so and stop expanding that branch.

## Terminology expansion

When the explanation introduces new terms, expand them until the explanation is understandable without prior codebase knowledge. Use this loop:
1. Identify unfamiliar terms in the description.
2. Search for the term's definition or usage context.
3. Summarize in plain language (1-2 sentences each).
4. Stop when the explanation reads as a complete narrative to a non-expert.

Recommended lookup order:
- Same directory README or module docs.
- `docs/system/` and relevant design docs.
- Type or trait definitions in code.

## Stop conditions

Stop expanding when:
- The caller intent and system purpose are clear in plain language.
- Additional edges are only refactoring detail, not behavior.
- You hit a dynamic boundary you cannot verify.

## Output format

Start with the direct answer or conceptual change and precise source evidence. Use the selected specialist's format; for a simple question, stop at the direct answer. Avoid a fixed report template and do not repeat snippets or diagrams in prose. Define essential terms plainly. Include boundaries, safe edit locations, uncertainty, or the next decisive check only when relevant.
