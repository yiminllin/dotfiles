-- Requires an installed Diffview. Run with -u NONE -i NONE and a local TMPDIR.
local repo = vim.fn.getcwd()
local plugin = vim.env.DIFFVIEW_PLUGIN or (vim.fn.stdpath("data") .. "/lazy/diffview.nvim")
assert(vim.fn.isdirectory(plugin) == 1, "Set DIFFVIEW_PLUGIN to the installed Diffview directory")
local root = vim.fn.tempname()
vim.fn.mkdir(root, "p")
vim.env.XDG_CACHE_HOME = root .. "/cache"
vim.opt.runtimepath:append(repo .. "/nvim/.config/nvim")
vim.opt.runtimepath:append(plugin)
local function git(...)
  local args = { "git", "-C", root }
  vim.list_extend(args, { ... })
  local result = vim.fn.systemlist(args)
  assert(vim.v.shell_error == 0, table.concat(result, "\n"))
  return result[1]
end
local function commit(message)
  git("add", "-u")
  git(
    "-c",
    "user.name=Fixture",
    "-c",
    "user.email=fixture@example.invalid",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.hooksPath=/dev/null",
    "commit",
    "-qm",
    message
  )
  return git("rev-parse", "HEAD")
end
git("init", "-q")
git("config", "diff.suppressBlankEmpty", "true")
vim.fn.mkdir(root .. "/.github", "p")
vim.fn.writefile({
  "*.lua @ZiplineTeam/phoenix-reviewers",
  "/c.lua @ZiplineTeam/phoenix-physics-reviewers",
  "/b.lua @ZiplineTeam/phoenix-reviewers @other/team",
}, root .. "/.github/CODEOWNERS")
for _, path in ipairs({ "a.lua", "b.lua", "c.lua", "old.lua" }) do
  vim.fn.writefile({ "", "old", "tail" }, root .. "/" .. path)
end
vim.fn.writefile({ "fn pinned() -> bool {", "    true", "}" }, root .. "/context.rs")
git("add", ".")
local base = commit("base")
for _, path in ipairs({ "a.lua", "b.lua", "c.lua" }) do
  vim.fn.writefile({ "", "new", "tail" }, root .. "/" .. path)
end
git("mv", "old.lua", "renamed.lua")
local head = commit("head")
local path = root .. "/guide.json"
local diagram =
  { "    +------------------+", "    | PR flow fixture  |", "    +------------------+", "", "    Context: c.lua" }
local document = {
  context = { base_oid = base, head_oid = head },
  summary = "A concise takeaway.",
  behavior_change = { before = "Old marker.", after = "New marker." },
  diagram = diagram,
  core_code = {
    { label = "Source excerpt", title = "Before", code = { "old" }, sources = { "a.lua:2 at " .. base } },
    {
      label = "Source excerpt",
      title = "After",
      code = { "new" },
      sources = {
        "a.lua:2 at " .. head,
        { path = ".github/CODEOWNERS", side = "LEFT", revision = base, line = 1, end_line = 2 },
        { path = "context.rs", side = "LEFT", revision = base, line = 1, end_line = 2 },
        { path = "old.lua", side = "LEFT", revision = base, line = 2, end_line = 3 },
      },
    },
  },
  validation = { review_scope = "Fixture only.", gaps = { "Provider not exercised." } },
  files = {
    { path = "b.lua", reason = "inspect shared entry" },
    {
      path = "a.lua",
      reason = "inspect behavior",
      suggestions = {
        { id = "left", side = "LEFT", line = 2, body = "left question" },
        { id = "file", line = vim.NIL, body = "file question" },
      },
    },
    { path = "renamed.lua", reason = "check rename" },
    { path = "c.lua", reason = "inspect downstream context" },
  },
}
local function write_guide()
  vim.fn.writefile({ vim.json.encode(document) }, path)
