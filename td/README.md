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
td edit <id-prefix> --project work --priority M --estimate Q --state waiting
td edit <id-prefix> --project "" --priority "" --estimate "" --state none
```

The CLI displays full UUIDs. Unambiguous UUID prefixes also work as input.
Use empty values to clear project, priority, or estimate. Use `--state none` to clear
state. `add` and `edit` accept `none`, `next`, `in-progress`, or `waiting`.
Descriptions cannot be empty.

Loading rejects malformed logs, unsupported schemas, duplicate events or task
creations, and updates without a preceding task creation.

`install.sh` builds this repository's `td/` crate and installs it into
`~/.cargo/bin` with `cargo install --path "$SCRIPT_DIR/td" --root "$HOME/.cargo" --locked`.
It does not use sudo or install a crates.io package named `td`.

## Task agents

Save a task, then press `c` (chat) to open its Pi agent. On first use, this opens
settings without a picker. `C` opens the same settings later; there is no separate
`E` action. Names default to `review-123` for PR reviews or the first two task-title
words (up to 24 characters).

`Tab` changes fields:
- **Worktree:** `Enter` opens Session Finder. `F2` or `Ctrl-P` also browses;
  you can type a path instead.
- **Session ID:** `Enter` opens Agent Board to link a running session. Use arrows
  and `Enter`, or a number `1`–`9`, to choose. `Esc` or `q` returns to settings
  without changes. Selection saves its exact ID, worktree, and displayed name,
  then returns to settings. It does not launch, move, rename, or jump to Pi.
- **Session ID with a saved link:** `dd` immediately unlinks it and clears the
  field and Agent column. Pi keeps running, and its history stays intact.
- **Agent name:** `Enter` focuses **Save settings**. Saving validates the path and
  name and stores a session ID without launching Pi. Press `c` afterward to launch,
  resume, or jump. `C` never launches Pi.

Leave Session ID blank for a new session, or paste a full, exact session ID.
`Ctrl-U` clears a field. `Esc` closes settings and discards draft edits; applied
links and unlinks remain saved. To jump to a linked agent, close settings and
press `c`. If identity metadata is missing, run `/reload` in that Pi session.

The picker uses `~/.tmux/tmux-session-finder --print` with `fd` and `fzf`. It runs
in the current terminal, including inside the td popup; it does not open a nested
popup, invoke sessionizer, or create workspace windows.

Each task saves one Pi session ID, worktree path, and agent name. Subsequent `c`
presses jump to the live Pi pane or reopen it without setup prompts. This works
from every dashboard. With prefix + `T`, the popup closes after a successful
launch or jump so the destination is visible.

New windows go into the selected worktree's tmux workspace, not the calling
session. `tmux-sessionizer --ensure` reuses a workspace by path or creates a tmux
session with one shell window. It creates no Git worktree or extra Pi agent.
Workspace names start with the directory name; different paths with the same
name get separate sessions. Existing running agents are reused in place.

Generic tasks open `pi --session-id <id> --name <name>` without an initial task
message. PR-review tasks with one PR run Fish `review <PR-number-or-URL>` instead:
Diffview and its Pi assistant share the review window. This uses the review CLI's
normal bootstrap and preserves the task's Pi session ID and name. Saving the PR
review template never launches anything; press `c` when ready.

Agent Board shows the confirmed name. Windows use `󰚩 agent-1`, `󰚩 review-1`, etc.,
choosing the first free number in the destination workspace. Older unnamed links
use the short default. Existing windows are not renamed when jumping.

Every dashboard, including **All projects**, shows **Agent** immediately after
**State**. It refreshes about once per second:
- **A** (green): the linked Pi session is running in tmux.
- **I** (amber): a session is saved but not detected running in tmux.
- **Blank**: no session is linked.

Narrow Work dashboards shorten **In progress** to **In prog** to keep PR IDs and
the **Agent** header readable.

Run `td` inside tmux. This does not create Git worktrees or switch branches.
The review CLI may fetch the PR and base refs. Existing Pi sessions need `/reload`
once to publish their identity for jumps and Active status.

### Completing a task with an agent

`d` (or `td done <task-id>`) asks before completing an item with a running Pi in
its current tmux server. Confirming closes its td-created window, including
Diffview and every other pane. This interrupts Pi and can discard unsaved work.
Without td's ownership tag, only the Pi pane closes. This includes older td
windows and externally created windows.

Cancel leaves the task and session unchanged. Inactive sessions need no prompt.
Completion keeps the saved session ID and history so `c` can reopen it. If closing
fails after completion was saved, td reports that the item is Done but the agent
could not be closed.

```bash
td agent <task-id> --worktree /path/to/worktree --name "Review startup" # create and open
td agent <task-id>                              # jump or resume
td agent <task-id> --worktree /path/to/worktree --session <pi-session-id> --link-only
td agent <task-id> --unlink                     # keep session files
```

Associations use append-only events. Rebuild older `td` binaries before they read
logs containing these events. Completion can close a confirmed live agent, but it
never deletes session history.

## Urgency and ordering

CLI lists and every TUI Pending view sort by Done → In progress → Next →
No state → Waiting, with descending urgency within each group. Urgency ties use
older creation time, then UUID. The TUI Done view instead sorts by completion time,
newest first, then UUID. Tasks without a valid completion time appear last.
The CLI also supports deleted tasks. Urgency uses these weights:

- Priority A/H/M/L: 100/10/5/1; unset: 0
- Estimate Q/H/D/W/M: 8/5/2/0.5/0.1; unset: 0
- Project: base bonus 1, plus improve/work 5, code 3, note 2, read 1, opensource 0.5
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
- `A` (Shift+a): add from a preset template
- `e`: open the edit form for the selected task
- `c`: open or jump to the task's Pi chat
- `C`: agent settings; Session ID + Enter links through Agent Board, `dd` unlinks
- `y`: copy the selected task's full description to the clipboard (also in Work details).
  Uses tmux clipboard forwarding inside tmux, or OSC 52 otherwise. Your terminal
  must allow clipboard writes; this also works over SSH.
- `m`: mark/unmark the current pending task for merging; move and press `m` on
  each additional task. Enter opens the populated merge form; edit any field and
  use `:wq` to save. Esc cancels with a discard check; `:q!` discards immediately.
- `d`: mark done
- `u`: reopen the selected completed task (in either view)
- `x`: delete
- `s`: open the state picker; arrows or `j`/`k` move, Enter applies, `1`–`4` selects directly, Esc cancels
- `S` (Shift+s): cycle No state → Next → In progress → Waiting → No state.
  State controls also work in Work details; completed tasks are unchanged.
- `/`: filter tasks in the current view
- Esc from a project view: return to All projects; Esc from All projects: quit
- `q`: quit from any task list

Merging joins descriptions with a blank line, in marking order. The first marked
task supplies the ID and metadata; all fields remain editable. Saving soft-deletes
the other tasks, preserving their original data in the event log. Completed tasks
cannot be marked. Selection and preview do not write changes.

The table title shows the current project view. Each project view matches the
project field exactly, not words in the description. Pending/Done and `/` text
filtering work within that view. Switching projects keeps the status and text
filter. New tasks default to the current project; you can change it in the form.
Project views are session-only; starting `td` opens All projects.

### Workflow state

Every task has a state, including tasks without a project. New tasks default to No state.
Changing project or category preserves state. Standard add/edit forms include State;
quick-add templates keep their minimal fields and start with No state.

| Picker key | State | Meaning | Background |
|---|---|---|---|
| `1` | No state | Tracked, but not a current focus | Gray |
| `2` | Next | You intend to work on it next | Cyan |
| `3` | In progress | You are working on it | Purple |
| `4` | Waiting | Waiting on someone or something before continuing | Amber |

State is separate from Pending / Done. Waiting tasks stay Pending.
Use `d` when the task is done and `u` to reopen it with its previous state.
Done is not a picker choice: a green Done badge overrides the state badge while
complete. Waiting rows are dimmed outside the state badge.

### Quick-add templates

Press `A` from a task list, then choose `p` (PR review), `i` (Improvement),
`f` (Feature work), or `d` (Design doc review). The picker shows these letter hints.
Numbers `1`–`4` or arrows and Enter also work. Each template shows only its required inputs:

| Template | Inputs | Presets |
|---|---|---|
| PR review | One PR link or number, priority | Work / Reviews, M/H |
| Improvement | Description, priority, category | Improve, A/Q |
| Feature work | One Jira ticket link or key, priority | Work / Features, M/H |
| Design doc review | Description, document list, priority | Work / Reviews, M/H |

The last two preset letters mean priority / estimate. Work templates start with
No state. Bare PR numbers use FlightSystems; bare Jira numbers use `FSW`.
Improvement category starts Uncategorized. Ordinary `a` keeps its existing defaults.

Templates use the same editing keys as ordinary add. Type or paste the input;
multiline pasted descriptions stay intact. Enter and Tab advance fields without
saving; Shift-Tab moves back. Enter on Useful links opens the editor; Tab
accepts the current link and moves to Priority. Choose priority with A/H/M/L or Left/Right; choose
an Improve category with `1`–`6` or arrows. Text fields support the same Vim keys.
Esc leaves insert mode, then `:wq` and Enter save. `:q!` and Enter discard.
Esc in normal/select mode cancels, with confirmation for unsaved changes.
Ctrl-S does not save.

PR and Feature templates look up titles in the background using `gh` and
configured-host `jira issue view --raw`. These tools are optional: lookup failure,
missing tools, or a five-second timeout uses the reference as the task description.
Existing authentication is used; quick-add does not log in. Esc during lookup
returns to the draft without saving.

Design doc review keeps your Description and requires a document link in **Useful links**. Saving does not wait for title lookup.

Saving opens the template's project/category and clears the text filter so the
new task is visible. Use ordinary `e` afterward to change any other field.

### Improve categories

Use `p`, then `i` to open Improve. The table shows Category instead of Project.

- `0` / `1` / `2` / `3` / `4` / `5` / `6`: All / td / nvim / agents / terminal / system / Uncategorized
- Add or edit an Improve task to choose Category with `1`–`6` or arrows.
- Category appears in the form only when Project is `improve`.
- Tab switches Pending / Done within the selected category; `/` filters descriptions.

New and existing tasks default to Uncategorized. Adding from a focused category
still starts Uncategorized; saving switches the filter to the new task's category.
Changing projects preserves saved category metadata. Improve categories are separate
from Work categories and do not affect urgency. `td show` and `td list --json` include
`improve_category`; category editing is currently TUI-only, like Work metadata.
Old events need no rewrite: category changes append update events.

### Work dashboard (draft)

Use `p`, then `w` to open Work. Other project views keep the original table.

- `0` / `1` / `2` / `3` / `4` / `5`: All / Features / Reviews / Design and learning / Administrative / Uncategorized
- Enter: open details; `j` / `k` scroll details; Esc returns to the dashboard
- `a` / `e`: add / edit; ordinary add starts as Uncategorized / No state
- `A`: quick-add from a template with a preset category
- `r`: refresh the selected task's PR and document titles in the background (also in details)
- Tab: Pending / Done within the selected category
- `/`: search descriptions and Work details
- Esc from the dashboard: All projects; `q`: quit

For Work reviews, choosing Waiting records the review-round time. Move the review
to Next when it needs attention.

All shows one continuous list without category headers. Focused categories use
the same ordering as other Pending views. Administrative covers Jira housekeeping,
messages, and similar work. Task rows have no blank separators.

Column headers and **Useful links** use Octicons. Use a Nerd Font to see them.
Link icons distinguish PRs, PR chains, tickets, documents, spreadsheets, slides,
forms, videos, threads, wikis, repositories, folders, and other web links.
Each PR in a chain has its own URL. The table wraps descriptions and link titles.
If there is no cached title, it shows a short label such as `#123` or `Google Doc 1`.
Review time and notes are in task details (Enter).

