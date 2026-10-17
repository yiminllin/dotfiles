# td

`td` is a small Rust todo CLI/TUI backed by an append-only JSONL event log.

## Build and install

```bash
cargo build --manifest-path ~/dotfiles/td/Cargo.toml
cargo install --path ~/dotfiles/td --locked
```

## Data path

Default canonical data lives at:

```text
~/notes/todo/events.jsonl
```

For tests or migration checks, avoid the canonical file and override the path:

```bash
TD_EVENTS_PATH=/tmp/td-events.jsonl td list
td --events /tmp/td-events.jsonl add "try td" --project note
```

## Common usage

```bash
td                                      # open TUI
td list                                 # pending tasks
td list --status completed                 # done tasks
td list --status all --json
td add "write note" --project note --priority H --estimate D
td show <id-prefix>
td edit <id-prefix> --description "new text"
td done <id-prefix>
td delete <id-prefix>
td edit <id-prefix> --project work --priority M --estimate Q --blocked true
td edit <id-prefix> --project "" --priority "" --estimate "" --blocked false
```

The CLI displays full UUIDs. Unambiguous UUID prefixes also work as input.
Use empty values to clear project, priority, or estimate. Descriptions cannot be empty.

Loading rejects malformed logs, unsupported schemas, duplicate events or task
creations, and updates without a preceding task creation.

Taskwarrior Fish abbreviations are no longer configured. In existing Fish
sessions, erase legacy abbreviations or restart the shell. In particular, an old
`td` abbreviation may still need `abbr --erase td` before using this tool.
`install.sh` builds this repository's `td/` crate and installs it into
`~/.cargo/bin` with `cargo install --path "$SCRIPT_DIR/td" --root "$HOME/.cargo" --locked`.
It does not use sudo or install a crates.io package named `td`.
The legacy `task/` configuration is retained as a migration/scoring reference,
but `install.sh` no longer installs or stows Taskwarrior.

## Urgency and ordering

CLI lists and the TUI Pending view use descending urgency (higher scores first). This deliberately differs
from `report.list.sort = urgency+` in `task/.taskrc`, while keeping the same scoring.
Ties use older creation time, then UUID. The TUI Done view instead sorts by
completion time, newest first, with UUID as the tie-breaker. Tasks without a valid
completion time appear last. The TUI has only Pending and Done views; the CLI
still supports all statuses and keeps urgency ordering. Scoring matches the current Taskwarrior configuration for supported fields:

- Priority A/H/M/L: 100/10/5/1; unset: 0
- Estimate Q/H/D/W/M: 8/5/2/0.5/0.1; unset: 0
- Project: base bonus 1, plus improve/work 5, code 3, note 2, read 1, opensource 0.5
- Blocked: -100
- Age: 2 × whole days / 365, capped at 2; future or missing dates contribute 0

This scorer does not implement Taskwarrior fields absent from td, such as due dates,
tags, annotations, or dependencies. It does not read Taskwarrior configuration at
runtime; update `src/urgency.rs` if those weights change.

## Taskwarrior migration

Do a dry run first against a saved export:

```bash
task export > /tmp/taskwarrior-export.json
td --events /tmp/td-import-check.jsonl import taskwarrior /tmp/taskwarrior-export.json --dry-run
```

Validate the actual append path against a temporary event log before touching the
canonical file:

```bash
td --events /tmp/td-import-check.jsonl import taskwarrior /tmp/taskwarrior-export.json
td --events /tmp/td-import-check.jsonl list --status all --json
```

Actual import appends create events plus completed/deleted events as needed and
skips Taskwarrior UUIDs already present in the target event log. When you are
ready to migrate, intentionally rerun the import with
`--events ~/notes/todo/events.jsonl`.

## TUI keys

- Tab / Shift-Tab: toggle between Pending and Done
- `j`/`k` or arrows: move
- `gg` / `G`: first / last task in the current view
- Ctrl-U / Ctrl-D: move up / down half a page (based on the visible table height)
- `a`: open the add form
- `e`: open the edit form for the selected task
- `d`: mark done
- `u`: reopen the selected completed task (in either view)
- `x`: delete
- `b`: toggle blocked
- `/`: filter tasks in the current view
- `q`/Esc: quit from the task list