end
write_guide()
vim.cmd.cd(root)
vim.cmd.runtime("plugin/diffview.lua")
local review = require("utils.diffview_review")
require("diffview").setup({ use_icons = false, keymaps = review.diffview_keymaps() })
review.setup()
local function open(head_oid)
  review.set_active_guide_context({
    repo = root,
    path = path,
    context_kind = "branch",
    base_oid = base,
    head_oid = head_oid,
    diffview_rev_arg = base .. ".." .. head_oid,
    assistant_name = "offline-fixture",
    review_label = "offline-fixture",
  })
  vim.cmd("DiffviewOpen " .. base .. ".." .. head_oid)
end
open(head)
local lib = require("diffview.lib")
assert(vim.wait(5000, function()
  local view = lib.get_current_view()
  return view and view.cur_entry and view.files:len() == 4 and view.cur_entry.layout:get_main_win()
end, 20))
local view = lib.get_current_view()
local function settle()
  vim.wait(200, function()
    return false
  end, 20)
end
local function await_file(path)
  assert(
    vim.wait(5000, function()
      if not view.cur_entry or view.cur_entry.path ~= path then
        return false
      end
      local count = 0
      for _, file in ipairs(view.cur_entry.layout:files()) do
        if file.bufnr and vim.api.nvim_buf_is_valid(file.bufnr) then
          local lines = vim.api.nvim_buf_get_lines(file.bufnr, 0, -1, false)
          local expected = file.symbol == "a" or path == "renamed.lua"
          if lines[2] == (expected and "old" or "new") then
            count = count + 1
          end
        end
      end
      return count == 2
    end, 20),
    "both revision buffers must load for " .. path
  )
  settle()
end
local function tab(previous)
  local mapping = vim.fn.maparg(previous and "<S-Tab>" or "<Tab>", "n", false, true)
  assert(type(mapping.callback) == "function", "native Tab binding must be available")
  local key = vim.api.nvim_replace_termcodes(previous and "<S-Tab>" or "<Tab>", true, false, true)
  vim.api.nvim_feedkeys(key, "mx", false)
end
local function assert_order(expected)
  local paths, rendered = {}, {}
  for _, entry in ipairs(view.panel:ordered_file_list()) do
    table.insert(paths, entry.path)
  end
  for _, component in ipairs(view.panel.components.working.files) do
    table.insert(rendered, component.comp.context.path)
    local row = vim.api.nvim_buf_get_lines(view.panel.bufid, component.comp.lstart, component.comp.lstart + 1, false)[1]
    assert(row:find(component.comp.context.basename, 1, true), "panel row must render its ordered entry")
  end
  assert(vim.deep_equal(paths, expected), vim.inspect(paths))
  assert(vim.deep_equal(rendered, expected), "rendered rows must use the same order as Tab")
end
await_file("b.lua")
assert_order({ "b.lua", "a.lua", "renamed.lua", "c.lua" })
tab()
await_file("a.lua")
tab(true)
await_file("b.lua")
tab()
await_file("a.lua")
local function focus(side)
  for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
    for _, file in ipairs(view.cur_entry.layout:files()) do
      if file.symbol == side and file.bufnr == vim.api.nvim_win_get_buf(win) then
        vim.api.nvim_set_current_win(win)
        vim.api.nvim_win_set_cursor(win, { 2, 0 })
        return win
      end
    end
  end
  error("side is not visible")
end
local function state()
  return vim.json.decode(table.concat(vim.fn.readfile(root .. "/diffview-review.json"), "\n"))
end
local review_tab = vim.api.nvim_get_current_tabpage()
local refresh_review = review.refresh_review
local review_refreshed = false
review.refresh_review = function()
  review_refreshed = true
