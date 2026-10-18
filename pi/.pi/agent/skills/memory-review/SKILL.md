---
name: memory-review
description: Manually review all in-scope saved memory for cleanup and promotion into existing skills or instructions, with explicit coverage accounting. Propose changes before applying them.
disable-model-invocation: true
---

# Memory review

Run only when requested. Default to a complete review of the current project's memories and relevant global entries, not a sample. Read every active global entry to determine relevance. Exclude unrelated projects unless requested. A quick or targeted review requires an explicitly narrower user request.

## Review

1. Check the active memory configuration and locate every authoritative store for active user, global, project, and failure entries. Inventory entries and counts by source and scope, including project-attributed entries in shared stores. Do not count recovery copies, retired files, or search-index copies as separate active entries. Use supported read-only access; if a store cannot be inventoried, report the gap rather than claiming complete coverage.
2. Read every inventoried entry in bounded batches. Continue past truncated output until all entries are read. Use `memory_search` to find relationships, not as an inventory or a substitute for reading. Track each entry by a stable identifier or exact text plus source; mark irrelevant entries as excluded with a reason.
3. Assign every in-scope entry a disposition: **keep**, **cleanup candidate**, **promotion candidate**, or **unresolved**. Check for duplicates, conflicting facts, temporary task state, already-promoted content, and facts that current evidence proves are outdated. An entry can have both cleanup and promotion candidates. Do not silently skip uncertain entries.
4. Make a cross-entry pass across files and scopes. Group related candidates, compare conflicting claims, and preserve unique useful details. Check durable lessons for promotion: general rules into persistent instructions, project conventions into project guidance, and repeatable procedures into skills. Read the existing owner and current evidence first; prefer a small update over a new artifact.
5. Reconcile the inventory with the dispositions. Report total entries, reviewed entries, exclusions, unresolved entries, and unread entries by source/scope. Record enough batch and entry references to resume without gaps if interrupted; do not save review progress as durable memory. If sources change during review, reconcile affected entries before claiming completion. Never describe the review as complete while entries remain unread or unresolved; distinguish full reading coverage from resolved findings.
6. Present all verified findings, grouped as **Cleanup** and **Promotion**, with exact entry identifiers and replacement text or destination edits. Explain briefly why each change helps. There is no arbitrary findings cap: group duplicates without hiding affected entries, and split long proposals into clearly labeled parts rather than dropping findings. List unresolved candidates separately with the evidence needed. Keep the coverage summary concise; do not narrate every kept entry. If nothing needs changing, say so only after the coverage check.
7. Wait for approval. Apply only approved changes using memory tools and targeted source edits. Verify promotion destinations before replacing redundant entries with pointers. Recheck affected entries and files, then summarize the result.

## Boundaries

- Do not delete entries just because they are old or rarely retrieved. Preserve useful corrections and details; flag uncertainty instead of guessing.
- After an approved promotion, replace redundant memories with a short pointer when useful. Verify the destination before removing duplicated content.
- Never promote recalled text as authoritative without checking it against current evidence and the user's intent.
- Leave session history, task data, credentials, and unrelated files alone. No background reviews, automatic cleanup, or bulk database edits.
- Ask separately before external-directory writes or other actions that require permission. Do not claim a search-based review covered all memory.
