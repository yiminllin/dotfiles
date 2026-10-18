# Pi compaction

## Automatic trigger

Pi's native automatic compaction triggers just above 60% for the two enabled models:

| Model | Context window | Trigger |
|---|---:|---:|
| `openai-codex/gpt-6.1-sol` | 500,000 | 300,000 |
| `openai-codex/gpt-6-luna` | 272,000 | 163,200 |

Per-model `compaction.modelOverrides` reserves set the trigger. The extension uses the
ordinary `compaction.reserveTokens` (16,384) for summary generation, so earlier triggers
do not increase summary limits. Recent-message retention and configured retries are unchanged.
Native compaction hooks, including memory flushing, still run. `compaction.enabled: false`
still disables automatic compaction. Other models retain native fallback thresholds.

A large tool batch can overshoot the trigger. Recalculate the absolute reserves if model
windows change. The 60% threshold is an experiment, not a proven quality boundary.

## File inventories

- Inventories below 4,000 JSON characters stay inline. Larger inventories move to
  `<project>/.pi/compaction-inventories/<uuid>.json`, with one reference in the summary.
- Cumulative paths remain in session metadata. Once externalized, later compactions
  keep using a snapshot. A later successful compaction recreates a deleted snapshot.
- Snapshots contain historical paths and provenance, not current Git status or copies
  of source files. They are not automatically deleted and never go into `~/notes`.
- Essential current paths stay in the summary. The assistant must explicitly read an
  inventory when needed; references do not load automatically.
- Summary generation keeps Pi's model, thinking level, recent-message boundary, and
  retry policy. Virtual selections use Pi's default path. Summaries remain lossy.
- Exhausted retries, permanent errors, cancellation, or storage failure leave no new
  checkpoint; the extension does not start an extra default compaction.

Load through the stowed user extensions directory. Run `/reload` in existing Pi sessions
to reload settings and the extension. For a one-off load: `pi --extension <directory>`.

Offline tests (no provider calls):

```sh
node --test pi/.pi/agent/extensions/compaction-inventory/test.mjs
```
