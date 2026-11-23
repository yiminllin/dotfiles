# Human review guides and parallel conversations

Run `review` for your committed local branch, or `review <PR-number-or-URL>` for a remote PR. Remote reviews fetch the pinned source without changing your checkout. The main Pi session owns the review guide. Each
question runs in a separate Pi conversation with persistent history. Use a normal reply to ask for local edits. Up to three
conversations investigate in parallel; further requests wait. Follow-ups reuse
their thread history.

Existing Pi sessions need `/reload` before using this integration. Reopen
`review` to connect its service. New review sessions connect automatically.
After updating these files, run `source ~/.config/fish/functions/review.fish` in Fish, restart Neovim, and reopen `review`.

## In Diffview

| Key | Action |
| --- | --- |
| `<leader>gdg` | Open the review panel on the last used tab (Guide or Threads) |
| Tab / Shift-Tab, in code | Cycle hunks within the current section; change files outside section focus |
| `]r` / `[r` | Next/previous review section |
| `]c` / `[c` | Next/previous focused hunk; native change otherwise |
| `<leader>gdv` | Toggle the current Git hunk read in section focus |
| `<leader>gdA` | Ask Pi about a line or selected range |
| `<leader>gda` | Add/edit a private note on a line or selected range |
| `<leader>gdO` | Open matching checked-out source in a normal tab for LSP |
| `<leader>gdf` | Toggle All/Phoenix ownership scope |
| `<leader>gdr` | Refresh Diffview and reload the saved guide and GitHub discussions; do not generate a guide |
| `<leader>gdl` | Relocate a local comment anchor to the line or selected range |
| `<leader>gd]` / `<leader>gd[` | Jump to the next/previous code comment |

## One review panel

Guide and Threads share one panel per review/tab. Guide shows both the 🧭 PR overview and the 🔬 current section guide, separated by horizontal rules and emoji headings. The PR overview comes first: goal, before/after explanation, diagram, and core code. The section list follows. Each section starts with what changed and what to look for, then shows its diagram, core code, hunks, and discussions. There is no separate Chunks view.

Guide and Threads open expanded in the same centered panel. Press `z` to dock it on the left at about 25% width. Opening source docks the panel so you can see the diff. Source excerpts use syntax colors when an installed Tree-sitter parser supports their language. Pseudocode highlights keywords, calls, literals, and line comments without a parser. In Guide, press `g1` for the PR overview, `g2` for the section list, or `g3` for the active section details. Selecting another section updates its guide and focused diff while keeping the overview available above it.

`Tab` or `Shift-Tab` inside the panel switches Guide/Threads and preserves their reading positions. Press `z` to switch between expanded and split layouts, `?` for help, or `q` to close it. Escape remains available to cancel `/` search. Closing the panel does not cancel work. Reopening restores its selection. The header identifies the PR/branch, pinned base/head, and ownership scope. Counts appear in the status bar.

The review status bar shows review progress and counts for input requests, unread answers, investigation, and queued work. Click a count to open its conversations; click reviewed progress to open Guide. Narrow bars use `?` for input, `●` for unread, `↻` for investigating, and `…` for queued. `]a`/`[a` moves between conversations needing attention; `m` opens thread actions, including **Show all conversations** when filtered.

Threads shows each full message in a card with a bold author name. Questions and human replies use blue borders; Pi responses use green. It includes local comments, guide suggestions, and imported GitHub discussions, with full bodies, replies, source labels, matching review sections, and GitHub links. A GitHub-style card below the comment anchor shows its source and a one-line preview of the first message. An ellipsis means the message continues or there are more replies. The old comments quickfix command and `<leader>gds` are removed.

Commands: `:DiffviewReviewAllChanges`, `:DiffviewReviewThreads`, `:DiffviewReviewGuide`, and `:DiffviewReviewAttention`.

## Focused review sections

Pi divides the pinned PR into ordered semantic sections, not arbitrary file-size buckets. A section can span files; separate Git hunks in one file can belong to different sections. Start from the overview and press Enter on a section.

