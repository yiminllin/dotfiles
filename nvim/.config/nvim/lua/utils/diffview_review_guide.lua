local M = {}

function M.diagram(value)
  if type(value) == "string" then
    return vim.split(value, "\n", { plain = true })
  end
  local lines = {}
  for _, line in ipairs(type(value) == "table" and value or {}) do
    if type(line) == "string" then
      for _, part in ipairs(vim.split(line, "\n", { plain = true })) do
        table.insert(lines, part)
      end
    end
  end
  return lines
end

function M.progress(entries, current, phoenix, width)
  local reviewed, position = 0, nil
  for index, item in ipairs(entries) do
    if item.viewed then
      reviewed = reviewed + 1
    end
    if item.path == current then
      position = index
    end
  end
  local total = #entries
  local filled = total > 0 and math.floor(reviewed * 8 / total) or 0
  local bar = "[" .. string.rep("#", filled) .. string.rep("-", 8 - filled) .. "]"
  local scope = phoenix and "Phoenix" or "All"
  if total == 0 then
    local text = scope .. " · no matching files · reviewed 0/0 " .. bar
    return width and vim.fn.strdisplaywidth(text) > width and (scope .. " · no files " .. bar) or text
  end
  local text = ("%s · position %s/%d · reviewed %d/%d %s"):format(scope, position or "-", total, reviewed, total, bar)
  if width and vim.fn.strdisplaywidth(text) > width then
    return ("%s %s/%d · done %d/%d %s"):format(scope, position or "-", total, reviewed, total, bar)
  end
  return text
end

