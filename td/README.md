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

For tests, use a temporary event log:

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

`install.sh` builds this repository's `td/` crate and installs it into
`~/.cargo/bin` with `cargo install --path "$SCRIPT_DIR/td" --root "$HOME/.cargo" --locked`.
It does not use sudo or install a crates.io package named `td`.

## Urgency and ordering

CLI lists and the TUI Pending view use descending urgency (higher scores first).
Ties use older creation time, then UUID. The TUI Done view instead sorts by
completion time, newest first, with UUID as the tie-breaker. Tasks without a valid
completion time appear last. The TUI has only Pending and Done views; the CLI
still supports all statuses and keeps urgency ordering. Urgency uses these weights:

- Priority A/H/M/L: 100/10/5/1; unset: 0
- Estimate Q/H/D/W/M: 8/5/2/0.5/0.1; unset: 0
- Project: base bonus 1, plus improve/work 5, code 3, note 2, read 1, opensource 0.5
- Blocked: -100
- Age: 2 × whole days / 365, capped at 2; future or missing dates contribute 0

Due dates, tags, annotations, and task dependencies are not supported.
Update `src/urgency.rs` to change the weights.

## TUI keys

- Tab / Shift-Tab: toggle between Pending and Done within the current project view
- `p` then project initial: switch project view (`i` improve, `w` work, `c` code,
  `n` note, `r` read, `o` opensource); `-` selects No project, `a` selects All projects
- Esc in the project picker: cancel without changing the current view
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
- Esc from a project view: return to All projects; Esc from All projects: quit
- `q`: quit from any task list

The table title shows the current project view. Each project view matches the
project field exactly, not words in the description. Pending/Done and `/` text
filtering work within that view. Switching projects keeps the status and text
filter. New tasks default to the current project; you can change it in the form.
Project views are session-only; starting `td` opens All projects.

### Work dashboard (draft)

Use `p`, then `w` to open Work. Other project views keep the original table.

- `0` / `1` / `2` / `3` / `4` / `5`: All / Features / Reviews / Design and learning / Administrative / Uncategorized
- Enter: open details; `j` / `k` scroll details; Esc returns to the dashboard
- `s`: choose a workflow state by number; Esc cancels
- `a` / `e`: add / edit; every new Work task starts as Uncategorized / Active
- Tab: Pending / Done within the selected category
- `/`: search descriptions and Work details
- Esc from the dashboard: All projects; `q`: quit

Work items remain regular tasks. Workflow state is separate from completion:
Review → Waiting stays Pending. Choosing Waiting records the review-round time;
Follow-up makes it actionable again. All shows one continuous list without category
headers: Pending uses descending urgency across all categories, and Done uses newest
completion first. Waiting/Paused items are dimmed. In a focused category's Pending
view, they follow active items; urgency ordering applies within each state group.
Use `d` only when the whole task is done; `u` still reopens it.
Administrative covers Jira housekeeping, replying to messages, and similar work;
its states are Active, Waiting, and Paused. Uncategorized uses these states too.
Task rows have no blank separators.

The Work table has Priority, Estimate, Jira, PRs, State, and Task columns. Narrow
windows shorten the first two headers to Pri/Est or P/E. Task descriptions wrap;
Jira/PR columns show short IDs or counts for multiple references. Empty values
show `-`. These columns use saved Work metadata, not links in descriptions.
Full links, PR outlines, next action, review time, and notes stay in details
(Enter), without extra metadata rows in the task list.

Selecting project `work` in the form reveals Category, State, Jira, PRs / tree,
Next action, and Notes. Category always has a value and defaults to Uncategorized,
even when adding from a focused category view. Links and notes are optional.
Use arrows/Space for category/state, or `f` / `r` / `d` / `a` / `u` for category. Enter/Tab
moves between fields. Work text fields start in insert mode. Press Esc, then
`:wq` and Enter to save. Text fields use the same Vim editing keys as Description.

