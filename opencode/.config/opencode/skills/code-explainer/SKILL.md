---
name: code-explainer
description: Trace and explain call paths and code behavior across multi-language repositories. Use when asked to show a call graph, find callers/callees, locate entry points, explain how a function/module works, summarize code flow, or explain an error message with evidence.
---

# Code Explainer

## Overview

Provide high-level, conceptual understanding of code from a function, module, file, or directory. Summarize purpose, data flow, and key components with evidence. Keep results concise, translate jargon, and mark uncertainty. Include a short TL;DR, a small ASCII diagram, and a compact table for readability.

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
- Error message / log snippet / stack trace

If the request is ambiguous, ask only one short clarifying question (e.g., "Do you want the whole module, or just a specific file?").

## Workflow

1. Identify the starting scope (function, file, or directory). Infer language from extension when possible.
2. Locate top-level docs (README, module docs, docs/system) nearest to the scope; skim for purpose.
3. Read the main entry points (public functions, traits, structs/classes, or binaries) for responsibilities and inputs/outputs.
4. Identify key collaborators: dependencies, interfaces, or major subsystems it connects to.
5. Trace minimal, representative call paths only if needed to clarify behavior.
6. Double-check the most important claims by re-reading the relevant code regions.
7. Summarize purpose, responsibilities, data flow, and boundaries with file references and clear confidence levels.

### Error-message workflow (use when input is an error/log/stack trace)

1. Parse the error text and extract the concrete signal: error code, exception type, log message, or assertion text.
2. Locate the origin in code: search for the exact string, error code, or the throwing/return site; then read the surrounding function.
3. Identify the immediate trigger conditions from code (preconditions, validation checks, Result/Err paths).
4. Enumerate upstream inputs or sources that could satisfy those trigger conditions (config, env vars, message fields, file IO, network responses, clock/time, external deps).
5. Trace the shortest confirmed call path from entrypoint to the error site; mark inferred edges as "likely."
6. Summarize “why this error happens” in one paragraph, then list concrete input sources that can cause it with file references.
7. If multiple sites emit the same error message, enumerate them and explain how to disambiguate (call site, log tags, error codes).

## Search strategy

Prefer `rg` and open only the minimal set of files. Avoid speculation; label inferred links as "likely."

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

- TL;DR (2–4 bullets)
- Scope and intent
- Purpose (system context)
- Diagram (ASCII only; include inputs/outputs/side effects if applicable)
- Key responsibilities
- Data flow (high level)
- Dependencies and boundaries (table)
- Inputs/Outputs/Side effects (table or bullets)
- Call paths (only if needed; confirmed/likely)
- Terminology (plain-language definitions)
- Error analysis (only when user provides an error/log/stack trace)
- Evidence (short snippets or line-number references)
- Key files to inspect next

Keep file references precise and add line numbers when feasible.