function M.lines(guide, entries, current, phoenix)
  local lines, targets = { "PR flow", "" }, {}
  if guide then
    if guide.summary ~= "" then
      table.insert(lines, (guide.summary:gsub("[\r\n]", " ")))
    end
    table.insert(lines, "")
    for _, line in ipairs(guide.diagram) do
      table.insert(lines, line)
    end
    if #guide.diagram == 0 then
      table.insert(lines, "No diagram yet; ask Pi to update the guide.")
    end
  else
    table.insert(lines, "Guide not ready; you can continue reviewing while Pi prepares it.")
  end
  table.insert(lines, "")
  table.insert(lines, M.progress(entries, current, phoenix))
  table.insert(lines, "Recommended review route (Enter opens a file):")
  if #entries == 0 then
    table.insert(lines, phoenix and "No Phoenix-owned changed files at this revision." or "No changed files.")
  end
  for index, item in ipairs(entries) do
    local file = guide and guide.files_by_path[item.path]
    local reason = file and file.reason or nil
    if reason then
      reason = reason:gsub("[\r\n]", " ")
    end
    table.insert(
      lines,
      ("%s %s %d. %s%s"):format(
        item.path == current and ">" or " ",
        item.viewed and "[x]" or "[ ]",
        index,
        item.path,
        reason and (" — " .. reason) or ""
      )
    )
    targets[#lines] = item
  end
  if guide and #guide.high_risk > 0 then
    table.insert(lines, "")
    table.insert(lines, "Review focus:")
    for index = 1, math.min(3, #guide.high_risk) do
      table.insert(lines, "- " .. guide.high_risk[index]:gsub("[\r\n]", " "))
    end
  end
  return lines, targets
end

local POPUP_NS = vim.api.nvim_create_namespace("diffview_review_guide")

local function notify(message, level)
  vim.notify(message, level or vim.log.levels.INFO, { title = "Diffview Review" })
end

local function string_list(value)
  if type(value) == "string" and value ~= "" then
    return { value }
  end
  if type(value) ~= "table" then
    return {}
  end

  local result = {}
  for _, item in ipairs(value) do
    if item ~= nil and item ~= vim.NIL and tostring(item) ~= "" then
      table.insert(result, tostring(item))
    end
  end
  return result
end

local function positive_line(value)
  if type(value) ~= "number" and type(value) ~= "string" then
    return nil
  end

  local number = tonumber(value)
  if number and number >= 1 then
    return math.floor(number)
  end
end

local function string_id(value)
  if type(value) == "string" and value ~= "" then
    return value
  end
  if type(value) == "number" then
    return tostring(value)
  end
end

local function normalize_file(path)
  if not path or path == "" then
    return nil
  end

  return path:gsub("\\", "/"):gsub("^%./", "")
end

function M.normalize(decoded)
  if type(decoded) ~= "table" then
    return nil
  end

  local guide = {
    context = type(decoded.context) == "table" and decoded.context or {},
    pr_number = type(decoded.pr) == "table" and decoded.pr.number
      or (type(decoded.context) == "table" and decoded.context.pr_number or nil),
    pr_url = type(decoded.pr) == "table" and decoded.pr.url or nil,
    summary = type(decoded.summary) == "string" and decoded.summary or "",
    diagram = M.diagram(decoded.diagram),
    high_risk = string_list(decoded.high_risk),
    files = {},
    files_by_path = {},
  }

  for _, file in ipairs(type(decoded.files) == "table" and decoded.files or {}) do
    local path = type(file) == "table" and normalize_file(file.path) or nil
    if path and not guide.files_by_path[path] then
      local guide_file = {
        id = string_id(file.guide_id) or string_id(file.id),
        reason = type(file.reason) == "string" and file.reason or nil,
        path = path,
        suggestions = {},
      }
      for _, suggestion in ipairs(type(file.suggestions) == "table" and file.suggestions or {}) do
        local body = type(suggestion) == "table" and type(suggestion.body) == "string" and vim.trim(suggestion.body)
          or ""
        if body ~= "" then
          local start_line = positive_line(suggestion.line)
          local end_line = positive_line(suggestion.end_line) or start_line
          table.insert(guide_file.suggestions, {
            body = body,
            end_line = end_line,
            id = string_id(suggestion.guide_id) or string_id(suggestion.id),
            line = start_line,
            side = tostring(suggestion.side or "RIGHT"):upper() == "LEFT" and "LEFT" or "RIGHT",
            severity = type(suggestion.severity) == "string" and suggestion.severity or "Medium",
            why = type(suggestion.why) == "string" and suggestion.why or nil,
          })
        end
      end

      table.insert(guide.files, guide_file)
      guide.files_by_path[path] = guide_file
    end
  end

  return guide
end

function M.load(path, context)
  if not path then
    return nil
  end

  local stat = (vim.uv or vim.loop).fs_stat(path)
  local mtime = stat and (tostring(stat.mtime.sec) .. ":" .. tostring(stat.mtime.nsec) .. ":" .. stat.size) or -1
  if mtime == -1 then
    M.cache = { path = path, mtime = mtime, guide = nil }
    return nil
  end
  if M.cache and M.cache.path == path and M.cache.mtime == mtime then
    return M.cache.guide
  end

  local read_ok, lines = pcall(vim.fn.readfile, path)
  if not read_ok then
    notify("Could not read guide JSON: " .. path, vim.log.levels.WARN)
    M.cache = { path = path, mtime = mtime, guide = nil }
    return nil
  end

  local decode_ok, decoded = pcall(vim.fn.json_decode, table.concat(lines, "\n"))
  local guide = decode_ok and M.normalize(decoded) or nil
  if not guide then
    notify("Ignoring invalid guide JSON: " .. path, vim.log.levels.WARN)
  elseif
    context
    and context.head_oid
    and (guide.context.head_oid ~= context.head_oid or guide.context.base_oid ~= context.base_oid)
  then
    notify("Guide is stale for this revision; ask Pi to refresh it", vim.log.levels.WARN)
    guide = nil
  else
    guide.source_path = path
    if context then
      local paths = {}
      for _, file in ipairs(guide.files) do
        table.insert(paths, file.path)
      end
      local order = table.concat(paths, "\n")
      if context.review_order and context.review_order ~= order then
        notify("Guide review order updated; current file and progress were preserved")
      end
      context.review_order = order
    end
    guide.context_pr_number = context and context.pr_number or nil
    guide.repo_key = context and context.repo_key or nil
  end
  M.cache = { path = path, mtime = mtime, guide = guide }
  return guide
end

function M.refresh_popup(view, guide, entries, current, phoenix)
  if not M.popup or M.popup.view ~= view then
    return
  end
  local popup = M.popup
  if not vim.api.nvim_win_is_valid(popup.winid) or not vim.api.nvim_buf_is_valid(popup.bufnr) then
    M.popup = nil
    return
  end
  local lines, targets = M.lines(guide, entries, current, phoenix)
  popup.targets = targets
  if not vim.deep_equal(lines, vim.api.nvim_buf_get_lines(popup.bufnr, 0, -1, false)) then
    local saved = vim.api.nvim_win_call(popup.winid, vim.fn.winsaveview)
    vim.bo[popup.bufnr].modifiable = true
    vim.api.nvim_buf_set_lines(popup.bufnr, 0, -1, false, lines)
    vim.bo[popup.bufnr].modifiable = false
    saved.lnum = math.min(saved.lnum, #lines)
    vim.api.nvim_win_call(popup.winid, function()
      vim.fn.winrestview(saved)
    end)
  end
  vim.api.nvim_buf_clear_namespace(popup.bufnr, POPUP_NS, 0, -1)
  for line, item in pairs(targets) do
    if item.path == current then
      vim.api.nvim_buf_set_extmark(popup.bufnr, POPUP_NS, line - 1, 0, { line_hl_group = "DiffviewReviewStatusFile" })
    end
  end
end

function M.show(view, guide, entries, current, phoenix, jump)
  if M.popup and vim.api.nvim_win_is_valid(M.popup.winid) then
    if M.popup.view == view then
      vim.api.nvim_set_current_win(M.popup.winid)
      return
    end
    vim.api.nvim_win_close(M.popup.winid, true)
  end
  local lines = M.lines(guide, entries, current, phoenix)
  local longest = 52
  for _, line in ipairs(lines) do
    longest = math.max(longest, vim.fn.strdisplaywidth(line))
  end
  local width = math.min(longest, math.max(1, vim.o.columns - 4))
  local height = math.min(#lines, math.max(1, vim.o.lines - 4))
  local bufnr = vim.api.nvim_create_buf(false, true)
  vim.b[bufnr].diffview_review_guide = true
  vim.bo[bufnr].bufhidden = "wipe"
  vim.bo[bufnr].filetype = "text"
  local winid = vim.api.nvim_open_win(bufnr, true, {
    border = "rounded",
    relative = "editor",
    style = "minimal",
    col = math.max(math.floor((vim.o.columns - width) / 2), 0),
    row = math.max(math.floor((vim.o.lines - height) / 2), 0),
    width = width,
    height = height,
    title = " PR flow and review route ",
    title_pos = "center",
  })
  vim.wo[winid].wrap = false
  vim.wo[winid].conceallevel = 0
  M.popup = { bufnr = bufnr, winid = winid, view = view }
  M.refresh_popup(view, guide, entries, current, phoenix)
  local function close()
    if vim.api.nvim_win_is_valid(winid) then
      vim.api.nvim_win_close(winid, true)
    end
    if M.popup and M.popup.winid == winid then
      M.popup = nil
    end
  end
  vim.keymap.set("n", "q", close, { buffer = bufnr, nowait = true, silent = true })
  vim.keymap.set("n", "<Esc>", close, { buffer = bufnr, nowait = true, silent = true })
  vim.keymap.set("n", "<CR>", function()
    local item = M.popup and M.popup.targets[vim.api.nvim_win_get_cursor(winid)[1]]
    if item then
      close()
      jump(item)
    end
  end, { buffer = bufnr, nowait = true, silent = true, desc = "Open review route file" })
end

return M
