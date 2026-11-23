-- SETUP: Isolated mailboxes model streaming, failed requests and queued follow-ups.
vim.opt.runtimepath:append(vim.fn.getcwd() .. "/nvim/.config/nvim")

local review_agent = require("utils.diffview_review_agent")
local review_format = require("utils.diffview_review_format")
local pi = require("utils.pi")

local function assert_equal(actual, expected, message)
  if not vim.deep_equal(actual, expected) then
    error(("%s\nexpected: %s\nactual: %s"):format(message, vim.inspect(expected), vim.inspect(actual)))
  end
end

assert_equal(review_format.agent_status_label("pending"), "Queued", "use human-readable worker states")
assert_equal(review_format.agent_status_label("running"), "Investigating")
assert_equal(review_format.agent_status_label("blocked"), "Needs input")
assert_equal(review_format.agent_status_label("failed"), "Failed")

local temp_dir = vim.fn.tempname()
vim.fn.mkdir(temp_dir, "p")
local state_path = vim.fs.joinpath(temp_dir, "diffview-review.json")
local comment = {
  agent_request_id = "request-1",
  agent_status = "pending",
  body = "Could this race?",
  file = "lua/example.lua",
  line = 10,
  local_id = "local-1",
}
local state = { comments = { comment } }
local reply_dir = review_agent.reply_dir(state_path)
vim.fn.mkdir(reply_dir, "p")

local reply_path = vim.fs.joinpath(reply_dir, "local-1--request-1.json")
vim.fn.writefile(
  { vim.json.encode({ comment_id = "local-1", request_id = "request-1", status = "running" }) },
  reply_path
)
-- TEST: Ingest worker artifacts without invoking a provider.
local started = review_agent.ingest(state, state_path)
assert_equal(started, true, "the agent start marker should change queued state") -- VERIFY: Dispatch alone is not running.
assert_equal(comment.agent_status, "running", "only an agent marker should report active investigation")
assert_equal(review_agent.ingest(state, state_path), false, "a repeated start marker should not change state")
vim.fn.writefile({
  vim.fn.json_encode({
    author = "pi",
    body = "Yes. The callback can run after cleanup.",
    comment_id = "local-1",
    created_at = "2026-01-01T00:00:00Z",
    request_id = "request-1",
  }),
}, reply_path)