end
vim.api.nvim_feedkeys((vim.g.mapleader or "\\") .. "gdr", "mx", false)
review.refresh_review = refresh_review
assert(review_refreshed, "gdr reloads the review in a pinned review view")
local pinned_win = focus("b")
local pinned_buffer = vim.api.nvim_win_get_buf(pinned_win)
local pinned_lines = vim.api.nvim_buf_get_lines(pinned_buffer, 0, -1, false)
local pinned_path = view.cur_entry.path
local working_path = root .. "/" .. pinned_path
local working_lines = vim.fn.readfile(working_path)
vim.fn.writefile({ "local edit, not part of the pinned diff" }, working_path)
vim.cmd.edit()
assert(
  vim.deep_equal(vim.api.nvim_buf_get_lines(pinned_buffer, 0, -1, false), pinned_lines),
  ":edit keeps the pinned source"
)
assert(not vim.bo[pinned_buffer].modifiable)
vim.fn.writefile(working_lines, working_path)
local navigation_panel = review.show_guide_popup()
local function panel_source(path, side)
  vim.api.nvim_set_current_win(navigation_panel.winid)
  for row, target in pairs(navigation_panel.targets) do
    if target.path == path and target.side == side then
      vim.api.nvim_win_set_cursor(navigation_panel.winid, { row, 0 })
      return target
    end
  end
  error("Missing source: " .. path .. " " .. side)
end
local function panel_key(key)
  vim.fn.maparg(key, "n", false, true).callback()
end
for _, side in ipairs({ "LEFT", "RIGHT" }) do
  panel_source("a.lua", side)
  assert(vim.api.nvim_get_current_line() == "↗ a.lua:2 · " .. (side == "LEFT" and "Before" or "After"))
  vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("<CR>", true, false, true), "mx", false)
  assert(
    vim.wait(3000, function()
      return vim.api.nvim_get_current_win() ~= navigation_panel.winid
        and vim.api.nvim_get_current_line() == (side == "LEFT" and "old" or "new")
        and vim.api.nvim_win_get_cursor(0)[1] == 2
    end, 20),
    "source links select the correct real revision buffer"
  )
end
local invalid_source = panel_source("a.lua", "RIGHT")
invalid_source.end_line = 999
panel_key("<CR>")
settle()
assert(vim.api.nvim_get_current_win() == navigation_panel.winid, "invalid ranges never clamp or steal focus")
review.refresh_visible()
panel_source("old.lua", "LEFT")
panel_key("<CR>")
assert(
  vim.wait(3000, function()
    return view.cur_entry.path == "renamed.lua"
      and vim.api.nvim_get_current_win() ~= navigation_panel.winid
      and vim.api.nvim_get_current_line() == "old"
  end, 20),
  "base references follow the old path of a renamed file"
)
local marks =
  vim.api.nvim_buf_get_extmarks(0, vim.api.nvim_create_namespace("diffview_review_target"), 0, -1, { details = true })
