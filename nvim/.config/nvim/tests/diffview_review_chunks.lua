-- SETUP: Real Git fixtures separate same-file/cross-file hunks and unequal revision lengths.
local repo = vim.fn.getcwd()
local plugin = vim.env.DIFFVIEW_PLUGIN or (vim.fn.stdpath("data") .. "/lazy/diffview.nvim")
vim.opt.runtimepath:append(repo .. "/nvim/.config/nvim")
vim.opt.runtimepath:append(plugin)
local root = vim.fn.tempname()
vim.fn.mkdir(root, "p")
vim.env.XDG_CACHE_HOME = root .. "/cache"
local function git(...)
  local args = { "git", "-C", root }
  vim.list_extend(args, { ... })
  local result = vim.system(args, { text = true }):wait()
  assert(result.code == 0, result.stderr)
  return vim.trim(result.stdout)
end
local function commit(label)
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
    label
  )
  return git("rev-parse", "HEAD")
end
local function write(path, lines)
  vim.fn.writefile(lines, root .. "/" .. path)
end
git("init", "-q")
git("config", "diff.suppressBlankEmpty", "true")
git("config", "core.filemode", "true")
vim.fn.mkdir(root .. "/.github", "p")
write(".github/CODEOWNERS", { "*.lua @ZiplineTeam/phoenix-reviewers", "b.lua @other/team" })
local source = {}
for number = 1, 90 do
  source[number] = "local value_" .. number .. " = " .. number
