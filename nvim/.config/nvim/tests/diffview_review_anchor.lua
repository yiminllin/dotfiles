vim.opt.runtimepath:append(vim.fn.getcwd() .. "/nvim/.config/nvim")

local anchor = require("utils.diffview_review_anchor")
local format = require("utils.diffview_review_format")

local function assert_equal(actual, expected, message)
  if not vim.deep_equal(actual, expected) then
    error(("%s\nexpected: %s\nactual: %s"):format(message, vim.inspect(expected), vim.inspect(actual)))
  end
end

local original = {
  "local before = true",
  "target one",
  "target two",
  "local after = true",
}
local captured = anchor.capture(original, {
  path = "lua/example.lua",
  side = "RIGHT",
  line = 2,
  end_line = 3,
  commit_sha = "head-sha",
  blob_sha = "blob-sha",
})
assert_equal(captured.original.text, { "target one", "target two" }, "capture should retain the selected range")
assert_equal(captured.original.before, { "local before = true" }, "capture should retain preceding context")
assert_equal(captured.original.after, { "local after = true" }, "capture should retain following context")
assert_equal(captured.original.commit_sha, "head-sha", "capture should retain commit identity")

local resolution = anchor.resolve(captured, original)
assert_equal(resolution.status, "anchored", "unchanged content should stay anchored")
assert_equal(resolution.line, 2, "unchanged content should keep its line")

local inserted = { "new heading", unpack(original) }
resolution = anchor.resolve(captured, inserted)
assert_equal(resolution.status, "moved", "an insertion above should move the anchor")
assert_equal(resolution.line, 3, "an insertion above should relocate the anchor")
assert_equal(resolution.confidence, "unique-exact", "a unique exact range should resolve confidently")

local moved = {
  "local before = true",
  "local after = true",
  "other",
  "target one",
  "target two",
}
resolution = anchor.resolve(captured, moved)
assert_equal(resolution.status, "moved", "a moved block should resolve")
assert_equal(resolution.line, 4, "a moved block should use its new location")

local repeated_with_context = {
  "target one",
  "target two",
  "other",
  "local before = true",
  "target one",
  "target two",
  "local after = true",
}
resolution = anchor.resolve(captured, repeated_with_context)
assert_equal(resolution.status, "moved", "context should disambiguate duplicate ranges")
assert_equal(resolution.line, 5, "context should select the matching duplicate")
assert_equal(resolution.confidence, "exact-context", "context resolution should report its confidence")

local ambiguous = {
  "target one",
  "target two",
  "other",
  "target one",
  "target two",
}
resolution = anchor.resolve(captured, ambiguous)
assert_equal(resolution.status, "ambiguous", "duplicate ranges without context should remain ambiguous")
assert_equal(resolution.candidates, { 1, 4 }, "ambiguous resolution should expose candidates")

resolution = anchor.resolve(captured, { "target was deleted" })
assert_equal(resolution.status, "stale", "deleted content should become stale")

local comment = { anchor = captured, line = 2, end_line = 3 }
resolution = anchor.resolve(captured, inserted)
anchor.apply_resolution(comment, resolution)
assert_equal(comment.line, 3, "applying a confident resolution should update the working line")
assert_equal(comment.anchor.original.line, 2, "applying a resolution must preserve the original line")
assert_equal(comment.anchor_status, "moved", "applying a move should expose the moved status")
assert(format.comment_status_text(comment):find("moved L2→L3", 1, true), "moved anchors should render status")
assert_equal(format.comment_status_text({ anchor_status = "stale" }), "stale anchor", "stale status should render")
assert_equal(format.comment_status_text({ anchor_status = "ambiguous" }), "ambiguous anchor", "ambiguous status should render")
assert_equal(
  format.comment_status_text({ anchor_status = "legacy_unverified" }),
  "unverified legacy anchor",
  "legacy status should render"
)

print("diffview_review_anchor: all tests passed")
