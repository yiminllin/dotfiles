vim.opt.runtimepath:append("nvim/.config/nvim")
local owners = require("utils.codeowners")
local guide = require("utils.diffview_review_guide")
local state = require("utils.diffview_review_state")
local phoenix = "@ZiplineTeam/phoenix-reviewers"
local rules = owners.parse({
  "/ash/ " .. phoenix,
  "/ash/physics/ @ZiplineTeam/phoenix-physics-reviewers",
  "/ash/physics/models/ " .. phoenix .. " @ZiplineTeam/p2-gnc",
  "*.bzl @ZiplineTeam/developer-productivity",
  "/ash/**/BUILD.bazel " .. phoenix .. " @ZiplineTeam/p2-gnc",
  "/ash/core/config_gen.bzl " .. phoenix .. " @ZiplineTeam/developer-productivity",
  "/ash/unowned/ # explicit unowned override",
  "/directory\\ with\\ spaces/ " .. phoenix,
  "!ash/ignored/ " .. phoenix,
  "/ash/[invalid]/ @someone",
})
assert(owners.owned_by(rules, "ash/core/a.rs", phoenix))
assert(not owners.owned_by(rules, "ash/physics/a.rs", phoenix), "last matching rule replaces broad ownership")
assert(owners.owned_by(rules, "ash/physics/models/a.rs", phoenix), "shared ownership includes Phoenix")
assert(not owners.owned_by(rules, "ash/core/a.bzl", phoenix), "global overrides apply after directory rules")
assert(owners.owned_by(rules, "ash/core/config_gen.bzl", phoenix), "later specific overrides restore shared ownership")
assert(owners.owned_by(rules, "ash/BUILD.bazel", phoenix), "double-star matches zero directories")
assert(owners.owned_by(rules, "ash/physics/deep/BUILD.bazel", phoenix))
assert(not owners.owned_by(rules, "ash/unowned/a.rs", phoenix))
assert(owners.owned_by(rules, "directory with spaces/a.rs", phoenix))
assert(not owners.owned_by(rules, "elsewhere/a.rs", phoenix))
assert(owners.matches("docs/", "nested/docs/a.md"), "unanchored directory matches at any depth")
assert(not owners.matches("/docs/", "nested/docs/a.md"))
assert(not owners.matches("/docs/", "docs"), "directory rule does not match a file of the same name")
assert(owners.matches("/docs/*", "docs/subdir/deep/a.md"), "matched directories pass ownership to descendants")
assert(owners.matches("/docs/*.md", "docs/a.md"))
assert(not owners.matches("/docs/*.md", "docs/subdir/a.md"), "single star cannot cross a slash")
assert(owners.matches("/docs/**", "docs/subdir/a.md"))
assert(not owners.matches("/docs/**", "docs"))
assert(owners.matches("/a/?/file.txt", "a/b/file.txt"))
assert(not owners.matches("/a/?/file.txt", "a/bb/file.txt"))

local original_systemlist = vim.fn.systemlist
local commands = {}
vim.fn.systemlist = function(args)
  table.insert(commands, args)
  return { "/ash/ " .. phoenix }
end
assert(owners.owned_by(owners.read("/fixture", "exact-head"), "ash/a.rs", phoenix))
assert(commands[1][5] == "exact-head:.github/CODEOWNERS", "read ownership from the head revision")
vim.fn.systemlist = original_systemlist

local entries = {
  { path = "b.rs", viewed = true },
  { path = "a.rs", viewed = false },
  { path = "c.rs", viewed = false },
}
local progress = guide.progress(entries, "a.rs", true)
assert(progress:find("position 2/3", 1, true))
assert(not progress:find("reviewed", 1, true), "route position must not duplicate completion counters")
assert(guide.progress(entries, "a.rs", true, 15) == "Phoenix 2/3", "narrow windows keep route position visible")
assert(guide.progress({}, nil, true):find("no matching files", 1, true))
local diagram = { "    +-------+", "    | Flow  |", "    +-------+", "", "       |", "       v" }
assert(vim.deep_equal(guide.diagram(diagram), diagram), "diagram indentation and blank lines must survive")
assert(vim.deep_equal(guide.diagram(table.concat(diagram, "\n")), diagram))
assert(vim.deep_equal(guide.diagram({ "first\n  second" }), { "first", "  second" }))
local lines, targets = guide.lines({
  summary = "One takeaway.",
  diagram = diagram,
  high_risk = { "one", "two", "three", "four" },
  files_by_path = { ["a.rs"] = { reason = "check the consumer", notes = {} } },
}, entries, "a.rs", true)
local diagram_start
for index, line in ipairs(lines) do
  if line == diagram[1] then
    diagram_start = index
    break
  end