assert(
  #marks == 2 and marks[1][2] == 1 and marks[2][2] == 2 and marks[1][4].sign_text and marks[2][4].sign_text,
  "native diff source links mark the first and last line in the gutter"
)
panel_source("a.lua", "RIGHT")
view.right.commit = base
local before_stale = view.cur_entry
panel_key("<CR>")
assert(
  view.cur_entry == before_stale and vim.api.nvim_get_current_win() == navigation_panel.winid,
  "stale panel navigation cannot change the selected file"
)
view.right.commit = head
panel_source(".github/CODEOWNERS", "LEFT")
panel_key("<CR>")
local continued_reviewing = focus("b")
settle()
assert(
  vim.api.nvim_get_current_tabpage() == review_tab and vim.api.nvim_get_current_win() == continued_reviewing,
  "late source reads cannot take focus after the reviewer moves on"
)
panel_source("context.rs", "LEFT")
panel_key("<CR>")
assert(vim.wait(3000, function()
  return vim.api.nvim_buf_get_name(0):match("^review%-source://") ~= nil
end, 20))
assert(vim.api.nvim_get_current_tabpage() == review_tab)
assert(vim.api.nvim_get_current_line() == "fn pinned() -> bool {")
assert(not vim.bo.modifiable and vim.bo.filetype == "rust" and vim.bo.buftype == "nofile")
assert(
  vim.treesitter.highlighter.active[vim.api.nvim_get_current_buf()] or vim.fn.synID(1, 1, 1) ~= 0,
  "pinned Rust snapshots use Tree-sitter or built-in Rust syntax"
)
assert(vim.wo.number and not vim.wo.wrap)
panel_key("q")
assert(vim.api.nvim_get_current_tabpage() == review_tab)
panel_source("a.lua", "RIGHT")
panel_key("<CR>")
assert(vim.wait(3000, function()
  return view.cur_entry.path == "a.lua"
    and vim.api.nvim_get_current_win() ~= navigation_panel.winid
    and vim.api.nvim_get_current_line() == "new"
end, 20))
vim.api.nvim_set_current_win(navigation_panel.winid)
panel_key("q")
local original_state = state()
local with_attention = vim.deepcopy(original_state)
vim.list_extend(with_attention.comments, {
  {
    local_id = "ui-unread",
    file = "a.lua",
    side = "RIGHT",
    line = 2,
    body = "Explain new marker\nwith more context",
    agent_request_id = "offline-unread",
    agent_status = "completed",
    agent_unread = true,
    replies = { { author = "pi", body = "Offline answer", request_id = "offline-unread" } },
  },
  {
    local_id = "ui-input",
    file = "a.lua",
    side = "LEFT",
    line = 2,
    end_line = 3,
    body = "Explain old marker",
    agent_request_id = "offline-input",
    agent_status = "blocked",
    agent_input = { id = "offline-question", method = "confirm", title = "Inspect more?" },
  },
  {
    source = "github",
    github_id = "ui-github",
    file = "a.lua",
    file_level = true,
    author = "alice",
    body = "Full imported question\nwith its second line",
    github_url = "https://example.invalid/comment/1",
    replies = { { author = "bob", body = "A GitHub reply" } },
  },
  {
    file = "a.lua",
    side = "RIGHT",
    line = 2,
    end_line = 2,
    body = "Legacy question\nwith full local context",
    created_at = "2026-01-01T00:00:00Z",
  },
})
vim.fn.writefile(
  { vim.json.encode({ cwd = root, updated_at = vim.fn.localtime() * 1000 }) },
  root .. "/review-service.json"
)
vim.fn.writefile({ vim.json.encode(with_attention) }, root .. "/diffview-review.json")
review.refresh_visible()
local preview_text = {}
for _, file in ipairs(view.cur_entry.layout:files()) do
  for _, mark in
    ipairs(
      vim.api.nvim_buf_get_extmarks(
        file.bufnr,
        vim.api.nvim_create_namespace("diffview_review"),
        0,
        -1,
        { details = true }
      )
    )
  do
    local rows = mark[4].virt_lines
    if rows then
      assert(
        #rows == 3 and rows[1][1][1]:match("^╭─") and rows[3][1][1]:match("╯$"),
        "preview has a rounded border"
      )
      local width = vim.fn.strdisplaywidth(rows[1][1][1])
      assert(width == vim.fn.strdisplaywidth(rows[3][1][1]))
      local row = table.concat(vim.tbl_map(function(chunk)
        return chunk[1]
      end, rows[2]))
      assert(vim.fn.strdisplaywidth(row) == width, "the preview fits inside its border")
      table.insert(preview_text, row)
      if row:find("Explain new", 1, true) then
        assert(file.symbol == "b" and mark[2] == 1, "preview belongs to the exact right-side anchor")
        assert(row:match("…%s*│$"), "the preview indicates omitted text")
      end
    end
  end