Enter opens a section/hunk. Press `v` on a section row to toggle the whole section viewed, or on a hunk row to toggle that hunk read. Press `V` anywhere in Guide to toggle the selected section, falling back to the active section. When a valid plan is ready, review starts at the first section in scope. Tab/Shift-Tab cycles hunks within the active section without moving Guide; `]r`/`[r` changes sections and scrolls an open Guide to **Review sections**. Navigation from code does not reopen a closed panel. Only the active section expands to show its Git hunks. Hunk jumps land on a changed line, not the leading context. Returning to a section restores its reading position.

The file panel contains the active section's files. Other regions in the original revision buffers are folded and labeled **outside active section**. This is a focused view of the same base/head, not a fabricated intermediate commit. Source links retain actual line numbers. Normal fold commands can expose context; only assigned hunks can be marked read. Use `:DiffviewReviewAllChanges` to leave section focus deliberately.

Neovim publishes `review-hunks.json` beside the guide. Pi must assign every inventory ID exactly once, including file-level changes; file attributes accompanying code travel with the first hunk. Unknown/duplicate IDs, omitted regions, stale pins, and forward dependencies reject the plan. Invalid updates retain the last valid partition and discussions. Ownership filtering restricts navigation, not whole-PR coverage; out-of-scope hunks remain labeled in the section list. The JSON schema still calls sections `chunks`.

The diff winbar and the top of Guide show overall hunk progress across the pinned review. Ownership filters do not change that total. The section list shows how many sections are complete and a hunk progress bar for each section. The active section also shows its progress above the Git hunks. These bars use the full section totals, even when ownership filtering hides some hunks. Marking a partial section viewed marks every remaining hunk read; toggling a viewed section clears all its hunk flags. If ownership filtering hides any of its hunks, switch ownership scope to All before changing the whole section. Read state belongs to immutable hunk identities, not section names or file flags, so regrouping preserves progress. Existing file flags and comments remain stored separately. Whole-file progress controls are removed; existing flags remain readable. Legacy guides remain readable: open Guide and press `r` to generate a section plan. After updating this configuration, reload Fish, restart Neovim, and `/reload` a reused Pi session before generating the plan.

| Threads key | Action |
| --- | --- |
| `↑` / `↓` | Browse without marking a conversation read |
| Enter | Open the comment’s pinned source. Press Esc there to return to the same thread row. |
| Space / Esc | Read the conversation / return to the list |
| `]a` / `[a` | Next / previous unread Pi answer or request for input |
| `m` | Open thread actions. Press a displayed number to choose it directly. |
| `q` | Close the panel without cancelling workers |

Click a status count to show only that group. In the `m` menu, **Show all conversations** removes that filter. The same menu offers replies, worker controls, and local resolve or dismissal. In the reply editor, `:w`, `:wq`, or normal-mode Ctrl-s sends and returns to the same thread. `:q!` discards.

To edit from a thread, press `m` → **Reply**, ask for the change, and send it with `:wq`. Pi can edit tracked files if the checkout matches the reviewed head. Edits are unstaged and do not appear in the pinned diff. Use `git diff` to inspect them.

Replies stream into the selected conversation without moving the cursor or
stealing focus. Inline status marks queued work, investigation, input requests,
and unread replies. Other conversations continue while one waits for input.

## General Diffview controls

| Key | Action |
| --- | --- |
| `<leader>gdc` | Open current changes |
| `<leader>gdm` | Compare against origin/main or FlightSystems origin/develop |
| `<leader>gdp` | Compare against the git-spice parent; never publish comments |
| `<leader>gdx` | Close Diffview itself |
| `<leader>gde` | Toggle the file explorer |
| `Alt+c` | Cycle the diff split sizes when focused on either diff side; keep Guide and the file explorer at their current widths |
| `<leader>gdi` | Toggle word-level highlighting |
| `<leader>gdr` | Refresh Diffview; also reload review state in a review |

Outside review buffers, `<leader>gdf` opens file history. Inside them, it toggles ownership scope.

## Main Pi beside Diffview

Pi starts in a pane below Neovim, in the same tmux window. Reusing a session moves it into the current review window when necessary, preserving its process, history, and running jobs. Agent Board therefore opens Pi together with Diffview.