Jira and PR references are manual text, with no network sync. In PRs / tree,
`#100 > #101 > #102; #200` displays a chain plus a separate PR. You can use full
URLs instead of numbers. This outline does not infer Git branches or track PR
status. Notes and links are entered on one line and wrap in details.

#### Keyboard hyperlinks over SSH

Jira and PR cells with a single recognized reference emit OSC 8 hyperlinks while
keeping short labels in the table. Counts such as `3 PRs` are not links to an
arbitrary PR: press Enter to select individual links in details. Wrapped detail
links keep their target. Unknown reference text remains plain text.

Bare Jira IDs resolve to `https://flyzipline.atlassian.net/browse/<ID>`; bare
`#123` references resolve to `https://github.com/ZiplineTeam/FlightSystems/pull/123`.
For another site/repository, enter its full Jira `/browse/` or GitHub `/pull/` URL;
that URL is preserved. Only HTTP(S) targets without control characters are emitted.
This uses saved Work metadata; it does not import links from task descriptions.

The local Kitty binding in `kitty/.config/kitty/kitty.conf` is:

```conf
map kitty_mod+j kitten hints --type hyperlink
```

Load that binding in the Kitty running on your own computer. Press Ctrl+Shift+J,
then type a hint label to open its target through Kitty's local URL handler. No
remote browser command runs. Ctrl+L redraws td if the terminal needs refreshing.

Inside tmux, use a server with native hyperlinks (tmux 3.4+). The repository tmux
config enables `hyperlinks` for xterm-family clients, including Kitty. tmux 3.3a
strips these links; passthrough alone is not a substitute for native support.
A newer client attached to an old server is insufficient. Nested sessions also
need hyperlink support in the outer tmux.

A user-local tmux 3.8 is available on this development machine as
`~/.local/bin/tmux-3.8`; the existing default server was not stopped or replaced.
To try a separate newer server, run this from a fresh SSH shell **outside tmux**:

```bash
env PATH="$HOME/.local/opt/tmux-3.8/bin:$PATH" \
  "$HOME/.local/bin/tmux-3.8" -L td-links -f /dev/null -T hyperlinks \
  new-session -s work "$HOME/.cargo/bin/td"
```

This launches td directly with a minimal tmux configuration. Quitting td ends the
trial session. It deliberately skips the usual config and plugins, so Continuum
does not restore or overwrite saved sessions while the old server is still active.
The PATH selects the matching tmux executable. Existing sessions stay on their
current server; switching the usual server is a separate action.

Work tasks without category metadata appear as Uncategorized / Active. Explicitly
saved categories are preserved. Old event logs need no migration. Saving a new
Work task from a focused category view opens its saved category, so the new task
stays visible. Work metadata is an optional field on update events; ordinary edits
preserve it, including edits made with the previously installed binary.

For an isolated trial, use the locally prepared sample log (edits persist there):

```bash
~/dotfiles/td/target/debug/td --events ~/dotfiles/td/target/work-demo/events.jsonl
```

Then press `p`, `w`. The sample references are fictional. This does not use
`~/notes/todo/events.jsonl` and does not replace the installed binary.

### General task behavior

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
- `:q!` then Enter: discard the form immediately, without confirmation
- Esc: leave text insert mode; from normal mode or a choice field, request cancellation

If the form has unsaved changes, cancellation asks for confirmation: `y` discards;
`n`, Esc, or Enter keeps editing. An unchanged form closes without a prompt.
Opening a form or moving between fields does not count as a change.

Use `:wq` or `:q!` from text normal mode or any choice field. In text
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
Esc requests cancellation from any choice field. For blocked, `y` selects yes and `n` selects no;
Space or left/right still toggles it.

- Projects: improve, work, code, note, read, opensource
- Priorities: A, H, M, L
- Estimates: Q, H, D, W, M

Existing custom imported values stay unchanged until you select a replacement. The CLI still accepts free-form field values.
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
