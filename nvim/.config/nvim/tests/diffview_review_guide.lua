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
assert(progress:find("reviewed 1/3", 1, true), "visiting a file is not completion")
assert(progress:find("[##------]", 1, true))
assert(guide.progress(entries, "a.rs", true, 35):find("done 1/3", 1, true), "narrow windows keep completion visible")
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
for index, line in ipairs(diagram) do
  assert(lines[index + 4] == line)
end
local current_line
for line, item in pairs(targets) do
  if item.path == "a.rs" then
    current_line = line
  end
end
assert(lines[current_line]:find("> [ ] 2. a.rs", 1, true))
assert(lines[current_line]:find("check the consumer", 1, true))
assert(lines[#lines] == "- three", "guide focus remains concise")
assert(table.concat(guide.lines(nil, {}, nil, true), "\n"):find("No Phoenix-owned changed files", 1, true))

local directory = vim.fn.tempname()
vim.fn.mkdir(directory, "p")
local context = { root = directory, state_path = directory .. "/state.json" }
assert(state.save(context, { ownership_filter = "phoenix", viewed = { ["a.rs"] = true }, comments = {} }, error))
local restored = state.load(context, error)
assert(restored.ownership_filter == "phoenix" and restored.viewed["a.rs"])
vim.fn.delete(directory, "rf")
print("diffview_review_guide: all tests passed")