end
assert(diagram_start)
for index, line in ipairs(diagram) do
  assert(lines[diagram_start + index - 1] == line, "the viewer must preserve renderer output unchanged")
end
local current_line
for line, item in pairs(targets) do
  if item.path == "a.rs" then
    current_line = line
  end
end
assert(lines[current_line]:find("> [ ] 2. a.rs", 1, true))
assert(table.concat(lines, "\n"):find("Purpose/change: check the consumer", 1, true))
assert(table.concat(guide.lines(nil, {}, nil, true), "\n"):find("No Phoenix-owned changed files", 1, true))

local complete = guide.normalize({
  summary = "Prevent dispatch after cleanup.",
  behavior_change = { before = "Dispatch used cached readiness.", after = "Dispatch checks readiness freshness." },
  diagram = diagram,
  core_code = {
    {
      label = "Source excerpt",
      title = "Before at base",
      code = { "if ready then", "  dispatch()", "end" },
      sources = { "a.rs:dispatch:10-12 at base" },
    },
    {
      label = "Core pseudocode",
      title = "After at head",
      code = [[if ready and fresh then
  dispatch()
  return "if \"quoted\" // text" // return here
end]],
      sources = { "a.rs:dispatch:15-17 at head" },
    },
  },
  files = { { path = "a.rs", stage = "Dispatch gate", reason = "check freshness" } },
  validation = {
    review_scope = "Deep: dispatch path; mapped: callers.",
    observed = { "Parser tests passed" },
    gaps = { "Runtime not exercised" },
  },
  high_risk = { "One", "Two", "Three", "Four" },
})
assert(complete.core_code[2].code[2] == "  dispatch()", "code indentation must survive normalization")
local full = table.concat(guide.lines(complete, entries, "a.rs", false, { status = "running" }), "\n")
for _, expected in ipairs({
  "Main Pi: updating",
  "Before: Dispatch used",
  "After: Dispatch checks",
  "Source excerpt — Before",
  "Core pseudocode — After",
  "  dispatch()",
  "Source: a.rs:dispatch:15-17 at head",
  "Dispatch gate",
}) do
  assert(full:find(expected, 1, true), "guide viewer lost: " .. expected)
end
assert(
  #guide.normalize({ core_code = { false, { code = 42 } }, behavior_change = false, validation = false }).core_code == 0
)

assert(
  not full:find("Review focus", 1, true)
    and not full:find("Review coverage", 1, true)
    and complete.high_risk[4] == "Four"
    and complete.validation.observed[1] == "Parser tests passed",
  "audit details stay in the artifact, not the reading view"
)

local chunks = guide.normalize({
  context = { base_oid = string.rep("a", 40), head_oid = string.rep("b", 40) },
  summary = "Connect the entry point to its checks.",
  diagram = diagram,
  files = {
    {
      path = "b.rs",
      stage = "1. Entry point",
      reason = "Chunk summary: Connect actual_entry to actual_gate. [read carefully]",
      suggestions = {
        {
          id = "entry-question",
          side = "LEFT",
          line = 2,
          end_line = 3,
          body = "Question: Can actual_entry run twice?\n\n```text\nBefore: literal text\n    keep_indent()\n```",
          why = "Check the reset path.",
        },
      },
    },
    { path = "a.rs", stage = "1. Entry point", reason = "actual_gate[deep] — inspect the transition [deep]" },
    {
      path = "c.rs",
      stage = "2. Checks",
      reason = "Chunk summary: Cover errors via actual_test. [skim]",
      suggestions = { { id = "coverage-gap", body = "Verification gap: Runtime is not exercised." } },
    },
  },
})
local before_chunks, before_entries = vim.deepcopy(chunks), vim.deepcopy(entries)
local chunk_lines, chunk_targets, chunk_sections = guide.lines(chunks, entries, "a.rs", false)
local overview_order, chunk_order, file_order = {}, {}, {}
local question_row, next_file_row, source_target, approximate_row
for row, line in ipairs(chunk_lines) do
  local section = chunk_sections[row]
  if section and section.id:match("^overview:chunk:") then
    table.insert(overview_order, section.id:sub(10))
  end
  if section and section.id:match("^chunk:") then
    table.insert(chunk_order, section.id)
  end
  local target = chunk_targets[row]
  if target and not target.line then
    table.insert(file_order, target.path)
    if target.path == "a.rs" then
      next_file_row = row
    end
  elseif target and target.side == "LEFT" then
    source_target = target
  end
  if line:find("Question: Can actual_entry", 1, true) then
    question_row = row
  end
  if line:find("(file-level / approximate anchor)", 1, true) then
    approximate_row = row
  end