end
write("a.lua", source)
write("b.lua", { "old_b()" })
write("old name.lua", { "unchanged()" })
write("empty.txt", {})
git("add", ".")
local base = commit("base")
source[10], source[60] = "local value_10 = 1000", "local value_60 = 6000"
write("a.lua", source)
assert(vim.uv.fs_chmod(root .. "/a.lua", 493))
write("b.lua", { "new_b()", "prepare()", "complete()" })
git("mv", "old name.lua", "new name.lua")
git("rm", "empty.txt")
local head = commit("head")
local chunks = require("utils.diffview_review_chunks")
-- TEST: Partition the pinned inventory, then exercise the same ranges in real Diffview.
local catalog, err = chunks.inventory(root, base, head)
assert(catalog, err) -- VERIFY: Later ownership/progress checks use Git-derived identities.
assert(#catalog.hunks == 5, "two separated hunks, one b.lua hunk, deletion and rename")
assert(vim.deep_equal(catalog, chunks.inventory(root, base, head)), "hunk identity is deterministic")
local a, b, metadata = {}, nil, {}
for _, hunk in ipairs(catalog.hunks) do
  if hunk.path == "a.lua" then
    table.insert(a, hunk)
  elseif hunk.path == "b.lua" then
    b = hunk
  else
    table.insert(metadata, hunk.id)
  end
end
assert(#a == 2 and a[1].right_start == 7 and a[2].right_start == 57)
assert(chunks.jump_source(a[1], catalog).line == 10 and chunks.jump_source(a[2], catalog).line == 60)
assert(a[1].file_change:find("100755", 1, true), "code hunks retain their accompanying file-attribute change")
for _, hunk in ipairs(catalog.hunks) do
  if hunk.path == "empty.txt" then
    assert(hunk.kind == "file" and chunks.source(hunk).side == "LEFT")
  end
end
local hidden = chunks.hidden_ranges({ a[1] }, "a.lua", "RIGHT", 90)
assert(vim.deep_equal(hidden, { { 1, 6 }, { 14, 90 } }), "focus hides the other hunk, retaining pinned line numbers")
assert(not chunks.hidden_ranges({ a[1] }, "a.lua", "RIGHT", 1), "unloaded or invalid ranges must not be clamped")
local document = {
  context = { base_oid = base, head_oid = head },
  summary = "Two mechanisms in one file.",
  diagram = { "entry → configuration → runtime" },
  core_code = {
    {
      id = "runtime",
      label = "Source excerpt",
      title = "PR entry point",
      code = { "new_b()" },
      sources = { { path = "b.lua", side = "RIGHT", line = 1, revision = head } },
    },
  },
  files = {
    {
      path = "a.lua",
      suggestions = {
        { id = "runtime-question", side = "RIGHT", line = 60, body = "Question: Is value_60 validated?" },
      },
    },
    { path = "b.lua" },
    { path = "empty.txt" },
    { path = "new name.lua" },
  },
  chunks = {
    {
      id = "configuration",
      title = "Configuration",
      summary = "Change value_10 and its caller.",
      relationship = "Entry → [Configuration] → Runtime",
      diagram = { "new_b → value_10" },
      hunks = { b.id, a[1].id },
      checks = { "Check the caller contract" },
    },
    {
      id = "runtime",
      title = "Runtime",
      summary = "Change value_60 without changing value_10 again.",
      depends_on = { "configuration" },
      hunks = { a[2].id },
      core_code = {
        {
          id = "1",
          label = "Source excerpt",
          title = "value_60 at head",
          code = { source[60] },
          sources = { { path = "a.lua", side = "RIGHT", line = 60, revision = head } },
        },
      },
    },
    {
      id = "support",
      title = "Supporting changes",
      summary = "Rename a file and remove an empty file.",
      depends_on = { "runtime" },
      depth = "skim",
      hunks = metadata,
    },
  },
}
local plan = assert(chunks.plan(catalog, document))
assert(plan.owner[a[1].id] ~= plan.owner[a[2].id], "one file can belong to multiple semantic chunks")
for _, kind in ipairs({ "missing", "duplicate", "unknown", "boundary", "dependency" }) do
  local invalid = vim.deepcopy(document)
  if kind == "missing" then
    table.remove(invalid.chunks[1].hunks)
  elseif kind == "duplicate" then
    table.insert(invalid.chunks[2].hunks, a[1].id)
  elseif kind == "unknown" then
    invalid.chunks[1].hunks[1] = "invented"
  elseif kind == "boundary" then
    invalid.context.head_oid = base
  else
    invalid.chunks[1].depends_on = { "runtime" }
  end
  assert(not chunks.plan(catalog, invalid), "reject " .. kind .. " plans")
end
local guide_path = root .. "/guide.json"
local function save_guide()
  write("guide.json", { vim.json.encode(document) })
end
save_guide()
vim.cmd.cd(root)
vim.cmd.runtime("plugin/diffview.lua")
local review = require("utils.diffview_review")
require("diffview").setup({
  use_icons = false,
  keymaps = review.diffview_keymaps(),
  default_args = { DiffviewOpen = { "--imply-local" } },
})
review.setup()
review.set_active_guide_context({
  repo = root,
  path = guide_path,
  base_oid = base,
  head_oid = head,
  diffview_rev_arg = base .. ".." .. head,
  assistant_name = "fixture",
})
assert(git("rev-parse", "HEAD") == head)
vim.cmd("DiffviewOpen --imply-local=false " .. base .. ".." .. head)
local view = require("diffview.lib").get_current_view()
assert(view.left.commit == base and view.right.commit == head, "review keeps checkout HEAD pinned")
assert(vim.wait(3000, function()
  return view.cur_entry and view.cur_entry.opened
end))
review.refresh_visible()
local workspace = view.review_chunks
assert(workspace and workspace.plan and #workspace.plan.chunks == 3, workspace and workspace.error)
assert(
  vim.wait(3000, function()
    return workspace.active == "configuration"
      and view.cur_entry
      and view.cur_entry.opened
      and view.cur_entry.path == "b.lua"
  end),
  "a new review focuses its first section"
)
assert(vim.fn.filereadable(root .. "/review-hunks.json") == 1, "Pi receives the exact immutable inventory")
local function source_window(side)
  local result
  for _, file in ipairs(view.cur_entry.layout:files()) do
    if (file.symbol == "a" and "LEFT" or "RIGHT") == side and file.bufnr then
      for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
        if vim.api.nvim_win_get_buf(win) == file.bufnr then
          result = win
        end
      end
    end
  end
  return result
end
local function details()
  for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
    local buffer = vim.api.nvim_win_get_buf(win)
    if vim.b[buffer].diffview_review_panel then
      return table.concat(vim.api.nvim_buf_get_lines(buffer, 0, -1, false), "\n"), win
    end
  end
  error("Missing integrated chunk explanation")
end
local function at_hunk(chunk_id, hunk)
  review.chunk_action("open", { chunk_id = chunk_id, hunk_id = hunk.id })
  assert(
    vim.wait(3000, function()
      local win = source_window("RIGHT")
      return view.cur_entry.path == hunk.path
        and view.cur_entry.opened
        and win
        and vim.api.nvim_get_current_win() == win
        and vim.api.nvim_win_get_cursor(win)[1] == chunks.jump_source(hunk, workspace.catalog).line
    end),
    "wait for the exact pinned hunk: "
      .. vim.inspect({
        wanted = hunk.path,
        actual = view.cur_entry.path,
        opened = view.cur_entry.opened,
        current = vim.api.nvim_get_current_win(),
        right = source_window("RIGHT"),
        scope = view.review_scope.enabled,
        line = source_window("RIGHT") and vim.api.nvim_win_get_cursor(source_window("RIGHT"))[1],
      })
  )
  review.refresh_visible()
end
local state_module = require("utils.diffview_review_state")
local ctx = { root = root, state_path = root .. "/diffview-review.json", view = view }
review.show_guide_popup()
local overview = vim.api.nvim_get_current_win()
local route_row
for number, line in ipairs(vim.api.nvim_buf_get_lines(0, 0, -1, false)) do
  if line:find("1. Configuration", 1, true) then
    route_row = number
    break
  end
end
assert(route_row, "the whole-PR overview links to its semantic chunks")
local route_line = vim.api.nvim_buf_get_lines(0, route_row - 1, route_row, false)[1]
local route_marks = vim.api.nvim_buf_get_extmarks(
  0,
  vim.api.nvim_create_namespace("diffview_review_panel"),
  { route_row - 1, 0 },
  { route_row - 1, -1 },
  { details = true }
)
assert(
  vim.iter(route_marks):any(function(mark)
    return mark[4].hl_group == "DiffviewReviewGuideSubheading"
      and route_line:sub(mark[3] + 1, mark[4].end_col) == "1. Configuration"
  end),
  "only the numbered title gets the section heading style"
)
vim.api.nvim_win_set_cursor(overview, { route_row, 0 })
local before_section = state_module.load(ctx, error)
assert(vim.api.nvim_get_current_line():find("[--------] 0/2", 1, true))
vim.api.nvim_feedkeys("v", "mx", false)
local section_state = state_module.load(ctx, error)
assert(chunks.read_count(plan.chunks[1].hunks, section_state) == 2, "overview v persists the entire cross-file section")
assert(not section_state.read_hunks[a[2].id], "section actions do not mark another section")
assert(
  vim.api.nvim_get_current_line():find("[████████] 2/2", 1, true)
    and vim.api.nvim_get_current_win() == overview
)
assert(
  vim.deep_equal(before_section.comments, section_state.comments)
    and vim.deep_equal(before_section.viewed, section_state.viewed)
)
vim.api.nvim_feedkeys("v", "mx", false)
assert(
  chunks.read_count(plan.chunks[1].hunks, state_module.load(ctx, error)) == 0,
  "viewed sections toggle back to unread"
)
vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("<CR>", true, false, true), "mx", false)
assert(
  vim.wait(3000, function()
    return workspace.active == "configuration"
      and view.cur_entry.path == "b.lua"
      and source_window("RIGHT")
      and vim.api.nvim_get_current_win() == source_window("RIGHT")
  end),
  "overview Enter opens the integrated workspace"
)
local explanation, panel_win = details()
assert(
  explanation:find("new_b → value_10", 1, true) and vim.api.nvim_win_get_config(panel_win).relative == "",
  "overview selection docks the granular explanation"
)
assert(vim.api.nvim_win_get_position(panel_win)[2] == 0, "Guide docks to the left of the diff")
assert(
  vim.wo[panel_win].winhl:find("NormalNC:NormalFloat", 1, true),
  "Guide keeps its floating background when source navigation takes focus"
)
assert(
  explanation:find("## 🧭 PR overview", 1, true)
    and explanation:find(document.summary, 1, true)
    and explanation:find(document.diagram[1], 1, true)
    and explanation:find("## 🔬 Section 1: Configuration", 1, true)
    and explanation:find("### 🗺️ Section diagram", 1, true)
    and explanation:find("### 👀 What to look for", 1, true)
    and explanation:find("────────────────", 1, true),
  "one guide separates the whole-PR overview, section guide and checks with emoji headings and rules"
)
assert(explanation:find(document.diagram[1], 1, true) < explanation:find("📚 Review sections", 1, true))
assert(explanation:find("👀 What to look for", 1, true) < explanation:find("🗺️ Section diagram", 1, true))
local combined = review.show_guide_popup()
assert(combined.mode == "guide" and not combined.expanded, "opening the active guide keeps it beside the diff")
local route_cursor = vim.api.nvim_win_get_cursor(combined.winid)[1]
assert(combined.sections[route_cursor].id == "chunk:configuration", "section navigation leaves the cursor in the list")
assert(explanation:find("▶ ○ 1. After ", 1, true), "hunk rows identify the current hunk and the source side")
local source_buffer = vim.api.nvim_win_get_buf(source_window("RIGHT"))
local before_layout = state_module.load(ctx, error)
local function heading_row(id)
  for row, section in pairs(combined.sections) do
    if section.id == id then
      return row
    end
  end
  error("Missing guide heading: " .. id)
end
local function assert_section_list(key, active)
  vim.api.nvim_feedkeys(key, "mx", false)
  assert(workspace.active == active)
  assert(
    vim.api.nvim_win_call(panel_win, function()
      return vim.fn.line("w0") == heading_row("route") and vim.fn.line(".") == heading_row("route")
    end),
    key .. " puts Review sections at the top of Guide"
  )
  local expanded = 0
  for row, target in pairs(combined.targets) do
    if target.hunk_id then
      assert(target.chunk_id == active and row > heading_row("chunk:" .. active))
      assert(vim.api.nvim_buf_get_lines(combined.buffer, row - 1, row, false)[1]:match("^    • "))
      expanded = expanded + 1
    end
  end
  assert(expanded == #workspace.plan.by_id[active].hunks)
end
vim.wo[panel_win].scrolloff = 10
assert_section_list("]r", "runtime")
assert(
  vim.wait(3000, function()
    return vim.api.nvim_get_current_win() == source_window("RIGHT")
  end),
  "section navigation returns focus to the diff"
)
assert_section_list("[r", "configuration")
assert(vim.api.nvim_win_get_width(panel_win) == math.floor(vim.o.columns / 4))
vim.api.nvim_set_current_win(panel_win)
for index, id in ipairs({ "overview", "route", "section:purpose:configuration" }) do
  vim.api.nvim_feedkeys("g" .. index, "mx", false)
  assert(vim.fn.line(".") == heading_row(id) and vim.fn.line("w0") == heading_row(id))
end
vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("<Tab>", true, false, true), "mx", false)
assert(combined.mode == "threads")
vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("<S-Tab>", true, false, true), "mx", false)
assert(combined.mode == "guide" and details():find(document.summary, 1, true))
assert(
  workspace.active == "configuration"
    and vim.api.nvim_win_get_buf(source_window("RIGHT")) == source_buffer
    and view.left.commit == base
    and view.right.commit == head
    and vim.deep_equal(before_layout, state_module.load(ctx, error)),
  "guide layout controls preserve pinned source, comments and read progress"
)
vim.api.nvim_set_current_win(source_window("RIGHT"))
at_hunk("configuration", b)
assert(
  vim.api.nvim_buf_line_count(vim.api.nvim_get_current_buf()) == 3,
  "unequal before/after hunk lengths remain intact"
)
at_hunk("configuration", a[1])
assert(
  details():find("new_b → value_10", 1, true) and not details():find("Question: Is value_60", 1, true),
  "the integrated explanation and comments follow the active chunk"
)
local win = source_window("RIGHT")
assert(vim.api.nvim_win_call(win, function()
  return vim.fn.foldclosed(60)
end) >= 0, "the other semantic chunk is folded, not displayed as part of this review")
assert(vim.api.nvim_win_call(win, function()
  return vim.fn.foldclosed(10)
end) == -1)
assert(
  vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(win), 59, 60, false)[1] == source[60],
  "underlying revision buffers remain intact"
)
local paths = {}
for _, entry in ipairs(view.panel:ordered_file_list()) do
  table.insert(paths, entry.path)
