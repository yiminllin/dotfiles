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

function M.new_id(prefix)
  id_counter = id_counter + 1
  local timestamp = os.date("!%Y%m%dT%H%M%SZ")
  local pid = vim.fn.getpid and vim.fn.getpid() or 0
  return ("%s-%s-%s-%d"):format(prefix, timestamp, tostring(pid), id_counter)
end

function M.reply_dir(state_path)
  return vim.fs.joinpath(vim.fn.fnamemodify(state_path, ":p:h"), "agent-replies")
end

function M.reply_path(state_path, comment_id, request_id)
  local filename = (comment_id .. "--" .. request_id):gsub("[^%w._-]", "-") .. ".json"
  return vim.fs.joinpath(M.reply_dir(state_path), filename)
end

function M.build_prompt(opts)
  local line_label = tostring(opts.line or "file-level")
  if opts.end_line and opts.end_line ~= opts.line then
    line_label = line_label .. "-" .. tostring(opts.end_line)
  end
  local body = tostring(opts.body or ""):gsub("%s+", " ")

  return table.concat({
    "A new automatic Diffview review request is ready.",
    "Comment ID: " .. opts.comment_id,
    "Request ID: " .. opts.request_id,
    "Target: " .. opts.file .. ":" .. line_label,
    "Comment: " .. body,
    "State (read-only): " .. opts.state_path,
    "Reply artifact: " .. opts.reply_path,
    "Review the comment using this persistent review session and inspect relevant local code as needed.",
    "Write one raw JSON object with comment_id, request_id, author, body, created_at, and optional status/error.",
    "Write atomically via a temporary file in the same directory followed by rename to the exact reply artifact path.",
    "Do not edit diffview-review.json and do not mutate or post to GitHub.",
  }, " ")
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
    elseif not comment or string_id(comment.agent_request_id) ~= request_id then
      stats.stale = stats.stale + 1
    else
      local body = type(artifact.body) == "string" and vim.trim(artifact.body) or ""
      local error_message = type(artifact.error) == "string" and vim.trim(artifact.error) or ""
      local artifact_status = type(artifact.status) == "string" and artifact.status:lower() or ""
      if artifact_status == "failed" or (body == "" and error_message ~= "") then
        local failure = error_message ~= "" and error_message or "Persistent Pi review failed"
        if comment.agent_status ~= "failed" or comment.agent_error ~= failure then
          comment.agent_status = "failed"
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
        comment.replies = type(comment.replies) == "table" and comment.replies or {}
        table.insert(comment.replies, {
          author = type(artifact.author) == "string" and vim.trim(artifact.author) ~= "" and artifact.author or "pi",
          body = body,
          created_at = type(artifact.created_at) == "string" and artifact.created_at
            or os.date("!%Y-%m-%dT%H:%M:%SZ"),
          request_id = request_id,
        })
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