end
local previews = table.concat(preview_text, "\n")
assert(previews:find("Explain new", 1, true), previews)
assert(not previews:find("more context", 1, true) and not previews:find("Offline answer", 1, true))
assert(not previews:find("Legacy question", 1, true) and not previews:find("Full imported question", 1, true))
local format = require("utils.diffview_review_format")
assert(format.comment_preview({ body = "界界界" }, 5) == "界界…", "truncation preserves wide characters")
assert(
  vim.wo[view.panel.winid].winbar:find("%3@v:lua.DiffviewReviewStatusClick@", 1, true),
  "review status exposes actionable input and unread counts"
)
local attention_panel = review.next_attention()
assert(
  attention_panel.buffer == navigation_panel.buffer and attention_panel.selected == "ui-unread",
  "attention reuses the guide panel and selects an unread answer"
)
for _, comment in ipairs(state().comments) do
  if comment.local_id == "ui-unread" then
    assert(not comment.agent_unread, "reading acknowledges the persisted reply")
  end
end
review.status_click(3, 1, "l")
assert(
  attention_panel.selected == "ui-input" and attention_panel.filter == "blocked",
  "count clicks filter real conversations"
)
vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("<CR>", true, false, true), "mx", false)
assert(
  vim.wait(3000, function()
    return vim.api.nvim_get_current_win() ~= attention_panel.winid and vim.api.nvim_get_current_line() == "old"
  end, 20),
  "threads jump to their pinned side and range"
)
review.show_threads()
assert(attention_panel.selected == "ui-input", "opening at the code cursor selects its conversation")
local function thread_action(label)
  local select = vim.ui.select
  vim.ui.select = function(items, opts, callback)
    vim.ui.select = select
    assert(opts.prompt == "Thread actions")
    for _, item in ipairs(items) do
      if item.label == label then
        callback(item)
        return
      end
    end
    error("Missing thread action: " .. label)
  end
  panel_key("m")
  assert(vim.ui.select == select, "the action menu opened")
end

review.status_click(3, 1, "l")
thread_action("Show all conversations")
local function select_discussion(preview)
  for row in pairs(attention_panel.rows) do
    if vim.api.nvim_buf_get_lines(attention_panel.buffer, row - 1, row, false)[1]:find(preview, 1, true) then
      vim.api.nvim_win_set_cursor(attention_panel.winid, { row, 0 })
      panel_key("<Space>")
      return
    end
  end
  error("Missing discussion: " .. preview)
end
select_discussion("Full imported question")
local discussion = table.concat(vim.api.nvim_buf_get_lines(attention_panel.buffer, 0, -1, false), "\n")
assert(
  discussion:find("@alice", 1, true)
    and discussion:find("with its", 1, true)
    and discussion:find("second line", 1, true)
    and discussion:find("A GitHub reply", 1, true)
    and discussion:find("https://example.invalid/comment/1", 1, true)
)
thread_action("Resolve locally")
local resolved_github
for _, comment in ipairs(state().comments) do
  if comment.github_id == "ui-github" then
    resolved_github = comment
  end
end
assert(resolved_github.local_resolved and not resolved_github.resolved, "GitHub resolution is local only")
thread_action("Delete or dismiss locally")
assert(state().dismissed_github_comments["ui-github"], "dismissed GitHub discussions cannot return on import")
select_discussion("Legacy question")
thread_action("Resolve locally")
local legacy
for _, comment in ipairs(state().comments) do
  if comment.body:find("Legacy question", 1, true) then
    legacy = comment
  end
end
assert(legacy.resolved, "ID-less legacy comments resolve by exact identity, not display coordinates")
thread_action("Delete or dismiss locally")
for _, comment in ipairs(state().comments) do
  assert(not comment.body:find("Legacy question", 1, true))
