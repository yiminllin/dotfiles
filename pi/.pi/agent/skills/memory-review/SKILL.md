---
name: memory-review
description: Review and consolidate saved Pi memories and skills across projects, including Git-ignored files in ~/notes. Check for duplicates, conflicting guidance, and lessons worth promoting. Propose changes before applying them.
disable-model-invocation: true
---

# Memory review

Run only when requested. Default to all active global and project memories and saved skills, including projects other than the current checkout. Narrow the scope only when the user asks. Use smaller batches rather than sampling.

## Review

1. Check the active memory and skill configuration. Inventory authoritative user, global, project, and failure entries, including project-attributed entries in shared stores. Inventory saved `SKILL.md` files in the configured memory and skill roots. Walk those directories directly (for example, with `find`); do not use Git status or tracked files to determine scope. New files under `~/notes/pi-memory/` may be Git-ignored but still active. Resolve symlinks and count each canonical file once. Exclude recovery copies, retired files, databases used only as indexes, and session history. Use supported read-only access to inventory active entries; report any inaccessible source.
2. Read every inventoried entry and skill in bounded batches. Continue past truncated output. Use `memory_search` to find relationships, not as an inventory or a substitute for reading. Track entries by stable ID or exact text plus source, and skills by canonical path. Report exclusions with reasons.
3. Assign every in-scope entry a disposition: **keep**, **cleanup candidate**, **promotion candidate**, or **unresolved**. Check for duplicates, conflicting facts, temporary task state, already-promoted content, and facts that current evidence proves are outdated. An entry can have both cleanup and promotion candidates. Do not silently skip uncertain entries.
4. Compare memories and skills across scopes. Group duplicates, reconcile conflicting guidance against current evidence, and preserve unique useful details. For overlapping skills, propose one canonical owner and explain what to merge or keep separate. Keep project-only details out of global skills. Check durable lessons for promotion into persistent instructions, project guidance, or existing skills. Read the existing owner first; prefer a small update over a new file.
5. Reconcile the inventory with the dispositions. Report totals, reviewed items, exclusions, unresolved items, and unread items by source and scope. Count memory entries and skill files separately. Record enough batch and entry references to resume without gaps if interrupted; do not save review progress as durable memory. If sources change during review, reconcile affected entries before claiming completion. Never describe the review as complete while entries remain unread or unresolved; distinguish full reading coverage from resolved findings.
6. Present all verified findings, grouped as **Cleanup** and **Promotion**, with exact entry identifiers and replacement text or destination edits. Explain briefly why each change helps. There is no arbitrary findings cap: group duplicates without hiding affected entries, and split long proposals into clearly labeled parts rather than dropping findings. List unresolved candidates separately with the evidence needed. Keep the coverage summary concise; do not narrate every kept entry. If nothing needs changing, say so only after the coverage check.
7. Wait for approval. Apply only approved changes using memory tools and targeted source edits. Treat Git inclusion as a separate decision: identify useful files to version after a privacy review, but do not change ignore rules or stage files without explicit approval. Verify promotion destinations before replacing redundant entries with pointers. Recheck affected entries and files, then summarize the result.

## Boundaries

- Do not delete entries just because they are old or rarely retrieved. Preserve useful corrections and details; flag uncertainty instead of guessing.
- After an approved promotion, replace redundant memories with a short pointer when useful. Verify the destination before removing duplicated content.
- Never promote recalled text as authoritative without checking it against current evidence and the user's intent.
- Leave session history, task data, credentials, and unrelated files alone. No background reviews, automatic cleanup, or bulk database edits.
- Ask separately before external-directory writes or other actions that require permission. Do not claim a search-based review covered all memory.
