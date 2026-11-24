-- Render saved conversations and route replies/input without changing source identities.
local M = {}
local format = require("utils.diffview_review_format")

function M.identity(comment)
  return comment.local_id
    or comment.github_id
    or comment.guide_id
    or vim.json.encode({
      comment.source or "",
      comment.file or "",
      comment.side or "RIGHT",
      comment.line or vim.NIL,
      comment.end_line or vim.NIL,
      comment.created_at or "",
      comment.body or "",
    })
end

function M.find(state, id)
  if id == nil then
    return
  end
  for _, comment in ipairs(state.comments or {}) do
    if M.identity(comment) == id then
      return comment
    end
  end
end

function M.matches(comment, filter)
  if filter == "attention" then
    return comment.agent_unread or comment.agent_status == "blocked"
  elseif filter == "unread" then
    return comment.agent_unread
  end
  return not filter or comment.agent_status == filter
end

function M.list(state, filter, selected)
  local result = {}
  for _, comment in ipairs(state.comments or {}) do
    if M.matches(comment, filter) or M.identity(comment) == selected then
      table.insert(result, comment)
    end
  end
  return result
end

function M.editor(title, submit, initial, location)
  local return_window = vim.api.nvim_get_current_win()
  vim.cmd("botright 8new")
  local editor_window = vim.api.nvim_get_current_win()
  local buffer = vim.api.nvim_get_current_buf()
  vim.bo[buffer].buftype = "acwrite"
  vim.bo[buffer].bufhidden = "wipe"
  vim.bo[buffer].swapfile = false
  vim.bo[buffer].filetype = "markdown"
  vim.api.nvim_buf_set_name(buffer, "review-reply://" .. buffer .. "/" .. title)
  vim.api.nvim_buf_set_lines(buffer, 0, -1, false, vim.split(initial or "", "\n"))
  vim.api.nvim_create_autocmd("BufWriteCmd", {
    buffer = buffer,
    callback = function()
      local body = table.concat(vim.api.nvim_buf_get_lines(buffer, 0, -1, false), "\n")
      if vim.trim(body) == "" then
        return
      end
      vim.cmd.stopinsert()
      submit(body)
      vim.bo[buffer].modified = false
      -- Let :wq close the draft before handling the plain :w case.
      vim.schedule(function()
        if vim.api.nvim_win_is_valid(editor_window) then
          vim.api.nvim_win_close(editor_window, true)
        end
        if vim.api.nvim_win_is_valid(return_window) then
          vim.api.nvim_set_current_win(return_window)
        end
      end)
    end,
  })
  vim.wo[editor_window].winbar = (title .. (location and (" · " .. location) or "")):gsub("%%", "%%%%")
    .. "  |  Ctrl-s send · :q! discard"
  vim.keymap.set({ "n", "i" }, "<C-s>", "<cmd>write<CR>", { buffer = buffer })
  vim.schedule(function()
    if vim.api.nvim_get_current_buf() == buffer then
      vim.cmd.startinsert()
    end
  end)
end

local function comment_location(comment)
  local line = not format.is_file_level_comment(comment) and tonumber(comment.line) or nil
  if not line then
    return "file"
  end
  local first = tonumber(comment.start_line) or line
  local last = tonumber(comment.end_line) or line
  return first == last and tostring(first) or ("%s–%s"):format(math.min(first, last), math.max(first, last))
end

function M.location(comment)
  return comment.file .. ":" .. comment_location(comment)
end

local status_icons = {
  pending = "⏳",
  running = "🔍",
  blocked = "❓",
  completed = "✅",
  failed = "⚠️",
  unavailable = "⚠️",
  cancelled = "🛑",
  unread = "✉️",
  attention = "🔔",
}

local function status_label(status)
  local label = format.agent_status_label(status)
  local icon = status_icons[status]
  return icon and (icon .. " " .. label) or label
end

local function source_label(comment)
  local label = format.comment_source_label(comment)
  if format.is_guide_comment(comment) then
    return (label:gsub("^%S+ Guide", "📖 Guide", 1))
  elseif format.is_imported_github_comment(comment) then
    return "🌐 " .. label:gsub("^GH ", "")
  end
  return "📝 " .. label
end