end
assert(vim.deep_equal(paths, { "b.lua", "a.lua" }), "file panel follows the active chunk, not the full PR")
review.chunk_action("read")
local state = state_module.load(ctx, error)
assert(state.read_hunks[a[1].id] and not state.viewed["a.lua"], "hunk progress is not whole-file progress")
assert(chunks.read_count(plan.chunks[1].hunks, state) == 1)
assert(details():find("Hunks viewed     [████----] 1/2", 1, true))
assert(details():find("Sections viewed  [--------] 0/3", 1, true))
assert(details():find("Overall review  [█-------] 1/5 hunks", 1, true))
assert(vim.wo[win].winbar:match("Review %[[^%]]+%] 1/5"), "overall progress is visible while reading the diff")
review.show_guide_popup()
local _, section_win = details()
vim.api.nvim_win_set_cursor(section_win, { 1, 0 })
vim.api.nvim_feedkeys("V", "mx", false)
assert(
  chunks.read_count(plan.chunks[1].hunks, state_module.load(ctx, error)) == 2,
  "V completes the active partial section"
)
vim.api.nvim_feedkeys("V", "mx", false)
assert(chunks.read_count(plan.chunks[1].hunks, state_module.load(ctx, error)) == 0)
review.chunk_action("read", { chunk_id = "configuration", hunk_id = a[1].id })
vim.api.nvim_set_current_win(win)
local guide_position = vim.api.nvim_win_get_cursor(section_win)
vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("<Tab>", true, false, true), "mx", false)
assert(
  vim.wait(3000, function()
    return workspace.active == "configuration"
      and view.cur_entry.path == "b.lua"
      and source_window("RIGHT") == vim.api.nvim_get_current_win()
  end),
  "Tab wraps to the first hunk without leaving its section"
)
assert(vim.deep_equal(guide_position, vim.api.nvim_win_get_cursor(section_win)))
vim.api.nvim_feedkeys("]r", "mx", false)
assert(vim.wait(3000, function()
  return workspace.active == "runtime"
    and source_window("RIGHT")
    and vim.api.nvim_get_current_win() == source_window("RIGHT")
end))
win = source_window("RIGHT")
assert(
  details():find("value_60 at head", 1, true) and details():find("Question: Is value_60", 1, true),
  "core code and anchored questions are integrated with this chunk"
)
local thread_view = require("utils.diffview_review_threads")
local review_state = state_module.load(ctx, error)
local thread
for _, comment in ipairs(review_state.comments) do
  if comment.body:find("Question: Is value_60", 1, true) then
    thread = comment
    break
  end