end
assert(vim.deep_equal(overview_order, chunk_order) and #chunk_order == 2, "both passes share the same chunk order")
assert(vim.deep_equal(file_order, { "b.rs", "a.rs", "c.rs" }), "chunks cannot reorder native file navigation")
assert(question_row < next_file_row, "questions stay beside their file within the chunk")
assert(chunk_lines[question_row] == "Question: Can actual_entry run twice?")
assert(chunk_lines[question_row + 4] == "    keep_indent()", "guide prose does not add indentation to code")
assert(
  source_target.path == "b.rs"
    and source_target.line == 2
    and source_target.end_line == 3
    and source_target.revision == chunks.context.base_oid,
  "chunk source jumps retain exact LEFT coordinates and pins"
)
assert(approximate_row and not chunk_targets[approximate_row], "approximate anchors must not invent a line target")
local chunk_text = table.concat(chunk_lines, "\n")
for _, label in ipairs({
  "## 🧭 PR overview",
  "🔬 Section review",
  "🔎 Careful reading",
  "👀 Skim",
  "Purpose/change: Connect actual_entry",
  "actual_gate[deep]",
  "Why: Check the reset path.",
}) do
  assert(chunk_text:find(label, 1, true), "missing chunk content: " .. label)
end
local scoped = table.concat(guide.lines(chunks, { entries[2], entries[3] }, "a.rs", true), "\n")
assert(
  scoped:find("Purpose/change: Connect actual_entry", 1, true) and scoped:find("actual_gate[deep]", 1, true),
  "ownership filtering must retain both the chunk summary and visible file guidance"
)
assert(vim.deep_equal(chunks, before_chunks) and vim.deep_equal(entries, before_entries), "rendering is read-only")

local panel_view = require("utils.diffview_review_panel")
local generated, refined, opened = 0, 0, nil
complete.context = { base_oid = string.rep("a", 40), head_oid = string.rep("b", 40) }
local base_link, base_target = guide.source_link(complete.core_code[1].sources[1], complete)
assert(base_link == "↗ a.rs:10-12 · Before")
assert(base_target.side == "LEFT" and base_target.line == 10 and base_target.end_line == 12)
local _, head_target = guide.source(
  { path = "a.rs", line = 15, end_line = 17, side = "RIGHT", revision = complete.context.head_oid },
  complete
)
assert(head_target.side == "RIGHT" and head_target.revision == complete.context.head_oid)
local _, invalid = guide.source({ path = "a.rs", line = {}, side = "RIGHT" }, complete)
assert(invalid == nil, "malformed sources are displayed, not guessed")
local _, wrong =
  guide.source({ path = "a.rs", line = 1, side = "LEFT", revision = complete.context.head_oid }, complete)
assert(wrong == nil, "a source cannot claim a different side's revision")
local _, stale = guide.source("a.rs:10 at " .. string.rep("c", 40), complete)
assert(stale == nil, "stale references cannot become jump targets")

local ctx = { state_path = "guide-test", view = {} }
local status = { status = "queued" }
local model = {
  ctx = ctx,
  guide = complete,
  state = { comments = {} },
  entries = entries,
  current = "a.rs",
  phoenix = false,
  callbacks = {
    generate = function()
      generated = generated + 1
    end,
    refine = function()
      refined = refined + 1
    end,
    jump = function(target)
      opened = target.path
    end,
    status = function()
      return status
    end,
  },
}
local source_win = vim.api.nvim_get_current_win()
local source_width = vim.api.nvim_win_get_width(source_win)
local panel = panel_view.open(model, { mode = "guide" })
local function press(key)
  vim.fn.maparg(key, "n", false, true).callback()
end
local initial = panel.winid
assert(panel.expanded, "Guide opens expanded")
assert(panel_view.open(model, { mode = "threads" }).winid == initial)
assert(panel_view.open(model, { mode = "guide" }).winid == initial, "Guide and Threads share the expanded view")
press("z")
assert(not panel.expanded and vim.api.nvim_win_get_position(panel.winid)[2] == 0, "z docks on the left")
press("z")
local expanded = vim.api.nvim_win_get_config(panel.winid)
assert(
  panel.expanded
    and expanded.relative == "editor"
    and expanded.width == math.floor(vim.o.columns * 0.90)
    and expanded.height == math.floor(vim.o.lines * 0.88),
  "z opens a larger reading view with margins"
)
vim.api.nvim_exec_autocmds("VimResized", {})
assert(vim.api.nvim_win_get_config(panel.winid).width == expanded.width)
assert(vim.api.nvim_win_get_width(source_win) == source_width, "the float gives the diff back its full width")
local function locate(text)
  for row, line in ipairs(vim.api.nvim_buf_get_lines(panel.buffer, 0, -1, false)) do
    if line:find(text, 1, true) then
      return row
    end
  end
  error("Missing guide text: " .. text)
end
local function heading_highlight(text)
  local row = locate(text) - 1
  local marks = vim.api.nvim_buf_get_extmarks(
    panel.buffer,
    vim.api.nvim_create_namespace("diffview_review_panel"),
    { row, 0 },
    { row, -1 },
    { details = true }
  )
  for _, mark in ipairs(marks) do
    if mark[4].hl_group then
      return mark[4].hl_group
    end
  end
end
assert(heading_highlight("🔬 Section review") == "DiffviewReviewGuideHeading")
assert(
  locate("PR overview") < locate("Core code changes") and locate("Core code changes") < locate("🔬 Section review")
)
local guide_window = panel.winid
press("?")
local help_window = vim.api.nvim_get_current_win()
local help_lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
assert(help_window ~= guide_window and vim.api.nvim_win_get_config(help_window).relative ~= "")
assert(help_lines[5] == "Guide" and help_lines[6]:find("Enter", 1, true), "help uses separate shortcut rows")
vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("<Esc>", true, false, true), "mx", false)
assert(not vim.api.nvim_win_is_valid(help_window) and vim.api.nvim_get_current_win() == guide_window)
assert(heading_highlight("🔬 Section 1 —") == "DiffviewReviewGuideSubheading")
assert(heading_highlight("Before: Dispatch used") == "DiffviewReviewProseLabel")
assert(vim.wo[panel.winid].winhl:find("@markup.raw.block.markdown:DiffviewReviewCodeText", 1, true))
assert(heading_highlight("Core pseudocode — After") == "DiffviewReviewGuideSubheading")
local _, variant_style = guide.code_language({ label = " Core pseudo-code (Rust-like) " }, complete)
assert(variant_style == "pseudocode")
local language, style = guide.code_language(complete.core_code[2], complete)
assert(language == "text" and style == "pseudocode", "pseudocode does not select a parser")
local pseudo_row = locate('return "if') - 1
local pseudo_line = vim.api.nvim_buf_get_lines(panel.buffer, pseudo_row, pseudo_row + 1, false)[1]
local tokens = {}
for _, mark in
  ipairs(
    vim.api.nvim_buf_get_extmarks(
      panel.buffer,
      vim.api.nvim_create_namespace("diffview_review_panel"),
      { pseudo_row, 0 },
      { pseudo_row, -1 },
      { details = true }
    )
  )