end
assert(vim.fn.maparg("P", "n", false, true).buffer ~= 1, "pane navigation has no review-specific shortcut")
assert(vim.fn.exists(":DiffviewReviewAgent") == 0, "the redundant Pi-focus command is removed")
local header = vim.api.nvim_buf_get_lines(attention_panel.buffer, 0, 2, false)
assert(
  header[1]:find("Branch offline-fixture", 1, true)
    and header[1]:find(base:sub(1, 8) .. ".." .. head:sub(1, 8), 1, true)
)
assert(header[2]:find("? help", 1, true) and not discussion:find("Tab switch", 1, true))
local leader = vim.g.mapleader or "\\"
local function reopen_panel(mode)
  panel_key("q")
  assert(not attention_panel.winid)
  assert(vim.fn.maparg(leader .. "gdT", "n") == "", "Threads has no separate shortcut")
  panel_key(leader .. "gdg")
  assert(vim.api.nvim_get_current_buf() == navigation_panel.buffer and attention_panel.mode == mode)
end
reopen_panel("threads")
panel_key("<Tab>")
reopen_panel("guide")
panel_key("q")
vim.fn.writefile({ vim.json.encode(original_state) }, root .. "/diffview-review.json")
review.refresh_visible()
focus("b")
review.open_review_source()
assert(vim.api.nvim_get_current_tabpage() ~= review_tab, "matching source opens outside the pinned diff")
assert(vim.api.nvim_buf_get_name(0) == root .. "/a.lua", "LSP uses the real checked-out source path")
assert(vim.api.nvim_win_get_cursor(0)[1] == 2, "source navigation preserves the selected line")
vim.cmd.tabclose()
assert(vim.api.nvim_get_current_tabpage() == review_tab)
focus("a")
review.open_review_source()
assert(vim.api.nvim_get_current_tabpage() == review_tab, "historical navigation must not silently use HEAD")
focus("b")
vim.fn.writefile({ "", "dirty", "tail" }, root .. "/a.lua")
review.open_review_source()
assert(vim.api.nvim_get_current_tabpage() == review_tab, "dirty source cannot claim to match the pinned revision")
vim.fn.writefile({ "", "new", "tail" }, root .. "/a.lua")
focus("a")
vim.ui.select = function(items, _, callback)
  for _, item in ipairs(items) do
    if item.comment.body == "left question" then
      callback(item)
      return
    end
  end
  error("left guide question not found")
