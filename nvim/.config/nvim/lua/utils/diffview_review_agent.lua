-- Exchange service requests and replies; Neovim owns changes to comment state.
local M = {}

local id_counter = 0

local function string_id(value)
  if type(value) == "string" and value ~= "" then
    return value
  end
  if type(value) == "number" then
    return tostring(value)
  end
end

local function read_json(path)
  local read_ok, lines = pcall(vim.fn.readfile, path)
  if not read_ok then
    return nil
  end

  local decode_ok, decoded = pcall(vim.fn.json_decode, table.concat(lines, "\n"))
  if not decode_ok or type(decoded) ~= "table" then
    return nil
  end
  return decoded
end

local function reply_exists(comment, request_id)
  for _, reply in ipairs(type(comment.replies) == "table" and comment.replies or {}) do
    if string_id(reply.request_id) == request_id then
      return true
    end
  end
  return false
end

local function append_reply(comment, artifact, request_id)
  comment.replies = type(comment.replies) == "table" and comment.replies or {}
  table.insert(comment.replies, {
    author = type(artifact.author) == "string" and vim.trim(artifact.author) ~= "" and artifact.author or "pi",
    body = vim.trim(artifact.body),
    created_at = type(artifact.created_at) == "string" and artifact.created_at or os.date("!%Y-%m-%dT%H:%M:%SZ"),
    request_id = request_id,
  })
  comment.agent_unread = true
end

function M.new_id(prefix)
  id_counter = id_counter + 1
  local timestamp = os.date("!%Y%m%dT%H%M%SZ")
  local pid = vim.fn.getpid and vim.fn.getpid() or 0
  return ("%s-%s-%s-%08d"):format(prefix, timestamp, tostring(pid), id_counter)
end

function M.reply_dir(state_path)
  return vim.fs.joinpath(vim.fn.fnamemodify(state_path, ":p:h"), "agent-replies")
end

function M.enqueue(state_path, request, directory_name)
  local directory = vim.fn.fnamemodify(state_path, ":p:h")
  local service = read_json(vim.fs.joinpath(directory, "review-service.json"))
  if not service or (vim.fn.localtime() * 1000 - (tonumber(service.updated_at) or 0)) > 10000 then
    return false,
      "Review service is not running; reopen `review` or run /review-service " .. directory .. " in the main Pi session"
  end
  if request.root and service.cwd ~= request.root then
    return false, "This review service belongs to another checkout; reopen review with the matching main Pi session"
  end
  local path = vim.fs.joinpath(directory, directory_name or "agent-requests", request.request_id .. ".json")
  vim.fn.mkdir(vim.fn.fnamemodify(path, ":h"), "p")
  local ok, error_message = pcall(function()
    assert(vim.fn.writefile({ vim.json.encode(request) }, path .. ".tmp") == 0, "Could not write review request")
    assert(vim.fn.rename(path .. ".tmp", path) == 0, "Could not publish review request")
  end)
  return ok, error_message
end

function M.guide_status(state_path)
  return read_json(vim.fs.joinpath(vim.fn.fnamemodify(state_path, ":p:h"), "guide-status.json"))
end

function M.control(state_path, request_id, action)
  local directory = vim.fs.joinpath(vim.fn.fnamemodify(state_path, ":p:h"), "agent-controls")
  vim.fn.mkdir(directory, "p")
  local path = vim.fs.joinpath(directory, request_id .. ".json")
  vim.fn.writefile({ vim.json.encode(action) }, path .. ".tmp")
  return vim.fn.rename(path .. ".tmp", path) == 0
end

function M.build_prompt(opts)
  local line_label = tostring(opts.line or "file-level")
  if opts.end_line and opts.end_line ~= opts.line then
    line_label = line_label .. "-" .. tostring(opts.end_line)
  end
  local body = tostring(opts.body or "")

  return table.concat({
    "Handle the newest Diffview review request. Inherited conversation is background context, not your task.",
    "Pinned base: " .. tostring(opts.base_oid or "unknown") .. "; pinned head: " .. tostring(
      opts.head_oid or "unknown"
    ),
    "Shared guide (read-only): " .. vim.fs.joinpath(vim.fn.fnamemodify(opts.state_path, ":h"), "guide.json"),
    "Diff side: " .. tostring(opts.side or "RIGHT"),
    "Comment ID: " .. opts.comment_id,
    "Request ID: " .. opts.request_id,
    "Target: " .. opts.file .. ":" .. line_label,
    "Comment: " .. body,
    "State (read-only): " .. opts.state_path,
    "The host persists and streams your answer; answer normally, without writing artifacts.",
    "Read shared state for all current comments and previous replies. Inspect relevant code and give a source-backed answer.",
    "Edit tracked working-tree files only if the reviewer asks. Do not edit review artifacts or mutate Git or GitHub.",
    "Only the main review agent owns guide updates. Report any changed understanding in your answer.",
  }, "\n")