end
assert(thread)
local thread_lines = thread_view.lines(review_state, thread_view.identity(thread), nil, workspace.plan)
assert(table.concat(thread_lines, "\n"):find("Section: 2. " .. workspace.plan.by_id.runtime.title, 1, true))
assert(table.concat(thread_lines, "\n"):find("Hunk: 1 · After ", 1, true))
assert(#chunks.comment_hunks(workspace.plan, { file = "a.lua", side = "RIGHT", line = 10, end_line = 60 }) == 2)
local headings = {}
for _, section in pairs(combined.sections) do
  assert(not headings[section.id], "overview and section reading anchors must not collide: " .. section.id)
  headings[section.id] = true
end
assert(
  headings["core:runtime:1"] and headings["section:core:runtime:1"],
  "both levels retain independent core-code anchors"
)
assert(details():find("PR entry point", 1, true) and details():find(document.diagram[1], 1, true))
assert(vim.api.nvim_win_call(win, function()
  return vim.fn.foldclosed(10)
end) >= 0)
assert(vim.api.nvim_win_call(win, function()
  return vim.fn.foldclosed(60)
end) == -1)
vim.api.nvim_win_set_cursor(win, { 61, 2 })
review.chunk_action("open", { chunk_id = "configuration" })
assert(vim.wait(3000, function()
  return workspace.active == "configuration"
    and source_window("RIGHT")
    and vim.api.nvim_get_current_win() == source_window("RIGHT")
end))
review.chunk_action("open", { chunk_id = "runtime" })
assert(
  vim.wait(3000, function()
    return workspace.active == "runtime"
      and source_window("RIGHT")
      and vim.api.nvim_win_get_cursor(source_window("RIGHT"))[1] == 61
  end),
  "chunk navigation restores its source reading position"
)
vim.api.nvim_set_current_win(combined.winid)
vim.api.nvim_feedkeys("q", "mx", false)
local function step_with_guide_closed(key, active, line)
  vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes(key, true, false, true), "mx", false)
  assert(
    vim.wait(3000, function()
      local right = source_window("RIGHT")
      return workspace.active == active
        and right
        and vim.api.nvim_get_current_win() == right
        and vim.api.nvim_win_get_cursor(right)[1] == line
    end),
    key .. " jumps to the pinned diff"
  )
  assert(not combined.winid, key .. " leaves Guide closed")