local changed, stats = review_agent.ingest(state, state_path)
assert_equal(changed, true, "a matching reply should change state")
assert_equal(stats.completed, 1, "a matching reply should complete once")
assert_equal(comment.agent_status, "completed", "a matching reply should complete the request")
assert_equal(#comment.replies, 1, "a matching reply should be appended")
assert_equal(comment.replies[1].request_id, "request-1", "the reply should retain request identity")

changed, stats = review_agent.ingest(state, state_path)
assert_equal(changed, false, "re-ingestion should be idempotent")
assert_equal(stats.completed, 0, "re-ingestion should not count a duplicate completion")
assert_equal(#comment.replies, 1, "re-ingestion should not duplicate replies")

comment.agent_request_id = "request-2"
comment.agent_status = "running"
local failed_path = vim.fs.joinpath(reply_dir, "local-1--request-2.json")
vim.fn.writefile({
  vim.fn.json_encode({
    author = "pi",
    body = "",
    comment_id = "local-1",
    created_at = "2026-01-01T00:00:01Z",
    error = "inspection failed",
    request_id = "request-2",
    status = "failed",
  }),
}, failed_path)
changed, stats = review_agent.ingest(state, state_path)
assert_equal(changed, true, "a matching failure should change state")
assert_equal(stats.failed, 1, "a matching failure should be counted")
assert_equal(comment.agent_status, "failed", "a failure artifact should fail the current request")
assert_equal(comment.agent_error, "inspection failed", "a failure artifact should preserve its error")
assert_equal(#comment.replies, 1, "a stale successful artifact should not attach to a newer request")

vim.fn.writefile({ "not json" }, vim.fs.joinpath(reply_dir, "invalid.json"))
changed, stats = review_agent.ingest(state, state_path)
assert_equal(changed, false, "invalid and already-ingested artifacts should not change state")
assert(stats.invalid >= 1, "invalid artifacts should be counted")
assert(stats.stale >= 1, "old request artifacts should be counted as stale")

local current_target = pi._select_named_agent_target({
  "@1\t%1\treview-42\tpi\texec pi --name review-42\t/Users/yiminlin/dotfiles",
  "@2\t%2\treview-42\tpi\texec pi --name review-42\t/Users/yiminlin/dotfiles/",
}, "@2", "review-42", "/Users/yiminlin/dotfiles")
assert_equal(current_target, { window_id = "@2", pane_id = "%2" }, "the current-window exact name should win")

local wrong_root_target, wrong_root_error = pi._select_named_agent_target({
  "@1\t%1\treview-42\tpi\texec pi --name review-42\t/Users/yiminlin/other-repo",
}, "@1", "review-42", "/Users/yiminlin/dotfiles")
assert_equal(wrong_root_target, nil, "a matching name in another repository should not be selected")
assert(wrong_root_error:find("review ...", 1, true) ~= nil, "the wrong-root error should direct the user to review ...")

local dead_target, dead_error = pi._select_named_agent_target({
  "@1\t%1\treview-42\tzsh\ttmux set-option -pt $TMUX_PANE @pi_agent_name review-42\t/Users/yiminlin/dotfiles",
}, "@1", "review-42", "/Users/yiminlin/dotfiles")
assert_equal(dead_target, nil, "a reused shell with the old name should not be selected")
assert(dead_error:find("review ...", 1, true) ~= nil, "the dead-pane error should direct the user to review ...")

local ambiguous_target, ambiguous_error = pi._select_named_agent_target({
  "@1\t%1\treview-42\tpi\texec pi --name review-42\t/Users/yiminlin/dotfiles",
  "@2\t%2\treview-42\tpi\texec pi --name review-42\t/Users/yiminlin/dotfiles",
}, "@3", "review-42", "/Users/yiminlin/dotfiles")
assert_equal(ambiguous_target, nil, "ambiguous global matches should not pick an arbitrary pane")
assert(ambiguous_error:find("Multiple Pi panes", 1, true) ~= nil, "ambiguity should be explicit")

local original_system = vim.system
local original_tmux = vim.env.TMUX
local tmux_calls = {}
vim.env.TMUX = "fake"
vim.system = function(args)
  table.insert(tmux_calls, vim.deepcopy(args))
  local stdout = ""
  if args[2] == "display-message" then
    stdout = "@2\n"
  elseif args[2] == "list-panes" then
    stdout = "@1\t%1\tother\tzsh\t\t/Users/yiminlin/dotfiles\n@2\t%2\treview-42\tpi\texec pi --name review-42\t/Users/yiminlin/dotfiles\n"
  end
  return {
    wait = function()
      return { code = 0, stderr = "", stdout = stdout }
    end,
  }
end
local send_ok, send_error = pi.send_to_named_agent("review-42", "/Users/yiminlin/dotfiles", "automatic request")
vim.system = original_system
vim.env.TMUX = original_tmux
assert_equal(send_ok, true, "named-pane dispatch should succeed with an exact match")
assert_equal(send_error, nil, "successful named-pane dispatch should not return an error")
assert_equal(tmux_calls[3], { "tmux", "send-keys", "-t", "%2", "-l", "automatic request" }, "dispatch should send literally to the exact pane")
assert_equal(tmux_calls[4], { "tmux", "send-keys", "-t", "%2", "M-Enter" }, "dispatch should queue a follow-up without interrupting or focusing the pane")
assert_equal(#tmux_calls, 4, "dispatch should not issue a pane-focus command")

local prompt = review_agent.build_prompt({
  body = comment.body,
  comment_id = comment.local_id,
  file = comment.file,
  line = comment.line,
  request_id = comment.agent_request_id,
  state_path = state_path,
})
assert(prompt:find("Do not edit review artifacts", 1, true) ~= nil, "the prompt should forbid shared-state edits")
assert(prompt:find("without writing artifacts", 1, true), "the host owns reply persistence")
assert(
  prompt:find("Only the main review agent owns guide updates", 1, true),
  "parallel workers must not race guide writes"
)
assert(prompt:find("Inherited conversation is background", 1, true), "the worker needs a clear task boundary")

local request = { comment_id = "local-1", request_id = "request-3", prompt = prompt }
assert_equal(
  review_agent.enqueue(state_path, request),
  false,
  "an absent service must not silently fall back to serial dispatch"
)
vim.fn.writefile(
  { vim.json.encode({ updated_at = vim.fn.localtime() * 1000, cwd = temp_dir }) },
  vim.fs.joinpath(temp_dir, "review-service.json")
)
assert_equal(review_agent.enqueue(state_path, request), true, "a live service accepts a local request")
assert_equal(
  vim.json.decode(table.concat(vim.fn.readfile(vim.fs.joinpath(temp_dir, "agent-requests", "request-3.json")), "\n")),
  request,
  "the mailbox preserves exact request identity"
)
comment.agent_request_id = "request-3"
local stream_path = vim.fs.joinpath(reply_dir, "local-1--request-3.json")
vim.fn.writefile({
  vim.json.encode({
    comment_id = "local-1",
    request_id = "request-3",
    status = "running",
    body = "Partial answer",
    activity = "read: src/main.rs",
  }),
}, stream_path)
review_agent.ingest(state, state_path)
assert_equal(comment.agent_partial, "Partial answer", "streamed text belongs to the live thread")
assert_equal(#comment.replies, 1, "partial text is not a completed reply")
vim.fn.writefile({
  vim.json.encode({
    comment_id = "local-1",
    request_id = "request-3",
    status = "blocked",
    input = { id = "input-1", method = "confirm" },
  }),
}, stream_path)
review_agent.ingest(state, state_path)
assert_equal(comment.agent_status, "blocked", "input requests remain thread-local")
assert_equal(comment.agent_input.id, "input-1", "input identity must survive ingestion")
assert(review_agent.control(state_path, "request-3", { id = "input-1", confirmed = false }))
vim.fn.writefile(
  { vim.json.encode({ comment_id = "local-1", request_id = "request-3", status = "completed", body = "Final answer" }) },
  stream_path
)
review_agent.ingest(state, state_path)
assert_equal(comment.agent_partial, nil, "completion clears partial output")
assert_equal(comment.agent_input, nil, "completion clears pending input")
assert_equal(comment.agent_unread, true, "completion is visible without taking focus")
assert_equal(#comment.replies, 2, "the final answer is appended once")

local review = require("utils.diffview_review")
review.set_active_guide_context({
  repo = temp_dir,
  path = temp_dir .. "/guide.json",
  assistant_name = "offline-main",
  base_oid = "base-pinned",
  head_oid = "head-pinned",
})
local original_send = pi.send_to_named_agent
local original_refresh = review.refresh_visible
review.refresh_visible = function() end
pi.send_to_named_agent = function()
  error("parallel dispatch must not type into the main agent")
end
local ctx = { root = temp_dir, state_path = state_path, label = "offline" }
assert(review.dispatch_agent_reply(ctx, state, comment, "First parallel question"))
local first_request = comment.agent_request_id
local queued =
  vim.json.decode(table.concat(vim.fn.readfile(temp_dir .. "/agent-requests/" .. first_request .. ".json"), "\n"))
assert(queued.prompt:find("head-pinned", 1, true), "the worker receives the immutable review boundary")
assert(review.dispatch_agent_reply(ctx, state, comment, "Follow-up while investigating"))
vim.fn.writefile({
  vim.json.encode({
    comment_id = comment.local_id,
    request_id = first_request,
    status = "completed",
    body = "First answer while follow-up is queued",
  }),
}, vim.fs.joinpath(reply_dir, comment.local_id .. "--" .. first_request .. ".json"))
local before = #comment.replies
review_agent.ingest(state, state_path)
assert_equal(#comment.replies, before + 1, "a queued follow-up must not lose the earlier answer")
assert_equal(comment.agent_status, "pending", "the earlier answer must not complete the newer request")
pi.send_to_named_agent = original_send
review.refresh_visible = original_refresh
review.clear_active_guide_context()

vim.fn.delete(temp_dir, "rf")
print("diffview_review_agent: all tests passed")
