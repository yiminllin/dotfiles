vim.opt.runtimepath:append("nvim/.config/nvim")
local review = require("utils.diffview_review")

-- Exercise private helpers through their owning actions, without adding a public test API.
local function helper(name)
  local seen = {}
  local function search(fn)
    if seen[fn] then
      return
    end
    seen[fn] = true
    local children = {}
    for index = 1, 200 do
      local key, value = debug.getupvalue(fn, index)
      if not key then
        break
      end
      if key == name then
        return value
      end
      if type(value) == "function" then
        table.insert(children, value)
      end
    end
    for _, child in ipairs(children) do
      local found = search(child)
      if found then
        return found
      end
    end
  end
  for _, fn in pairs(review) do
    if type(fn) == "function" then
      local found = search(fn)
      if found then
        return found
      end
    end
  end
  error("Missing helper: " .. name)
end

local normalize = require("utils.diffview_review_guide").normalize
local guide = normalize({
  context = { pr_number = 42 },
  files = {
    {
      path = "b.lua",
      suggestions = {
        { id = "deleted-check", side = "LEFT", line = 2, body = "Why remove this?" },
      },
    },
    { path = "a.lua" },
  },
})
assert(guide.pr_number == 42 and guide.files[1].notes == nil and guide.files[1].depth == nil)
assert(guide.files[1].suggestions[1].side == "LEFT")
local state = { comments = {} }
helper("import_guide_comments")(state, guide)
assert(state.comments[1].side == "LEFT", "guide import must preserve side")
state.comments[1].resolved = true
helper("import_guide_comments")(state, guide)
assert(state.comments[1].resolved, "guide reload must preserve local resolution")
guide.source_path = "/fixture/guide.json"
helper("import_guide_comments")(state, guide)
state.comments[1].replies = { { author = "you", body = "Discussion worth retaining." } }
helper("import_guide_comments")(state, { source_path = guide.source_path, files = {} })
assert(
  #state.comments == 1 and state.comments[1].guide_retired,
  "guide updates must retain discussions and resolutions"
)
assert(require("utils.diffview_review_format").comment_status_text(state.comments[1]):find("earlier guide", 1, true))
helper("import_guide_comments")(state, guide)
assert(
  not state.comments[1].guide_retired and #state.comments[1].replies == 1,
  "returning guide items reconnect to their thread"
)

assert(helper("truncate_display")("abcdefgh", 4) == "abc…", "posting previews retain bounded text")

local ordered = helper("review_entries")({
  panel = {
    ordered_file_list = function()
      return { { path = "b.lua" }, { path = "a.lua" }, { path = "c.lua" } }
    end,
  },
}, { viewed = { ["a.lua"] = true } })
assert(
  #ordered == 3 and ordered[1].path == "b.lua" and ordered[2].path == "a.lua" and ordered[3].path == "c.lua",
  "review consumers must keep native panel order"
)
assert(ordered[2].viewed)

local github = helper("normalize_github_comment")({
  id = 1,
  path = "a.lua",
  line = 10,
  start_line = 7,
  side = "LEFT",
  body = "range",
}, { ["a.lua"] = true })
assert(github.line == 7 and github.end_line == 10 and github.github_line == 10)
local first, last = helper("clamp_comment_range")(github, 30)
assert(first == 7 and last == 10)
assert(helper("clamp_comment_range")(github, 5) == nil, "invalid coordinates must not move to the last line")
assert(github.side == "LEFT")
assert(
  helper("is_hidden_comment")({ source = "github", local_resolved = true }),
  "local GitHub resolution must survive remote refresh"
)

local bufnr = vim.api.nvim_get_current_buf()
local symbol = "a"
local ctx = {
  file = "a.lua",
  view = {
    cur_entry = {
      layout = {
        files = function()
          return { { bufnr = bufnr, symbol = symbol } }
        end,
      },
    },
  },
}
local select_comment = helper("select_current_comment")
local left = { file = "a.lua", side = "LEFT", line = 2, body = "left" }
local right = { file = "a.lua", side = "RIGHT", line = 2, body = "right" }
local selected
select_comment(ctx, { comments = { right, left } }, { line = 2 }, function(comment)
  selected = comment
end)
assert(selected == left, "left action must not select a right-side comment at the same line")
symbol = "b"
select_comment(ctx, { comments = { left, right } }, { line = 2 }, function(comment)
  selected = comment
end)
assert(selected == right)
local file_note = { file = "a.lua", file_level = true, body = "file note" }
for _, side in ipairs({ "a", "b" }) do
  symbol = side
  select_comment(ctx, { comments = { file_note } }, { line = 50 }, function(comment)
    selected = comment
  end)
  assert(selected == file_note, "file-level actions must not depend on a display line")
