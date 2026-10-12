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
  diagram = diagram,
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
review.add_comment({ args = "saved draft", line = 2, end_line = 2 })
review.toggle_file_viewed()
assert(state().viewed["a.lua"])
local function open_skim()
  review.show_skim()
  assert(
    vim.wait(5000, function()
      return view.review_skim
        and not view.review_skim.loading
        and (view.review_skim.signature or view.review_skim.error)
    end, 20),
    "skim must build asynchronously"
  )
  local skim = view.review_skim
  assert(not skim.error, skim.error)
  return skim
end
local function skim_key(key)
  vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes(key, true, false, true), "mx", false)
end
local skim = open_skim()
assert(not vim.bo[skim.buf].modifiable and vim.bo[skim.buf].buftype == "nofile")
local persistence = require("utils.diffview_review_state")
local load_state, save_state = persistence.load, persistence.save
persistence.load, persistence.save =
  function()
    error("snapshot must not load state")
  end, function()
    error("snapshot must not save state")
  end
local snapshot_ok, snapshot = pcall(skim.snapshot)
persistence.load, persistence.save = load_state, save_state
assert(snapshot_ok and #snapshot.entries == 4, "skim status snapshots must be read-only")
local skim_lines = vim.api.nvim_buf_get_lines(skim.buf, 0, -1, false)
assert(skim_lines[1]:find("All · 4 files", 1, true))
local skim_paths = {}
for _, section in ipairs(skim.sections) do
  table.insert(skim_paths, skim.targets[section.start].path)
end
assert(vim.deep_equal(skim_paths, { "b.lua", "a.lua", "renamed.lua", "c.lua" }))
vim.api.nvim_win_call(skim.win, function()
  vim.cmd("normal! zM")
  assert(vim.fn.foldclosed(skim.sections[1].start) == skim.sections[1].start, "file sections must fold")
  vim.cmd("normal! zR")
end)
assert(table.concat(skim_lines, "\n"):find("rename from old.lua", 1, true), "skim must retain rename pairs")
local function select_skim_target(path, side, line)
  for row, target in pairs(skim.targets) do
    if target.path == path and target.side == side and target.line == line then
      vim.api.nvim_win_set_cursor(skim.win, { row, 0 })
      return row
    end
  end
  error("skim target not found")
end
local selected = select_skim_target("b.lua", "LEFT", 2)
skim_key("<CR>")
await_file("b.lua")
assert(
  vim.wait(2500, function()
    for _, file in ipairs(view.cur_entry.layout:files()) do
      if file.symbol == "a" and file.bufnr == vim.api.nvim_get_current_buf() then
        return vim.api.nvim_win_get_cursor(0)[1] == 2
      end
    end
  end, 20),
  "removed code must jump to its exact LEFT line"
)
assert(state().viewed["a.lua"] and not state().viewed["b.lua"] and #state().comments == 2)
skim = open_skim()
assert(vim.api.nvim_win_get_cursor(skim.win)[1] == selected, "returning to skim must preserve position")
select_skim_target("a.lua", "RIGHT", 2)
skim_key("<CR>")
await_file("a.lua")
assert(
  vim.wait(2500, function()
    for _, file in ipairs(view.cur_entry.layout:files()) do
      if file.symbol == "b" and file.bufnr == vim.api.nvim_get_current_buf() then
        return vim.api.nvim_win_get_cursor(0)[1] == 2
      end
    end
  end, 20),
  "added code must jump to its exact RIGHT line"
)
right = focus("b")
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
skim = open_skim()
skim_lines = vim.api.nvim_buf_get_lines(skim.buf, 0, -1, false)
assert(skim_lines[1]:find("Phoenix · 3 files", 1, true))
for _, target in pairs(skim.targets) do
  assert(target.path ~= "c.lua")
end
select_skim_target("a.lua", "RIGHT", 2)
local current_path = view.cur_entry.path
view.right.commit = base
skim_key("<CR>")
assert(
  vim.api.nvim_win_is_valid(skim.win) and view.cur_entry.path == current_path,
  "changed revisions must reject old jumps"
)
view.right.commit = head
skim_key("q")
assert(vim.wo[right].winbar:find("1/3", 1, true), "progress must use filtered denominator")
local cursor = vim.api.nvim_win_get_cursor(right)
skim = open_skim()
select_skim_target("a.lua", "RIGHT", 2)
review.show_guide_popup()
local popup = vim.api.nvim_get_current_win()
local popup_buf = vim.api.nvim_win_get_buf(popup)
local lines = vim.api.nvim_buf_get_lines(popup_buf, 0, -1, false)
for index, line in ipairs(diagram) do
  assert(lines[index + 4] == line)
end
assert(not vim.wo[popup].wrap, "diagram must not wrap")
assert(not table.concat(lines, "\n"):find("4. c.lua", 1, true), "route must use visible scope")
assert(table.concat(lines, "\n"):find("Context: c.lua", 1, true), "diagram keeps full PR context")
local notifications, original_notify = {}, vim.notify
vim.notify = function(message, ...)
  table.insert(notifications, message)
  original_notify(message, ...)
end
-- Simulate Pi atomically updating the guide during conversation.
document.summary = "Updated understanding."
document.files = { document.files[2], document.files[3], document.files[1], document.files[4] }
local temp = path .. ".tmp"
vim.fn.writefile({ vim.json.encode(document) }, temp)
assert((vim.uv or vim.loop).fs_rename(temp, path))
assert(
  vim.wait(2500, function()
    return vim.api.nvim_buf_get_lines(popup_buf, 2, 3, false)[1] == "Updated understanding."
  end, 20),
  "guide must reload through agent polling"
)
assert(view.cur_entry.path == "a.lua" and vim.deep_equal(vim.api.nvim_win_get_cursor(right), cursor))
assert_order({ "a.lua", "renamed.lua", "b.lua" })
assert(state().viewed["a.lua"] and state().ownership_filter == "phoenix" and #state().comments == 2)
assert(table.concat(notifications, "\n"):find("review order updated", 1, true))
assert(
  vim.wait(1500, function()
    return skim.outdated
  end, 20),
  "live guide order changes must mark skim outdated"
)
vim.api.nvim_set_current_win(skim.win)
skim_key("<CR>")
assert(vim.api.nvim_win_is_valid(skim.win) and view.cur_entry.path == "a.lua", "outdated skim must not navigate")
skim_key("r")
assert(vim.wait(5000, function()
  return not skim.loading and not skim.outdated
end, 20))
local preserved = skim.targets[vim.api.nvim_win_get_cursor(skim.win)[1]]
assert(
  preserved.path == "a.lua" and preserved.side == "RIGHT" and preserved.line == 2,
  "refresh must preserve the current change"
)
skim_paths = {}
for _, section in ipairs(skim.sections) do
  table.insert(skim_paths, skim.targets[section.start].path)
end
assert(vim.deep_equal(skim_paths, { "a.lua", "renamed.lua", "b.lua" }))
skim_key("q")
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
assert(
  not vim.api.nvim_buf_is_valid(skim.buf) and skim.timer == nil and skim.disposed,
  "closing review must clean up skim"
)
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
skim = open_skim()
local empty_skim = table.concat(vim.api.nvim_buf_get_lines(skim.buf, 0, -1, false), "\n")
assert(empty_skim:find("No matching changed files", 1, true) and next(skim.targets) == nil)
skim_key("q")
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