Use Ctrl-j / Ctrl-k or Agent Board to move between Neovim and Pi. Startup and background replies do not steal focus. `review --no-agent` still opens Diffview without starting Pi.

## Generate and refine the human guide

The main Pi session creates or reuses `guide.json` when review starts. The guide
shows the goal, before/after behavior, a source-backed ASCII code diagram,
representative core code changes with source anchors, a top-down review route,
and short review cues at the start of each section. Detailed coverage remains
in the JSON artifact. Code snippets and diagrams
explain the same verified mechanism; simplified code is labeled explicitly.

Start with 🧭 PR overview, then select a 🔬 section in the same Guide panel.
The section guide appears below the overview with findings/questions and pinned
source jumps. 🔎 Careful reading and 👀 Skim use the guide's depth hints;
full discussion histories and local actions stay in Threads. Existing guides need no conversion.

Inside the guide:
- Press `r` to generate or update it from the pinned source and current discussions.
- Press `u` to write focused feedback, such as "show the before/after failure path".
  `:w` queues the refinement; `:q` closes the editor.
- Press Enter on a route row or source link to open its pinned source. Guide stays on the link you opened. Changed files in scope open in Diffview. If no diff entry is available, a read-only pane opens in the same review tab. Press `q` to return.

Commands: `:DiffviewReviewGenerateGuide` and `:DiffviewReviewRefineGuide`.
You can also ask the visible main Pi session to revise the same guide directly.

These explicit actions queue model turns in the main session without interrupting
its current work. They do not launch comment workers. Comments alone do not
regenerate the guide or trigger extra model turns. Updates use shared comments
and completed thread answers, preserve the pinned revisions and suggestion IDs,
and leave reviewed files, scope, and discussions unchanged.

The panel shows queued, updating, ready, or failed status and reloads the guide
without taking focus. A failed request shows an error; an unchanged guide stays
readable. Read the main Pi conversation for details. If an artifact has different
revisions, Diffview rejects it instead of displaying it as current.

While Pi works, files follow the last saved guide, or normal Diffview/Git order
if no guide exists. Neovim checks about once per second for a saved guide and
updates the guide route, file panel, and Tab navigation without changing the
selected file. Streaming text alone does not reorder files.

## Ownership and safety

- Children inherit the main session's most recent complete turn at their first
  launch. Initial questions wait until that context exists. Each question points
  them to the shared guide and current comments. They are not live copies of the
  main conversation.
- The main session receives questions and completed replies as background
  context. These updates do not interrupt it or start an extra model turn.
- Workers read pinned Git source through `review_source`, even when the checkout
  is on another branch. They can also use `read`, `grep`, `find`, `ls`, and
  `ask_user_question`. Questions use the installed questionnaire extension's RPC
  dialogs. Other tool calls are blocked. Ask the main session for edits,
  arbitrary commands, or external research.
- Workers have no tmux panes or Agent Board entries. Only the main review agent
  remains visible on the board.
- Closing Diffview leaves work running in the main Pi session. Closing or
  reloading that Pi session stops its workers. Reopen review and retry to resume
  a thread. Do not resume the same child manually while it is running.
- The host owns reply artifacts; Neovim owns comments; only the main agent owns
  guide updates. GitHub access is read-only. There is no comment-publishing action.

The service stores requests, replies, controls, and child histories beside
`guide.json`. This includes inherited main-session context. Treat these files as
private review data. They persist until you remove the review directory.

## LSP boundary

`gdO` preserves the pinned diff and opens a separate source tab only when HEAD
matches the selected side and tracked files are clean. Use normal LSP mappings
there, then return to the Diffview tab. It does not attach Rust Analyzer to
historical `diffview://` buffers or create worktrees. Other revisions require a
matching checkout; navigation must not silently use a different revision.

## Verification

Run `bash nvim/.config/nvim/tests/review.sh`. Tests use fake model events, the
installed Pi extension loader, headless Neovim, and real Diffview. They do not
call a model provider or GitHub. Provider behavior and live interactive dialogs
still need an interactive smoke test.
