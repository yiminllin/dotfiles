-- SETUP: Independent conversations share a panel but not their status, history or focus.
vim.opt.runtimepath:append(vim.fn.getcwd() .. "/nvim/.config/nvim")
local panel_view = require("utils.diffview_review_panel")
local ctx = { state_path = vim.fn.tempname() .. "/diffview-review.json" }
local state = {
  comments = {
    {
      local_id = "a",
      agent_request_id = "req-a",
      agent_status = "running",
      body = "First question",
      file = "a.lua",
      side = "LEFT",
      line = 3,
      end_line = 5,
    },
    {
      local_id = "b",
      author = "vscode",
      agent_request_id = "req-b",
      agent_status = "completed",
      agent_unread = true,
      body = "Second question\n\nWhy it matters: This is the only retry path.",
      file = "b.lua",
      line = 5,
      replies = { { author = "pi", body = "Second answer" } },
    },
  },
}
local read, replies, retried, jumped = {}, {}, {}, {}
local callbacks = {
  read = function(comment)
    read[#read + 1] = comment.local_id
    comment.agent_unread = nil
  end,
  reply = function(comment, body)
    replies[#replies + 1] = { comment.local_id, body }
  end,
  retry = function(comment)
    retried[#retried + 1] = comment.local_id
  end,
  jump = function(target)
    jumped[#jumped + 1] = target
  end,
}
local entries = { { path = "a.lua", viewed = true }, { path = "b.lua" } }
local function model(context, data)
  return { ctx = context, state = data, entries = entries, callbacks = callbacks }
end
local function press(key)
  vim.fn.maparg(key, "n", false, true).callback()
end
local function text(buffer)
  return table.concat(vim.api.nvim_buf_get_lines(buffer, 0, -1, false), "\n")
end
-- TEST: Render, navigate and update conversations without starting workers.
local counts = panel_view.counts(state, entries)
assert(counts.reviewed == 1 and counts.total == 2 and counts.running == 1 and counts.unread == 1) -- VERIFY: Counts stay independent.
assert(panel_view.status(state, entries, 120).text:find("1 investigating", 1, true))
assert(panel_view.status(state, entries, 30).winbar:find("%4@v:lua.DiffviewReviewStatusClick@", 1, true))
local panel = panel_view.open(model(ctx, state), { mode = "threads" })
assert(panel.expanded and vim.api.nvim_win_get_config(panel.winid).relative == "editor")
local buffer, window = panel.buffer, panel.winid
assert(read[1] == "b", "opening threads selects the unread reply")
assert(text(buffer):find("Second answer", 1, true) and not vim.bo[buffer].modifiable)
assert(text(buffer):find("🔍 Investigating", 1, true))
assert(text(buffer):find("📖 Guide", 1, true))
local marks = vim.api.nvim_buf_get_extmarks(
  buffer,
  vim.api.nvim_create_namespace("diffview_review_panel"),
  0,
  -1,
  { details = true }
)
local function has_card_author(group, name)
  return vim.iter(marks):any(function(mark)
    local line = vim.api.nvim_buf_get_lines(buffer, mark[2], mark[2] + 1, false)[1]
    return mark[4].hl_group == group and mark[4].end_col == #line and line:match("^│ " .. name .. " +│$")
  end)
end
assert(has_card_author("DiffviewReviewThreadQuestion", "vscode"))
assert(has_card_author("DiffviewReviewThreadResponse", "Pi"))
local thread_view = require("utils.diffview_review_threads")
local wide_comment = { local_id = "wide", file = "wide.lua", line = 2, body = "界 wide line that wraps\n\n\tindent" }
for _, width in ipairs({ 14, 58 }) do
  local lines, _, _, cards = thread_view.lines({ comments = { wide_comment } }, "wide", nil, nil, width)
  for row in pairs(cards) do
    assert(vim.fn.strdisplaywidth(lines[row]) == width, "message borders align across wrapped and blank rows")
  end
end
assert(text(buffer):find("# b.lua:5 RIGHT\n\n──", 1, true), "the location is separated from the comment")
assert(
  vim.iter(marks):any(function(mark)
    local line = vim.api.nvim_buf_get_lines(buffer, mark[2], mark[2] + 1, false)[1]
    return mark[4].hl_group == "DiffviewReviewProseLabel"
      and line:sub(mark[3] + 1, mark[4].end_col) == "Why it matters:"
  end),
  "the reason label is bold"
)
assert(
  not text(buffer):find("Reviewed 1/2", 1, true) and not text(buffer):find("Tab switch", 1, true),
  "counts and long key hints must not be duplicated inside the panel"
)
local function thread_action(label)
  local select = vim.ui.select
  vim.ui.select = function(items, opts, callback)
    vim.ui.select = select
    assert(opts.prompt == "Thread actions")
    for index, item in ipairs(items) do
      if item.label == label then
        local keys = opts.snacks.win
        local mapping = keys.input.keys[tostring(index)]
        assert(mapping == keys.list.keys[tostring(index)] and vim.deep_equal(mapping.mode, { "n", "i" }))
        local selected
        local picker = {
          list = {
            count = function()
              return #items
            end,
            get = function(_, row)
              return { idx = #items - row + 1 }
            end,
            move = function(_, row, absolute)
              assert(absolute)
              selected = #items - row + 1
            end,
          },
          action = function(_, action)
            assert(action == "confirm" and selected == index)
            callback(items[selected])
          end,
        }
        opts.snacks.actions[mapping[1]](picker)
        return
      end
    end
    error("Missing thread action: " .. label)
  end
  press("m")
  assert(vim.ui.select == select, "the action menu opened")
end

local read_count = #read
press("<Down>")
assert(#read == read_count, "arrows browse without acknowledging a conversation")
assert(panel.rows[vim.api.nvim_win_get_cursor(window)[1]] == "a", "arrow navigation stays in the list")
vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("<CR>", true, false, true), "mx", false)
window = panel.winid
assert(not panel.expanded, "jumping to code docks Threads")
assert(jumped[1].file == "a.lua" and jumped[1].side == "LEFT" and jumped[1].end_line == 5)
press("<Space>")
assert(panel.selected == "a" and panel.detail_line)
press("]t")
assert(panel.selected == "b" and text(buffer):find("Thread 2/2", 1, true))
press("[t")
assert(panel.selected == "a" and panel.detail_line)
press("<Esc>")
assert(not panel.detail_line and panel.rows[vim.api.nvim_win_get_cursor(window)[1]] == "a")
for index, command in ipairs({ "write", "wq" }) do
  if index == 1 then
    press("r")
  else
    thread_action("Reply")
  end
  local editor = vim.api.nvim_get_current_buf()
  assert(editor ~= buffer and vim.bo[editor].buftype == "acwrite")
  vim.api.nvim_buf_set_lines(editor, 0, -1, false, { "Follow up", "with a second line" })
  vim.cmd(command)
  assert(
    vim.wait(1000, function()
      return vim.api.nvim_get_current_win() == window and not vim.api.nvim_buf_is_valid(editor)
    end),
    command .. " closes only the reply draft and returns to Threads"
  )
  assert(vim.api.nvim_win_is_valid(panel.source_win) and panel.selected == "a")
  assert(#replies == index and vim.deep_equal(replies[index], { "a", "Follow up\nwith a second line" }))
end
vim.api.nvim_win_set_cursor(window, { 4, 0 })
local cursor = vim.api.nvim_win_get_cursor(window)
vim.api.nvim_set_current_win(panel.source_win)
local code_window = vim.api.nvim_get_current_win()
state.comments[1].agent_partial = "Streaming"
panel_view.refresh(model(ctx, state))
assert(vim.api.nvim_get_current_win() == code_window, "background replies never steal focus")
assert(vim.deep_equal(vim.api.nvim_win_get_cursor(window), cursor), "streaming preserves the cursor")
assert(text(buffer):find("Streaming", 1, true))
panel_view.refresh(model({ state_path = "different-review" }, { comments = {} }))
assert(text(buffer):find("Streaming", 1, true), "unrelated updates cannot replace this panel")

vim.api.nvim_set_current_win(window)
local windows = #vim.api.nvim_tabpage_list_wins(0)
press("<Tab>")
assert(panel.mode == "guide" and vim.api.nvim_get_current_buf() == buffer and not vim.wo.wrap)
press("<S-Tab>")
assert(panel.mode == "threads" and panel.selected == "a" and vim.wo.wrap)
assert(#vim.api.nvim_tabpage_list_wins(0) == windows, "tabs reuse the same window")
press("z")
assert(panel.expanded and vim.api.nvim_win_get_config(panel.winid).relative == "editor")
assert(#vim.api.nvim_tabpage_list_wins(0) == windows, "expansion replaces, not duplicates, the panel")
press("z")
window = panel.winid
assert(not panel.expanded and vim.api.nvim_win_get_config(window).relative == "")
assert(#vim.api.nvim_tabpage_list_wins(0) == windows)

state.comments[1].agent_status = "blocked"
state.comments[1].agent_input = { id = "ask-1", method = "confirm", title = "Which variant?" }
state.comments[2].agent_unread = true
panel_view.refresh(model(ctx, state))
local input_prompt
local old_select = vim.ui.select
vim.ui.select = function(_, opts)
  input_prompt = opts.prompt
end
thread_action("Answer Pi's question")
vim.ui.select = old_select
assert(input_prompt == "Which variant?", "input is routed to the selected worker")
press("]a")
assert(panel.selected == "b" and not state.comments[2].agent_unread)
press("]a")
assert(panel.selected == "a", "attention includes blocked requests, not only unread replies")
state.comments[1].agent_status = "completed"
local before = vim.api.nvim_get_current_win()
assert(panel_view.open(model(ctx, state), { mode = "threads", attention = true }) == panel)
assert(vim.api.nvim_get_current_win() == before, "no attention does not move focus")
state.comments[2].agent_unread = true
panel_view.open(model(ctx, state), { mode = "threads", filter = "unread" })
assert(panel.selected == "b" and text(buffer):find("Second answer", 1, true), "count filter opens a matching thread")
thread_action("Show all conversations")
assert(panel.filter == nil)

local first_tab = vim.api.nvim_get_current_tabpage()
vim.cmd("tabnew")
local second_tab = vim.api.nvim_get_current_tabpage()
local second =
  panel_view.open(model({ state_path = "second-review" }, vim.deepcopy(state)), { mode = "threads", selected = "b" })
thread_action("Retry Pi request")
assert(retried[#retried] == "b")
state.comments[1].agent_partial = "Only the first review changes"
panel_view.refresh(model(ctx, state))
assert(not text(second.buffer):find("Only the first review changes", 1, true), "review tabs remain isolated")
vim.api.nvim_set_current_tabpage(first_tab)
panel_view.open(model(ctx, state), { mode = "threads", selected = "a" })
window = panel.winid
thread_action("Retry Pi request")
assert(retried[#retried] == "a")
vim.api.nvim_set_current_tabpage(second_tab)
vim.api.nvim_set_current_win(second.winid)
press("q")
vim.cmd("tabclose")
vim.api.nvim_set_current_win(window)
press("q")
assert(#vim.fn.win_findbuf(buffer) == 0, "closing hides the panel, not its workers")
local reopened = panel_view.open(model(ctx, state), { mode = "threads" })
assert(reopened.buffer == buffer and reopened.selected == "a", "reopening preserves panel and selection")
press("q")
vim.cmd("split")
local caller = vim.api.nvim_get_current_win()
panel_view.open(model(ctx, state), { mode = "threads" })
press("q")
assert(vim.api.nvim_get_current_win() == caller, "closing returns to the latest invoking code window")
local first_visit = panel_view.open(model({ state_path = "first-visit" }, state), { mode = "guide" })
local read_before = #read
press("<Tab>")
assert(first_visit.mode == "threads" and first_visit.winid == vim.api.nvim_get_current_win())
assert(not first_visit.selected and #read == read_before, "Tab switches views without opening or marking a thread")
for _, mode in ipairs({ "threads", "guide" }) do
  assert(first_visit.mode == mode)
  local previous_search = vim.fn.getreg("/")
  vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("/Comment<Esc>", true, false, true), "mtx", false)
  assert(vim.api.nvim_get_current_win() == first_visit.winid and vim.fn.getcmdtype() == "", "Escape cancels search")
  assert(vim.fn.getreg("/") == previous_search, "cancelling search keeps the previous pattern")
  press("<Tab>")
end
print("diffview_review_threads: unified tabs, attention, status, replies, expansion and isolation passed")