end
local original_select = vim.ui.select
vim.ui.select = function(items, opts, callback)
  assert(opts.format_item(items[2]):find("file note", 1, true))
  callback(items[2])
end
select_comment(ctx, { comments = { right, file_note } }, { line = 2 }, function(comment)
  selected = comment
end)
assert(selected == file_note, "overlapping comments require explicit selection")
vim.ui.select = original_select
vim.bo[bufnr].filetype = "DiffviewFiles"
select_comment(ctx, { comments = { right, file_note } }, { line = 2 }, function(comment)
  selected = comment
end)
assert(selected == file_note, "file panel must only target file-level comments")
vim.bo[bufnr].filetype = ""

local temp_dir = vim.fn.tempname()
vim.fn.mkdir(temp_dir, "p")
local path = temp_dir .. "/guide.json"
local root = vim.fn.getcwd()
local view = { rev_arg = "base..head", adapter = { ctx = { toplevel = root, dir = root .. "/.git" } } }
local repo_context = helper("repo_context")(view)
assert(repo_context.view == view, "repository context must retain the view for boundary checks")
assert(
  helper("active_pr_context_matches_view")({ diffview_rev_arg = view.rev_arg }, repo_context),
  "initial guide navigation must recognize the active diff boundary"
)
review.set_active_guide_context({ repo = root, path = path, base_oid = "base", head_oid = "head" })
assert(
  helper("is_hidden_comment")({ source = "github", github_head_oid = "old" }),
  "cached GitHub coordinates from another snapshot must stay hidden"
)
assert(not helper("is_hidden_comment")({ source = "github", github_head_oid = "head" }))
local function write_guide(head, summary)
  vim.fn.writefile(
    { vim.json.encode({ context = { base_oid = "base", head_oid = head }, summary = summary, files = {} }) },
    path
  )
end
write_guide("head", "first")
local load = helper("load_active_guide")
assert(load({ root = root }).summary == "first")
write_guide("head", "updated immediately")
assert(load({ root = root }).summary == "updated immediately", "cache must notice rapid guide writes")
write_guide("old-head", "stale")
assert(load({ root = root }) == nil, "guidance from another revision must not load")
vim.fn.delete(temp_dir, "rf")
review.clear_active_guide_context()
review.set_active_guide_context({ repo = root, path = path, assistant_name = vim.NIL })
assert(helper("active_guide_context").assistant_name == nil, "JSON null must disable agent polling")
review.start_agent_reply_polling({ root = root, state_path = temp_dir .. "/state.json" })
assert(review.agent_reply_poll_timer == nil)
review.clear_active_guide_context()

local original_systemlist = vim.fn.systemlist
local original_executable = vim.fn.executable
vim.fn.executable = function(name)
  return name == "gh" and 1 or original_executable(name)
end
local calls = 0
vim.fn.systemlist = function()
  calls = calls + 1
  return { "different-head" }
end
local comments, err =
  helper("fetch_github_comments")({ owner = "owner", repo = "repo", pull_number = "42", head_oid = "head" })
assert(comments == nil and err:find("revision", 1, true) and calls == 1)
calls = 0
vim.fn.systemlist = function(args)
  calls = calls + 1
  assert(vim.tbl_contains(args, "--slurp"), "GitHub pagination must use structured JSON")
  original_systemlist({ "false" })
  return { "unknown flag: --slurp" }
end
comments, err = helper("fetch_github_comments")({ owner = "owner", repo = "repo", pull_number = "42" })
assert(comments == nil and err:find("--slurp", 1, true) and calls == 1, "old gh must fail without a second request")
vim.fn.systemlist = original_systemlist
vim.fn.executable = original_executable
original_systemlist({ "true" })

for _, maps in pairs(review.diffview_keymaps()) do
  local refresh, skim = false, false
  for _, map in ipairs(maps) do
    assert(map[2] ~= "<Tab>" and map[2] ~= "<S-Tab>", "native navigation must not be overridden")
    refresh = refresh or map[2] == "<leader>gdR"
    skim = skim or (map[2] == "<leader>gdV" and map[3] == review.show_skim)
    assert(map[2] ~= "<leader>gdj" and map[2] ~= "<leader>gdk", "duplicate guide navigation must be removed")
    assert(map[2] ~= "<leader>gdS" and map[2] ~= "<leader>gdU", "redundant dashboards must be removed")
    assert(type(map[3]) == "function")
  end
  assert(refresh and skim)
end
print("diffview_review_workflow: all tests passed")