end
step_with_guide_closed("<S-Tab>", "runtime", 60)
step_with_guide_closed("<Tab>", "runtime", 60)
step_with_guide_closed("[r", "configuration", 1)
step_with_guide_closed("]r", "runtime", 60)
win = source_window("RIGHT")
vim.api.nvim_win_set_cursor(win, { 61, 2 })
local before = state_module.load(ctx, error)
document.chunks[2].title = "Runtime refinement"
document.chunks[2].summary = "More precise explanation of value_60."
save_guide()
require("utils.diffview_review_guide").cache = nil
review.refresh_visible()
assert(workspace.active == "runtime" and vim.api.nvim_win_get_cursor(win)[1] == 61)
assert(vim.deep_equal(before, state_module.load(ctx, error)), "refinement does not change comments or progress")
local guide_panel = review.show_guide_popup()
local link_row
for row, target in pairs(guide_panel.targets) do
  if target.path == "b.lua" and target.line == 1 then
    link_row = row
    break
  end
end
assert(link_row, "overview links to another section")
vim.api.nvim_win_set_cursor(guide_panel.winid, { link_row, 0 })
vim.api.nvim_feedkeys(vim.keycode("<CR>"), "mx", false)
assert(vim.wait(3000, function()
  return workspace.active == "configuration" and vim.api.nvim_get_current_win() == source_window("RIGHT")
end))
assert(vim.api.nvim_win_call(guide_panel.winid, vim.api.nvim_get_current_line):find("↗ b.lua:1", 1, true))
at_hunk("configuration", a[1])
local threads_panel = review.show_threads({ selected = thread_view.identity(thread) })
for row, id in pairs(threads_panel.rows) do
  if id == thread_view.identity(thread) then
    vim.api.nvim_win_set_cursor(threads_panel.winid, { row, 0 })
    break
  end