### Cached link titles

Work refreshes missing titles and titles at least 10 minutes old in the background.
It checks tasks in the current Work list, including its category and text filters.
Requests run one at a time with a five-second timeout. `r` refreshes the selected
task's links without waiting for the 10-minute interval. Failed requests keep
existing titles. Jira summaries use the configured `jira` CLI for tickets on
`flyzipline.atlassian.net`. If no summary is available, td shows the ticket key.

The cache is `$XDG_CACHE_HOME/td/pr-titles.json`, or
`~/.cache/td/pr-titles.json` by default. It stores titles and refresh times by full
link URL, separately from the task event log. Cached titles appear immediately;
first-time fetches do not block navigation, editing, saving, or quitting. Quitting
cancels an active refresh. Missing, corrupt, or unwritable caches do not prevent
task entry. Deleting the cache is safe. Task descriptions are never overwritten.
PR lookup uses ordinary `gh` requests, not conditional ETag requests.
Document titles share this cache and refresh policy. Public pages use `curl`
without browser authentication. Confluence page links on `flyzipline.atlassian.net`
use the read-only page API with existing `JIRA_API_USERNAME` and `JIRA_API_TOKEN`.
Credentials pass through stdin, not command arguments; authenticated requests do
not follow redirects or send credentials to other hosts. Missing credentials or
failed lookups keep the short label. Private Google Docs may not provide a title.