The Pending table also keeps tasks completed within the last 24 hours in their
usual urgency order. Completed rows are dimmed, with a ✓ marker and strikethrough
on the description only. Project colors stay unchanged. Dimming depends on your
terminal; it does not change background transparency. Press `u` to reopen an
accidental completion.
After 24 hours they disappear from Pending on the next interaction, but remain
in Done. This uses a rolling 24-hour window, not the calendar day.

The table border shows a bold colored view label: amber for Pending, green for
Done, followed by the filter. The form header shows
`INSERT`, `NORMAL`, `SELECT`, or `COMMAND`.
The active field has a `>` marker. Text editing shows the cursor. Colors use the
dim borders and muted accents without reverse video. The palette suits the
Solarized Light terminal configuration. Priority uses distinct dark red, orange,
amber, and taupe shades; estimates range from deep blue to slate blue.
A/H priorities and Q/H estimates stay bold; other values use less saturated colors.
Project labels use green; blocked uses purple.

Task rows have pale project backgrounds: improve sage, work blue, code lavender,
note sand, read blush, and opensource mint. Wrapped continuation lines share the
same background. Unset or custom projects keep the terminal background.

The task list has labeled columns: Priority, Estimate, Blocked, Project, and
Description. Status is shown by the selected Pending/Done view rather than a
column. Urgency still controls sorting but is not shown in the TUI.
Descriptions wrap at word boundaries, including long words when needed.
Ctrl-U/Ctrl-D move by screen lines so even descriptions taller than the popup can
be read fully. `j`/`k` still move between tasks. The `>` marker identifies the
selected line without changing category colors or intensity. Deleted tasks are
hidden in the TUI; the CLI can still list them.

In the add/edit form:

- Enter or Tab: move to the next field (wraps after blocked)
- Shift-Tab: move to the previous field
- `:wq` then Enter: save all fields and return to the task list
- Esc: leave insert mode; press again to cancel from description normal mode

Use `:wq` from description normal mode or any choice field. In description
insert mode, press Esc first; `:` remains ordinary text while inserting.
Esc from the command prompt returns to the form without saving.

Description uses a small set of Vim bindings. Add starts in insert mode; edit
starts in normal mode:

- `h`/`l` or arrows: move left/right in normal mode
- `0`/`$`: start/end; `w`/`b`: next/previous word
- `i`/`a`: insert before/after the cursor; `I`/`A`: insert at start/end
- `x`: delete the character under the cursor
- In insert mode: type text, use arrows/Home/End, Backspace, or Delete

Project, priority, and estimate are choice fields. Use left/right arrows or Space
to cycle. Backspace/Delete selects unset (`-`). Project first letters select
directly; `h`/`l` also cycle projects. Priority and estimate letters work in either
case (`h` selects H, `l` selects L for priority, `q` selects Q for estimate).
Esc cancels from any choice field. For blocked, `y` selects yes and `n` selects no;
Space or left/right still toggles it.

- Projects: improve, work, code, note, read, opensource
- Priorities: A, H, M, L
- Estimates: Q, H, D, W, M

These choices match `task/.taskrc`. Existing custom imported values stay unchanged
until you select a replacement. The CLI still accepts free-form field values.
Description is required. In the filter view, Enter applies the filter and Esc cancels.

After changing the source, rebuild with `cargo build --manifest-path td/Cargo.toml`
and run `./td/target/debug/td`, or reinstall with `cargo install --path ./td --locked --force`.

## tmux popup

Prefix + T opens the installed `td` in a popup, 75% of the terminal width and
65% of its height. Press `q` from the task list to close it and return to your pane.
Reinstall after source changes so the popup uses the updated binary.

The binding in `tmux/.tmux.conf` is:

```tmux
bind-key T display-popup -E -w 75% -h 65% '$HOME/.cargo/bin/td'
```