end
vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("<CR>", true, false, true), "mx", false)
assert(
  vim.wait(3000, function()
    local right = source_window("RIGHT")
    return workspace.active == "runtime"
      and right
      and vim.api.nvim_get_current_win() == right
      and vim.api.nvim_win_get_cursor(right)[1] == 60
  end),
  "Enter switches sections and opens the exact comment line in Diffview"
)
vim.api.nvim_feedkeys(vim.keycode("<Esc>"), "mx", false)
assert(vim.api.nvim_get_current_win() == threads_panel.winid)
assert(threads_panel.rows[vim.api.nvim_win_get_cursor(0)[1]] == thread_view.identity(thread))
document.chunks[1].hunks, document.chunks[2].hunks = { b.id }, { a[1].id, a[2].id }
save_guide()
require("utils.diffview_review_guide").cache = nil
review.chunk_action("viewed", { chunk_id = "runtime" })
assert(
  vim.deep_equal(before, state_module.load(ctx, error)),
  "a just-regrouped section must not mark unseen hunks read"
)
assert(workspace.active == "runtime" and workspace.plan.owner[a[1].id] == "runtime")
assert(state_module.load(ctx, error).read_hunks[a[1].id], "regrouping does not reset hunk progress")
local valid_plan = workspace.plan
table.remove(document.chunks[2].hunks, 1)
document.files[1].suggestions = {}
save_guide()
require("utils.diffview_review_guide").cache = nil
review.refresh_visible()
assert(
  workspace.plan == valid_plan and workspace.error:find("Unassigned"),
  "invalid updates cannot replace a valid partition"
)
assert(vim.deep_equal(before, state_module.load(ctx, error)), "an invalid update cannot prune existing discussions")
review.toggle_ownership_filter()
assert(
  vim.wait(5000, function()
    return view.review_scope.enabled and view.files:len() == 2
  end),
  "ownership scope: "
    .. vim.inspect({
      enabled = view.review_scope.enabled,
      count = view.files:len(),
      paths = vim.tbl_map(function(entry)
        return entry.path
      end, view.panel:ordered_file_list()),
      scope = state_module.load(ctx, error).ownership_filter,
    })
)
local scoped_state = state_module.load(ctx, error)
review.show_guide_popup()
local _, scoped_win = details()
for row, line in ipairs(vim.api.nvim_buf_get_lines(0, 0, -1, false)) do
  if line:find("1. Configuration", 1, true) then
    vim.api.nvim_win_set_cursor(scoped_win, { row, 0 })
    break
  end