do
  local group = mark[4].hl_group
  if group and group:match("^DiffviewReviewPseudo") then
    assert(not tokens[group], "keywords and comment markers inside strings must not get separate highlights")
    tokens[group] = pseudo_line:sub(mark[3] + 1, mark[4].end_col)
  end
end
assert(vim.deep_equal(tokens, {
  DiffviewReviewPseudoKeyword = "return",
  DiffviewReviewPseudoString = [["if \"quoted\" // text"]],
  DiffviewReviewPseudoComment = "// return here",
}))
assert(vim.wo[panel.winid].conceallevel == 2 and vim.wo[panel.winid].concealcursor == "nc")
local heading = locate("🔬 Section review") - 1
local marks = vim.api.nvim_buf_get_extmarks(
  panel.buffer,
  vim.api.nvim_create_namespace("diffview_review_panel"),
  { heading, 0 },
  { heading, -1 },
  { details = true }
)
assert(
  vim.iter(marks):any(function(mark)
    return mark[4].conceal == "" and mark[4].end_col == 3
  end),
  "heading markers are hidden without changing buffer text"
)
press("r")
assert(generated == 1 and refined == 0, "generation is an explicit main-session action")
vim.api.nvim_win_set_cursor(panel.winid, { locate("if ready and fresh then") + 1, 2 })
vim.api.nvim_set_current_win(source_win)
local focused = vim.api.nvim_get_current_win()
complete.summary = complete.summary .. string.rep("\nAdded explanation.", 12)
complete.core_code[2].code[1] = "if ready and fresh and not stopped then"
complete.core_code[2].title = "After at head, including shutdown"
panel_view.refresh(model)
assert(vim.api.nvim_get_current_win() == focused, "guide updates must not steal focus")
local row = vim.api.nvim_win_get_cursor(panel.winid)[1]
assert(
  vim.api.nvim_buf_get_lines(panel.buffer, row - 1, row, false)[1] == "  dispatch()",
  "the reader stays at the same offset inside a section after earlier sections grow"
)
status = { status = "running" }
panel_view.refresh(model)
assert(vim.api.nvim_get_current_win() == focused)
vim.api.nvim_set_current_win(panel.winid)
local target_line
for line, target in pairs(panel.targets) do
  if target.path == "a.rs" and not target.line then
    target_line = line
  end