local function message_card(lines, cards, width, name, body, response)
  local group = response and "DiffviewReviewThreadResponse" or "DiffviewReviewThreadQuestion"
  local function add(line, whole)
    table.insert(lines, line)
    cards[#lines] = { group = group, whole = whole }
  end
  local inner = width - vim.fn.strdisplaywidth("│  │")
  local function row(text, heading)
    text = text:gsub("\r$", ""):gsub("\t", "    ")
    repeat
      local part = text
      if vim.fn.strdisplaywidth(part) > inner then
        local count = inner
        part = vim.fn.strcharpart(text, 0, count, true)
        while vim.fn.strdisplaywidth(part) > inner do
          count = count - 1
          part = vim.fn.strcharpart(text, 0, count, true)
        end
        -- Keep words together when possible; do not discard spaces or punctuation.
        part = part:match("^(.*%S%s+)") or part
      end
      add("│ " .. part .. string.rep(" ", inner - vim.fn.strdisplaywidth(part)) .. " │", heading)
      text = text:sub(#part + 1)
    until text == ""
  end
  add(format.card_rule("╭", "╮", width), true)
  row(format.normalize_comment_text(name), true)
  for _, line in ipairs(vim.split(body, "\n", { plain = true })) do
    row(line, false)
  end
  add(format.card_rule("╰", "╯", width), true)
end

local function author_name(author, fallback)
  if type(author) ~= "string" or author == "" then
    return fallback
  end
  return author:lower() == "pi" and "Pi" or author
end

function M.lines(state, selected_id, filter, plan, width)
  local lines = {
    filter and ("Filter: " .. status_label(filter) .. " · ga All threads") or "All threads",
    "↑/↓ Browse · Space Read · Enter Source · r Reply · m Menu",
    "",
  }
  local rows = {}
  local conversations = M.list(state, filter, selected_id)
  local selected_index
  for index, comment in ipairs(conversations) do
    if M.identity(comment) == selected_id then
      selected_index = index
    end
    local label = status_label(comment.agent_status)
    if comment.local_resolved then
      label = label .. " · Resolved locally"
    elseif comment.resolved then
      label = label .. " · Resolved"
    end
    if comment.agent_unread then
      label = label .. " · ✉️ unread"
    end
    local preview = format.comment_preview(comment, 48)
    table.insert(
      lines,
      ("%s %s · %s · %s"):format(M.identity(comment) == selected_id and ">" or " ", M.location(comment), label, preview)
    )
    rows[#lines] = M.identity(comment)
  end
  if next(rows) == nil then
    table.insert(lines, filter and "No matching conversations." or "Ask Pi with <leader>gdA, or add a local comment.")
  end
  local comment = M.find(state, selected_id)
  local detail_line, cards
  if comment then
    cards = {}
    width = math.max(8, width or 72)
    vim.list_extend(lines, {
      "",
      "────────────────────────────────────────",
    })
    detail_line = #lines + 1
    vim.list_extend(lines, {
      ("Thread %d/%d · [t / ]t · r Reply"):format(selected_index or 1, #conversations),
      filter and (status_label(filter) .. " · ga All threads") or "All threads",
      "# " .. M.location(comment) .. " " .. (comment.side or "RIGHT"),
    })
    if plan then
      local chunks = require("utils.diffview_review_chunks")
      local previous
      for _, match in ipairs(chunks.comment_hunks(plan, comment)) do
        local section = match.section
        if previous ~= section.id then
          table.insert(lines, ("Section: %d. %s"):format(section.number, section.title))
          previous = section.id
        end
        table.insert(
          lines,
          ("Hunk: %d · %s"):format(match.index, chunks.hunk_location(match.hunk, comment.side or "RIGHT"))
        )
      end
    end
    vim.list_extend(lines, {
      "",
      "────────────────────────────────────────",
      "",
    })
    table.insert(lines, source_label(comment))
    local status = format.comment_status_text(comment)
    if status ~= "" then
      table.insert(lines, status)
    end
    if comment.local_resolved then
      table.insert(lines, "Resolved locally; GitHub was not changed.")
    elseif comment.resolved then
      table.insert(lines, "Resolved.")
    end
    if comment.github_url then
      table.insert(lines, comment.github_url)
    end
    table.insert(lines, "")
    local username = vim.env.USER or vim.env.LOGNAME or "You"
    local fallback = format.is_guide_comment(comment) and "Guide"
      or (format.is_imported_github_comment(comment) and "GitHub" or username)
    message_card(lines, cards, width, author_name(comment.author, fallback), format.comment_body(comment), false)
    for _, reply in ipairs(comment.replies or {}) do
      table.insert(lines, "")
      local author = author_name(reply.author, reply.request_id and "Pi" or username)
      message_card(lines, cards, width, author, reply.body or "", author == "Pi")
    end
    if comment.agent_partial and comment.agent_partial ~= "" then
      table.insert(lines, "")
      message_card(lines, cards, width, "Pi · investigating", comment.agent_partial, true)
    end
    if comment.agent_activity and comment.agent_status ~= "completed" then
      vim.list_extend(lines, { "", "Activity: " .. comment.agent_activity })
    end
    if comment.agent_status == "blocked" then
      local input = comment.agent_input or {}
      vim.list_extend(lines, { "", "Needs input:" })
      vim.list_extend(lines, vim.split(tostring(input.title or input.method), "\n"))
      if input.message then
        vim.list_extend(lines, vim.split(input.message, "\n"))
      end
      table.insert(lines, "Press m → Answer Pi's question. Other conversations continue.")
    end
    if comment.agent_error then
      vim.list_extend(lines, { "", "Error: " .. comment.agent_error })
    end
  end
  return lines, rows, detail_line, cards
end

function M.respond(state_path, comment)
  local input = comment and comment.agent_input
  if not input then
    return
  end
  local request_id = comment.agent_request_id
  local function answer(value)
    local response = { id = input.id }
    if value == nil then
      response.cancelled = true
    elseif input.method == "confirm" then
      response.confirmed = value == "Allow"
    else
      response.value = value
    end
    require("utils.diffview_review_agent").control(state_path, request_id, response)
  end
  if input.method == "select" or input.method == "confirm" then
    vim.ui.select(
      input.options or { "Deny", "Allow" },
      { prompt = input.title or input.message or "Review input" },
      answer
    )
  elseif input.method == "editor" then
    M.editor("Agent input", answer, input.prefill)
  else
    vim.ui.input({ prompt = vim.split(input.title or "Review input", "\n")[1] .. ": " }, answer)
  end
end

return M