When testing with an isolated event log, also set `XDG_CACHE_HOME` to a temporary
directory to keep test titles separate from your normal cache.

### Work item fields

Selecting project `work` in the form reveals Category, Useful links, and Notes. Category always has a value. Ordinary add defaults to Uncategorized,
even from a focused category view; quick-add templates supply their preset category.
Category choices and the focused State field appear as indented rows with short explanations, muted text, and a dot on the selected
choice. Choice rows have no bold text or colored backgrounds.
Links and notes are optional.
Use arrows, `j` / `k`, or Space for category/state; `f` / `r` / `d` / `a` / `u`
selects a category, and `1`–`4` selects a state. Tab moves between fields.
Enter on **Useful links** opens one editor for all references. Notes use the same
Vim keys as Description.

- Paste URLs, Jira keys such as `FSW-12345`, or PR numbers such as `#123`.
  A bare number means a FlightSystems PR. Spaces, commas, and newlines separate entries.
- To link a file in `~/notes`, paste a relative path such as `projects/repo/docs/plan.md`.
  Use `notes:path` for other file types, or start the path with `~/notes/`. Use paths without spaces.
  td stores relative paths and shows icons for docs, reviews, tables, and images.
  Opening local links depends on the terminal.
- To add a PR chain, enter `#123 > #124`, with the base PR first.
- Use arrows or `j`/`k` to select an entry. Enter edits it; `x` deletes it.
  `J`/`K` reorders entries of the same type. Esc cancels the current input.
