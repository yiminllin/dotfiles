---
name: phoenix-inspector
description: Canonical read-only Phoenix/HIL/GHA/ZML evidence inspector for inventory, bounded local log search, field-first ZML discovery, extraction, CSV summary, pass/fail comparison, and approved recent-HIL lookup.
---

# Phoenix Inspector

Use this skill for read-only Phoenix evidence work. Route launches, reruns, SIL/HIL execution, fetches, uploads, dispatches, and runtime mutation to `phoenix-workflows` (natural request or `/skill:phoenix-workflows`). Never use legacy Phoenix skills as the normal route.

## Helper strategy

The deterministic helper remains canonical at `$HOME/.config/opencode/scripts/phoenix_inspector.py`; do not duplicate its Python package in Pi. This stable stowed runtime path avoids two diverging implementations while OpenCode and Pi coexist. If it is absent, report that exact missing path and stop—do not install, copy, fetch, or silently substitute another helper. Save generated artifacts under `/tmp/pi/<short-task>`.

```bash
PI="$HOME/.config/opencode/scripts/phoenix_inspector.py"
python3 "$PI" --help
```

Running `--help` is safe. Before any other command, classify the source and effect.

## Routing

| Known input or intent | Command |
|---|---|
| Unknown explicit source shape/artifacts | `inventory <source>` |
| Known field, unknown topic | `fields <source> --fuzzy FIELD` (or `find-field`) |
| Known topic and field | `extract <source> --topic TOPIC --field FIELD` |
| Known topic, exploratory values | `extract <source> --topic TOPIC --all-fields --csv ...`, then `summary` |
| Local text signatures | `search-logs`, `validators`, or `journal` |
| Explicit fail/pass ZMLs | `compare --fail ... --pass ... --topic ... --field ...` or `--preset` |
| Recent HIL discovery | `recent-hil`, only after active-prompt network/auth approval |

Prefer `--format both --out-dir /tmp/pi/<short-task>` for report commands and `--csv /tmp/pi/<short-task>/<name>.csv` for extraction samples. Use `--systems-root /Systems` only when that explicit checkout is available. `local-text` is fixture-only, not production ZML decoding.

## Safety boundary

- Inspect only an explicit supported local directory, `.zml`/`.zml.zst`, GHA run/job URL, or non-root S3 prefix. Never broad-scan `/`, `/Systems`, home, bucket roots, or unrelated logs.
- Local inventory, bounded text search, and local ZML reads are read-only. Text search never downloads remote artifacts.
- **Require explicit approval in the active prompt before every network/auth/AWS/S3/GitHub action, including read-only remote inventory or `recent-hil`.** Existing credentials do not imply approval. Never initiate login, refresh credentials, read credential files, dispatch workflows, fetch/download, upload, launch hardware, or mutate runtime state.
- If approval, auth, a helper, `/Systems`, or an artifact is missing, stop and report the exact command/path/action, why it is needed, and the user decision.
- Do not invoke Phoenix runtime, SIL, HIL, Bazel execution, or external-log inspection merely to validate this skill.

## Evidence contract

Keep a Topic Ledger for nontrivial work: active question; exact run/scenario/job and source; topic/signal/log; time window or attempt; status; next decisive probe. Preserve exact decisive commands, exit status, report/CSV paths, blockers, and evidence limits.

Final claims must state: evidence supports/proves; evidence does not prove; missing comparison; blocker or next probe. Do not infer causal RCA from inventory, summaries, or signal deltas alone.

For detailed helper syntax, use `python3 "$PI" <command> -h`; do not load or copy the OpenCode README unless the user requests the operator guide.
