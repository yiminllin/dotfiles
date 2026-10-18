# Compaction file inventories

Keeps large historical file inventories out of Pi's model context. Inventories below
4,000 JSON characters use normal compaction. Once a session externalizes an inventory,
later compactions carry it forward through compaction metadata, not inline file lists.

- Writes JSON snapshots to `<project>/.pi/compaction-inventories/<uuid>.json`.
- Stores paths and provenance only; does not copy referenced files or write to `~/notes`.
- Replaces file-list tags and old inventory references with one absolute-path reference.
- Keeps exact paths needed for current work in the generated summary.
- Uses Pi's `compact()` with the same model, thinking level, split-turn handling, and
  retained-message boundary. Summaries remain lossy; this does not validate their facts.
- Leaves virtual-model selections on Pi's default compaction path.
- Uses Pi's effective retry settings and normal retryable-error classification, including
  default limits and backoff. Reports scheduled retries and honors cancellation.
- Cancels after retries are exhausted, on non-retryable generation failures, or on storage
  failure, without starting an extra default compaction or saving a broken reference.
- Keeps the full inventory in session metadata as well as the JSON snapshot. Snapshots
  are local session artifacts, not durable notes, and are not automatically deleted.
  If an inventory file is removed, the next successful compaction recreates the cumulative
  inventory from metadata. A summary reference alone does not load the file into context.

Load through the normal stowed user extensions directory, then run `/reload` in existing
Pi sessions. For a one-off test, use `pi --extension <path-to-this-directory>`.

Offline verification (no provider calls):

```sh
node --test pi/.pi/agent/extensions/compaction-inventory/test.mjs
```