- Tab accepts the input and moves to Notes. Esc from the list returns to the
  current field. Save the form with `:wq` and Enter.

Existing links and chains need no migration. PR and Jira URLs use their canonical
paths. Document URLs keep their queries and fragments.

#### Keyboard hyperlinks over SSH

Each link in the table and details emits its own OSC 8 hyperlink. Wrapped lines
keep their target. Unrecognized legacy references appear as plain text.

Bare Jira IDs resolve to `https://flyzipline.atlassian.net/browse/<ID>`; bare
`#123` or `123` references resolve to `https://github.com/ZiplineTeam/FlightSystems/pull/123`.
For another site/repository, enter its full Jira `/browse/` or GitHub `/pull/` URL. Only HTTP(S) targets without control characters are emitted.
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

Legacy logs load without rewriting history. Legacy Blocked becomes Waiting;
otherwise the saved Work state is preserved, or defaults to No state.
Active/Reviewing/Exploring → In progress; To review/Follow-up → Next;
Idea/Paused → No state; Waiting stays Waiting. New saves use task-wide state,
which overrides later legacy state/blocked updates. New events and task JSON omit
Blocked and nested Work state. Taskwarrior imports map Blocked to Waiting.
The old Blocked flag, shortcut, and urgency penalty are removed. Update older
`td` binaries on other machines before reading new saves; they require the retired
Blocked field.

Work tasks without category metadata appear as Uncategorized. Explicit categories
are preserved. Saving a new Work task from a focused category view opens its saved
category, so it stays visible. Ordinary edits preserve unrelated Work metadata.

For an isolated trial, use the locally prepared sample log (edits persist there):

```bash
~/dotfiles/td/target/debug/td --events ~/dotfiles/td/target/work-demo/events.jsonl
```

Then press `p`, `w`. The sample references are fictional. This does not use
`~/notes/todo/events.jsonl` and does not replace the installed binary.

### General task behavior

Every Pending view keeps tasks completed within the last 24 hours and puts them
first. Completed rows are dimmed, with a ✓ marker and strikethrough
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
Project labels use green. State badges use the colors listed above.

Task rows have pale project backgrounds: improve sage, work blue, code lavender,
note sand, read blush, and opensource mint. Wrapped continuation lines share the
same background, except for state badges. Unset or custom projects keep the terminal background.

The task list has labeled columns: Priority, Estimate, State, Project, and
Description. Narrow windows use Pri/Est. Status is shown by the Pending/Done view
and Done badges. Urgency sorts within state groups but is not shown in the TUI.
Descriptions wrap at word boundaries, including long words when needed.
Ctrl-U/Ctrl-D move by screen lines so even descriptions taller than the popup can
be read fully. `j`/`k` still move between tasks. The `>` marker identifies the
selected line without changing category colors or intensity. Deleted tasks are
hidden in the TUI; the CLI can still list them.

Descriptions wrap across lines in add, edit, and merge forms. The form scrolls
to keep the description cursor or selected metadata field visible.

In the add/edit form:

- Enter or Tab: move to the next field (wraps after the last field)
- Shift-Tab: move to the previous field
- `:wq` then Enter: save all fields and return to the task list
- `:q!` then Enter: discard the form immediately, without confirmation
- Esc: leave text insert mode; from normal mode or a choice field, request cancellation

If the form has unsaved changes, cancellation asks for confirmation: `y` discards;
`n`, Esc, or Enter keeps editing. An unchanged form closes without a prompt.
A merge always asks before discarding.
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
State uses `1`–`4` to select directly, or arrows, `j`/`k`, or Space to cycle.
Esc requests cancellation from any choice field.

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