end
vim.api.nvim_win_set_cursor(panel.winid, { target_line, 0 })
press("<CR>")
assert(opened == "a.rs", "guide sections retain route navigation")
model.guide = chunks
panel_view.refresh(model)
assert(heading_highlight("Purpose/change: Connect actual_entry") == "DiffviewReviewProseLabel")
assert(heading_highlight("Verification gap: Runtime is not exercised.") == "DiffviewReviewProseLabel")
assert(not heading_highlight("Before: literal text"), "labels inside code fences must not be styled as prose")
vim.api.nvim_win_set_cursor(panel.winid, { locate("Purpose/change: Cover errors"), 0 })
vim.api.nvim_set_current_win(source_win)
chunks.files_by_path["b.rs"].reason = "Chunk summary: Expanded entry context.\n"
  .. string.rep("More entry detail.\n", 10)
  .. "actual_entry [read carefully]"
chunks.files_by_path["b.rs"].stage, chunks.files_by_path["a.rs"].stage = "2. Entry point", "2. Entry point"
chunks.files_by_path["c.rs"].stage = "3. Checks"
panel_view.refresh(model)
local chunk_row = vim.api.nvim_win_get_cursor(panel.winid)[1]
assert(
  vim.api
    .nvim_buf_get_lines(panel.buffer, chunk_row - 1, chunk_row, false)[1]
    :find("Purpose/change: Cover errors", 1, true),
  "chunk reading position survives earlier expansion and renumbering"
)
assert(
  vim.api.nvim_get_current_win() == source_win and model.current == "a.rs" and vim.deep_equal(entries, before_entries),
  "updates preserve focus, selected file, and reviewed entries"
)
vim.api.nvim_set_current_win(panel.winid)
press("u")
assert(refined == 1 and vim.api.nvim_win_is_valid(panel.winid), "refinement keeps the shared panel")
press("q")
assert(not vim.api.nvim_win_is_valid(panel.winid or -1))
assert(vim.api.nvim_win_get_width(source_win) == source_width, "closing Guide restores the code workspace")

local directory = vim.fn.tempname()
vim.fn.mkdir(directory, "p")
local context = { root = directory, state_path = directory .. "/state.json" }
assert(state.save(context, { ownership_filter = "phoenix", viewed = { ["a.rs"] = true }, comments = {} }, error))
local restored = state.load(context, error)
assert(restored.ownership_filter == "phoenix" and restored.viewed["a.rs"])
vim.fn.delete(directory, "rf")
print("diffview_review_guide: all tests passed")
