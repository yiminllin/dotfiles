-- Archive review interactions separately from local UI and worker state.
local M = {}

local comment_fields = [[
  local_id github_id github_in_reply_to_id guide_id source kind severity body
  github_body why author created_at updated_at file path file_level line side
  start_line start_side end_line original_line original_start_line github_line
  commit_id original_commit_id github_head_oid pr_head_oid pr_number guide_pr_number
  github_url pull_request_url pr_url anchor review_context resolved
]]
local message_fields = "comment_id request_id author created_at body"
local revision_fields = message_fields .. " base_oid head_oid"
local section_names = { "comments", "questions", "answers", "guide_feedback", "user_input" }

local function pick(record, fields)
  local result = {}
  for key in fields:gmatch("%S+") do
    result[key] = record[key]
  end
  return result
end

local function read_json(path)
  return vim.json.decode(table.concat(vim.fn.readfile(path), "\n"))
end

-- Canonical keys keep Git diffs small and make it possible to deduplicate
-- records regardless of how a previous version ordered their keys.
local function encode(value)
  if type(value) ~= "table" or vim.islist(value) then
    if type(value) ~= "table" then
      return vim.json.encode(value)
    end
    return "[" .. table.concat(vim.tbl_map(encode, value), ", ") .. "]"
  end
  local fields = {}
  for _, key in ipairs(vim.fn.sort(vim.tbl_keys(value))) do
    fields[#fields + 1] = vim.json.encode(key) .. ": " .. encode(value[key])
  end
  return "{" .. table.concat(fields, ", ") .. "}"
end

local function archive(directory, comments)
  local path = vim.fs.joinpath(directory, "review-history.json")
  local previous = vim.fn.filereadable(path) == 1 and read_json(path) or { version = 1 }
  assert(previous.version == 1, "Unsupported review history version")
  local entries = { comments = {}, questions = {}, answers = {}, guide_feedback = {}, user_input = {} }
  for _, record in ipairs(comments or {}) do
    local comment = pick(record, comment_fields)
    if record.replies and #record.replies > 0 then
      comment.replies = vim.tbl_map(function(reply)
        return pick(reply, message_fields)
      end, record.replies)
    end
    if record.local_discussion then
      comment.local_discussion = pick(record.local_discussion, "user_reply assistant_reply planned_action")
    end
    table.insert(entries.comments, comment)
  end
  local function collect(folder, section, project)
    for _, file in ipairs(vim.fn.globpath(vim.fs.joinpath(directory, folder), "*.json", false, true)) do
      local record = project(read_json(file), file)
      if record and record.body and record.body ~= "" then
        table.insert(entries[section], record)
      end
    end
  end
  collect("agent-requests", "questions", function(request)
    local result = pick(request, revision_fields)
    result.body = request.body or request.prompt:match("\nComment: (.*)\nState %(read%-only%): ")
    assert(result.body, "Unknown Diffview question format")
    return result
  end)
  collect("agent-replies", "answers", function(reply)
    if reply.status == "completed" or reply.status == "answered" then
      return pick(reply, message_fields)
    end
  end)
  collect("guide-requests", "guide_feedback", function(request)
    return pick(request, revision_fields)
  end)
  collect("agent-controls", "user_input", function(response, file)
    return { request_id = vim.fn.fnamemodify(file, ":t:r"), body = response.value }
  end)

  local updated = false
  local sections = { '  "version": 1' }
  for _, key in ipairs(section_names) do
    local records, seen = {}, {}
    for _, record in ipairs(previous[key] or {}) do
      local encoded = encode(record)
      records[#records + 1] = "    " .. encoded
      seen[encoded] = true
    end
    for _, record in ipairs(entries[key]) do
      local encoded = encode(record)
      if not seen[encoded] then
        records[#records + 1] = "    " .. encoded
        seen[encoded] = true
        updated = true
      end
    end
    if #records > 0 then
      sections[#sections + 1] = '  "' .. key .. '": [\n' .. table.concat(records, ",\n") .. "\n  ]"
    end
  end
  if updated then
    local temp = path .. "." .. vim.fn.getpid() .. ".tmp"
    local lines = vim.split("{\n" .. table.concat(sections, ",\n") .. "\n}", "\n", { plain = true })
    assert(vim.fn.writefile(lines, temp) == 0, "Could not write " .. temp)
    assert(vim.fn.rename(temp, path) == 0, "Could not publish " .. path)
  end
end

function M.save(state_path, comments, notify)
  local directory = vim.fs.dirname(state_path)
  local kind = vim.fs.basename(vim.fs.dirname(directory))
  if kind ~= "pr-reviews" and kind ~= "branch-reviews" then
    return
  end
  local ok, error_message = pcall(archive, directory, comments)
  if not ok then
    (notify or vim.notify)("Could not archive Diffview history: " .. tostring(error_message), vim.log.levels.WARN)
  end
end

return M