end

function M.ingest(state, state_path)
  local comments_by_id = {}
  for _, comment in ipairs(state.comments or {}) do
    local comment_id = string_id(comment.local_id)
    if comment_id then
      comments_by_id[comment_id] = comment
    end
  end

  local stats = { completed = 0, failed = 0, invalid = 0, stale = 0 }
  local changed = false
  local reply_dir = M.reply_dir(state_path)
  if vim.fn.isdirectory(reply_dir) ~= 1 then
    return false, stats
  end

  local paths = vim.fn.globpath(reply_dir, "*.json", false, true)
  table.sort(paths)
  for _, path in ipairs(paths) do
    local artifact = read_json(path)
    local comment_id = artifact and string_id(artifact.comment_id) or nil
    local request_id = artifact and string_id(artifact.request_id) or nil
    local comment = comment_id and comments_by_id[comment_id] or nil

    if not artifact or not comment_id or not request_id then
      stats.invalid = stats.invalid + 1
    elseif
      comment
      and string_id(comment.agent_request_id) ~= request_id
      and vim.tbl_contains(comment.agent_requests or {}, request_id)
    then
      if
        artifact.status == "completed"
        and type(artifact.body) == "string"
        and vim.trim(artifact.body) ~= ""
        and not reply_exists(comment, request_id)
      then
        append_reply(comment, artifact, request_id)
        changed = true
        stats.completed = stats.completed + 1
      end
    elseif not comment or string_id(comment.agent_request_id) ~= request_id then
      stats.stale = stats.stale + 1
    else
      local body = type(artifact.body) == "string" and vim.trim(artifact.body) or ""
      local error_message = type(artifact.error) == "string" and vim.trim(artifact.error) or ""
      local artifact_status = type(artifact.status) == "string" and artifact.status:lower() or ""
      if artifact_status == "running" or artifact_status == "pending" or artifact_status == "blocked" then
        local input = type(artifact.input) == "table" and artifact.input or nil
        local activity = tostring(artifact.activity or "")
        if
          comment.agent_status ~= artifact_status
          or comment.agent_partial ~= body
          or comment.agent_activity ~= activity
          or not vim.deep_equal(comment.agent_input, input)
        then
          comment.agent_status = artifact_status
          comment.agent_partial = body
          comment.agent_activity = activity
          comment.agent_input = input
          comment.agent_updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
          changed = true
        end
      elseif artifact_status == "cancelled" then
        if comment.agent_status ~= "cancelled" then
          comment.agent_status = "cancelled"
          comment.agent_partial = nil
          comment.agent_input = nil
          changed = true
        end
      elseif artifact_status == "failed" or (body == "" and error_message ~= "") then
        local failure = error_message ~= "" and error_message or "Persistent Pi review failed"
        if comment.agent_status ~= "failed" or comment.agent_error ~= failure then
          comment.agent_status = "failed"
          comment.agent_input = nil
          comment.agent_error = failure
          comment.agent_updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
          changed = true
          stats.failed = stats.failed + 1
        end
      elseif artifact_status == "completed" and body == "" then
        -- A completion marker without a reply still needs to clear the spinner.
        if comment.agent_status ~= "completed" then
          comment.agent_status = "completed"
          comment.agent_error = nil
          comment.agent_updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
          changed = true
          stats.completed = stats.completed + 1
        end
      elseif body == "" then
        stats.invalid = stats.invalid + 1
      elseif not reply_exists(comment, request_id) then
        comment.agent_partial = nil
        comment.agent_input = nil
        append_reply(comment, artifact, request_id)
        comment.agent_status = "completed"
        comment.agent_error = nil
        comment.agent_updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
        changed = true
        stats.completed = stats.completed + 1
      elseif comment.agent_status ~= "completed" then
        comment.agent_status = "completed"
        comment.agent_error = nil
        comment.agent_updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
        changed = true
      end
    end
  end

  return changed, stats
end

return M