end
vim.api.nvim_feedkeys("V", "mx", false)
assert(
  vim.deep_equal(scoped_state, state_module.load(ctx, error)),
  "a section action cannot mark ownership-hidden hunks"
)
local counts = require("utils.diffview_review_panel").counts(state_module.load(ctx, error), {}, workspace)
assert(
  counts.total == 3 and #workspace.catalog.hunks == 5,
  "ownership filters progress, not canonical coverage, and retains renamed owned files"
)
assert(details():find("Overall review  [█-------] 1/5 hunks", 1, true), "overall progress ignores ownership filters")
assert(
  not require("utils.diffview_review_chunk_workspace").can_read(ctx, b),
  "out-of-scope hunks cannot be marked read"
)
review.toggle_ownership_filter()
assert(vim.wait(5000, function()
  return not view.review_scope.enabled and view.files:len() == 4
end))
review.chunk_action("all")
assert(not workspace.active and vim.wo[win].foldmethod ~= "manual", "all-changes restores native diff folds")
assert(#view.panel:ordered_file_list() == 4, "leaving chunk focus restores the full file panel")
assert(state_module.load(ctx, error).read_hunks[a[1].id], "progress survives leaving section focus")
local all_counts = require("utils.diffview_review_panel").counts(state_module.load(ctx, error), {}, workspace)
assert(all_counts.unit == " hunks" and all_counts.total == 5, "All changed files keeps hunk-based review progress")
review.clear_active_guide_context()
vim.cmd.DiffviewClose()
vim.wait(200)
assert(vim.v.errmsg == "", vim.v.errmsg)
vim.cmd.cd(repo)
-- Keep the isolated cache alive until Diffview's VimLeavePre logger finishes.
print(
  "diffview_review_chunks: inventory, coverage, focused native diffs, navigation, progress and stable updates passed"
)