end
review.resolve_comment({ line = 2 })
assert(state().comments[1].resolved)
local right = focus("b")
review.delete_comment({ line = 3 })
assert(#state().comments == 1)
review.add_comment({ line = 2, end_line = 3 })
vim.api.nvim_buf_set_lines(0, 0, -1, false, { "saved draft" })
vim.cmd("write")
local draft
for _, comment in ipairs(state().comments) do
  if comment.body == "saved draft" then
    draft = comment
  end
end
assert(draft and draft.anchor_status == "anchored")
assert(draft.anchor.original.line == 2 and draft.anchor.original.end_line == 3)
assert(
  vim.deep_equal(draft.anchor.original.text, { "new", "tail" }),
  "the draft anchors to pinned source, not its editor"
)
-- Saved data from the retired file-progress controls remains readable.
local legacy = state()
legacy.viewed["a.lua"] = true
vim.fn.writefile({ vim.json.encode(legacy) }, root .. "/diffview-review.json")
review.refresh_visible()
-- Working-tree ownership must not affect the immutable review.
vim.fn.writefile({ "* @nobody" }, root .. "/.github/CODEOWNERS")
review.toggle_ownership_filter()
assert(vim.wait(5000, function()
  return view.files:len() == 3
end, 20))
await_file("a.lua")
for _, entry in ipairs(view.panel:ordered_file_list()) do
  assert(entry.path ~= "c.lua")
  if entry.path == "renamed.lua" then
    assert(entry.oldpath == "old.lua", "filter must preserve rename pairs")
  end
end
assert(state().ownership_filter == "phoenix" and state().viewed["a.lua"])
assert_order({ "b.lua", "a.lua", "renamed.lua" })
assert(vim.wo[right].winbar:find("2/3", 1, true), "route position must use the filtered denominator")
assert(vim.wo[view.panel.winid].winbar:find("1/3", 1, true), "reviewed progress must use the filtered denominator")
local cursor = vim.api.nvim_win_get_cursor(right)
review.show_guide_popup()
local popup = vim.api.nvim_get_current_win()
local popup_buf = vim.api.nvim_win_get_buf(popup)
local lines = vim.api.nvim_buf_get_lines(popup_buf, 0, -1, false)
local diagram_start
for index, line in ipairs(lines) do
  if line == diagram[1] then
    diagram_start = index
    break
  end
end
assert(diagram_start)
for index, line in ipairs(diagram) do
  assert(lines[diagram_start + index - 1] == line)
end
assert(
  table.concat(lines, "\n"):find("Source excerpt — Before", 1, true),
  "core changes must be visible in the real guide popup"
)
assert(
  not table.concat(lines, "\n"):find("Provider not exercised.", 1, true),
  "audit notes stay out of the reading view"
)
assert(not vim.wo[popup].wrap, "diagram must not wrap")
assert(not table.concat(lines, "\n"):find("4. c.lua", 1, true), "route must use visible scope")
assert(table.concat(lines, "\n"):find("Context: c.lua", 1, true), "diagram keeps full PR context")
local notifications, original_notify = {}, vim.notify
vim.notify = function(message, ...)
  table.insert(notifications, message)
  original_notify(message, ...)
end
vim.fn.writefile(
  { vim.json.encode({ cwd = root, updated_at = vim.fn.localtime() * 1000 }) },
  root .. "/review-service.json"
)
view.right.commit = base
assert(not review.request_guide("generate"), "a changed Diffview comparison cannot generate a guide for stale context")
view.right.commit = head
assert(review.request_guide("refine", "Explain the changed marker\nand keep the code comparison."))
local request_path = vim.fn.glob(root .. "/guide-requests/*.json", false, true)[1]
local request = vim.json.decode(table.concat(vim.fn.readfile(request_path), "\n"))
assert(
  request.root == root and request.base_oid == base and request.head_oid == head,
  "guide requests preserve the visible immutable boundary"
)
assert(
  request.action == "refine" and request.body:find("\nand keep", 1, true),
  "the main guide request preserves focused multiline feedback"
)
vim.fn.writefile(
  { vim.json.encode({ request_id = request.request_id, base_oid = base, head_oid = head, status = "running" }) },
  root .. "/guide-status.json"
)
assert(
  vim.wait(2500, function()
    return table
      .concat(vim.api.nvim_buf_get_lines(popup_buf, 0, -1, false), "\n")
      :find("Main Pi: updating guide", 1, true)
  end, 20),
  "guide job status must refresh even before guide.json changes"
)
assert(vim.api.nvim_get_current_win() == popup, "guide status must not steal focus")
-- Simulate Pi atomically updating the guide during conversation.
document.summary = "Updated understanding."
document.core_code[2].code = { "new", "tail" }
document.files = { document.files[2], document.files[3], document.files[1], document.files[4] }
local temp = path .. ".tmp"
vim.fn.writefile({ vim.json.encode(document) }, temp)
assert((vim.uv or vim.loop).fs_rename(temp, path))
assert(
  vim.wait(2500, function()
    return table
      .concat(vim.api.nvim_buf_get_lines(popup_buf, 0, -1, false), "\n")
      :find("Updated understanding.", 1, true) ~= nil
  end, 20),
  "guide must reload through agent polling"
)
assert(view.cur_entry.path == "a.lua" and vim.deep_equal(vim.api.nvim_win_get_cursor(right), cursor))
assert_order({ "a.lua", "renamed.lua", "b.lua" })
assert(state().viewed["a.lua"] and state().ownership_filter == "phoenix" and #state().comments == 2)
assert(table.concat(notifications, "\n"):find("review order updated", 1, true))
vim.notify = original_notify
vim.api.nvim_win_close(popup, true)
review.toggle_ownership_filter()
assert(vim.wait(5000, function()
  return view.files:len() == 4
end, 20))
await_file("a.lua")
assert(state().viewed["a.lua"] and state().comments[2].body == "saved draft")
assert_order({ "a.lua", "renamed.lua", "b.lua", "c.lua" })
tab()
await_file("renamed.lua")
tab()
await_file("b.lua")
tab()
await_file("c.lua")
tab()
await_file("a.lua")
tab(true)
await_file("c.lua")
-- Toggling while the current file is excluded must leave a valid diff layout.
review.toggle_ownership_filter()
assert(vim.wait(5000, function()
  return view.files:len() == 3 and view.cur_entry.path ~= "c.lua"
end, 20))
settle()
review.clear_active_guide_context()
vim.cmd.DiffviewClose()
settle()
-- Start without guidance: native order first, then adopt the late guide without moving the diff.
vim.fn.delete(path)
open(head)
view = lib.get_current_view()
await_file("a.lua")
assert_order({ "a.lua", "b.lua", "renamed.lua" })
tab()
await_file("b.lua")
tab(true)
await_file("a.lua")
right = focus("b")
cursor = vim.api.nvim_win_get_cursor(right)
write_guide()
assert(vim.wait(2500, function()
  return view.panel.listing_style == "list"
end, 20))
assert_order({ "a.lua", "renamed.lua", "b.lua" })
assert(view.cur_entry.path == "a.lua" and vim.deep_equal(vim.api.nvim_win_get_cursor(right), cursor))
assert(state().viewed["a.lua"] and #state().comments == 2)
tab()
await_file("renamed.lua")
-- A native refresh must retain guide order and the same current entry.
local updated = false
view:update_files(function(err)
  assert(not err, "native refresh must succeed")
  updated = true
end)
assert(vim.wait(5000, function()
  return updated
end, 20))
await_file("renamed.lua")
assert_order({ "a.lua", "renamed.lua", "b.lua" })
review.clear_active_guide_context()
vim.cmd.DiffviewClose()
settle()
-- Restore persisted Phoenix scope at a new head with zero matching files.
local empty_head = commit("ownership changes")
document.context.head_oid = empty_head
write_guide()
open(empty_head)
view = lib.get_current_view()
assert(vim.wait(5000, function()
  return view.review_scope and view.review_scope.enabled and view.files:len() == 0
end, 20))
settle()
review.show_guide_popup()
local empty_lines = vim.api.nvim_buf_get_lines(vim.api.nvim_get_current_buf(), 0, -1, false)
assert(table.concat(empty_lines, "\n"):find("No Phoenix-owned changed files", 1, true))
assert(state().viewed["a.lua"] and #state().comments == 2)
vim.api.nvim_win_close(vim.api.nvim_get_current_win(), true)
review.clear_active_guide_context()
vim.cmd.DiffviewClose()
settle()
-- Missing rules must fall back to the full diff, not silently hide every file.
vim.fn.delete(root .. "/.github/CODEOWNERS")
local missing_head = commit("remove ownership rules")
document.context.head_oid = missing_head
write_guide()
open(missing_head)
view = lib.get_current_view()
local restored_all = vim.wait(5000, function()
  return view.review_scope
    and not view.review_scope.enabled
    and view.files:len() == 5
    and state().ownership_filter == "all"
end, 20)
assert(
  restored_all,
  vim.inspect({
    files = view.files:len(),
    scope = view.review_scope and view.review_scope.enabled,
    state = state().ownership_filter,
  })
)
await_file("a.lua")
assert(state().viewed["a.lua"] and #state().comments == 2)
review.clear_active_guide_context()
vim.cmd.DiffviewClose()
settle()
vim.cmd.cd(repo)
-- Diffview's VimLeavePre logger still needs the isolated cache; Neovim cleans its temp directory.
print("diffview_review_integration: all tests passed")
