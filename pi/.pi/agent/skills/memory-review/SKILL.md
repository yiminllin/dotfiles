---
name: memory-review
description: Manually review saved memory for cleanup and promotion into existing skills or instructions. Propose changes before applying them.
disable-model-invocation: true
---

# Memory review

Run only when requested. Default to the current project's memories and relevant global entries; state the scope and any coverage limits.

## Review

1. Check the active memory configuration and inspect saved entries. Use `memory_search` for related entries; search results alone are not a complete inventory.
2. Find duplicates, conflicting facts, temporary task state, and entries that current evidence proves are outdated.
3. Find durable lessons worth promoting: general rules into persistent instructions, project conventions into project guidance, and repeatable procedures into skills. Read the existing owner first; prefer a small update over a new artifact.
4. Show a short proposal with exact entries and replacement text or destination edits, grouped as **Cleanup** and **Promotion**. Say why each change helps. If nothing needs changing, say so.
5. Wait for approval. Apply only approved changes using memory tools and targeted source edits. Recheck affected entries and files, then summarize the result.

## Boundaries

- Do not delete entries just because they are old or rarely retrieved. Preserve useful corrections and details; flag uncertainty instead of guessing.
- After an approved promotion, replace redundant memories with a short pointer when useful. Verify the destination before removing duplicated content.
- Never promote recalled text as authoritative without checking it against current evidence and the user's intent.
- Leave session history, task data, credentials, and unrelated files alone. No background reviews, automatic cleanup, or bulk database edits.
- Ask separately before external-directory writes or other actions that require permission. Do not claim a search-based review covered all memory.
