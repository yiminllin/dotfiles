vim.opt.runtimepath:append(vim.fn.getcwd() .. "/nvim/.config/nvim")
local skim = require("utils.diffview_review_skim")
local lines, targets = {}, {}
local path = 'folder/space "tab\tname.lua'
skim.append_patch(lines, targets, path, {
  'diff --git "a/quoted" "b/quoted"',
  "--- a/quoted",
  "+++ b/quoted",
  "@@ -10,3 +20,4 @@ function example()",
  " context",
  "-old",
  "+new",
  "+extra",
  " tail",
  "\\ No newline at end of file",
  "@@ -50 +60 @@",
  "-again",
  "+again",
})
local function target(row, side, line)
  assert(vim.deep_equal(targets[row], { path = path, side = side, line = line }), vim.inspect(targets[row]))
end
target(2, "RIGHT", nil) -- Metadata must not become a removed-code anchor.
target(3, "RIGHT", nil)
target(5, "RIGHT", 20)
target(6, "LEFT", 11)
target(7, "RIGHT", 21)
target(8, "RIGHT", 22)
target(9, "RIGHT", 23)
target(10, "RIGHT", nil)
target(12, "LEFT", 50)
target(13, "RIGHT", 60)
assert(lines[1] == 'diff --git "a/quoted" "b/quoted"')

lines, targets = {}, {}
skim.append_patch(lines, targets, path, { "@@ -0,0 +1,2 @@", "++++ literal content", "+second" })
target(2, "RIGHT", 1)
target(3, "RIGHT", 2)
lines, targets = {}, {}
skim.append_patch(lines, targets, path, { "@@ -5,2 +4,0 @@", "-first", "-second" })
target(2, "LEFT", 5)
target(3, "LEFT", 6)
lines, targets = {}, {}
skim.append_patch(lines, targets, path, { "Binary files a/foo and b/foo differ", "rename from foo", "rename to bar" })
for row = 1, #lines do
  target(row, "RIGHT", nil)
end
-- Use actual Git quoting and a modified copy source, not hand-written filename headers.
local root = vim.fn.tempname()
vim.fn.mkdir(root, "p")
local function git(...)
  local args = { "git", "-C", root }
  vim.list_extend(args, { ... })
  local output = vim.fn.systemlist(args)
  assert(vim.v.shell_error == 0, table.concat(output, "\n"))
  return output
end
local function commit()
  git("add", ".")
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
    "fixture"
  )
  return git("rev-parse", "HEAD")[1]
end
git("init", "-q")
local odd = 'space\t "name\n.lua'
local original = {}
for index = 1, 15 do
  original[index] = "unchanged shared content line " .. index
end
original[8] = "old"
vim.fn.writefile(original, root .. "/source.lua")
vim.fn.writefile({ "old" }, root .. "/" .. odd)
local base = commit()
local copy, modified = vim.deepcopy(original), vim.deepcopy(original)
copy[8], modified[8] = "new", "source-only change"
vim.fn.writefile(copy, root .. "/copy.lua")
vim.fn.writefile(modified, root .. "/source.lua")
vim.fn.writefile({ "new" }, root .. "/" .. odd)
local head = commit()
local patch = git(
  "-c",
  "core.quotePath=false",
  "diff",
  "--find-copies",
  "--find-copies-harder",
  base,
  head,
  "--",
  "source.lua",
  "copy.lua"
)
local selected = skim.file_patch({ path = "copy.lua", entry = { oldpath = "source.lua" } }, patch)
assert(table.concat(selected, "\n"):find("copy from source.lua", 1, true))
assert(
  not table.concat(selected, "\n"):find("source-only change", 1, true),
  "copy must not include the source file's own diff"
)
lines, targets = {}, {}
skim.append_patch(lines, targets, "copy.lua", selected)
local removed, added = false, false
for row, value in pairs(targets) do
  if lines[row] == "-old" then
    removed = value.side == "LEFT" and value.line == 8
  end
  if lines[row] == "+new" then
    added = value.side == "RIGHT" and value.line == 8
  end
end
assert(removed and added)
patch = git("-c", "core.quotePath=false", "diff", base, head, "--", odd)
selected = skim.file_patch({ path = odd, entry = {} }, patch)
assert(#selected == #patch, "Git-quoted filename must match the original path exactly")
vim.fn.delete(root, "rf")
print("diffview_review_skim: all tests passed")
