local M = {}

local function signature(snapshot)
  if not snapshot then
    return nil
  end
  local files = {}
  for _, item in ipairs(snapshot.entries) do
    table.insert(files, { item.path, item.entry.oldpath or "" })
  end
  return vim.json.encode({ snapshot.root, snapshot.base, snapshot.head, snapshot.scope, files })
end

-- Coordinates come from hunk counters, never from quoted Git filenames or buffer offsets.
function M.append_patch(lines, targets, path, patch)
  local left, right, old_remaining, new_remaining
  for _, text in ipairs(patch) do
    table.insert(lines, text)
    local target = { path = path, side = "RIGHT" }
    local a, ac, b, bc = text:match("^@@ %-(%d+),?(%d*) %+(%d+),?(%d*) @@")
    if a then
      left, right = tonumber(a), tonumber(b)
      old_remaining = ac == "" and 1 or tonumber(ac)
      new_remaining = bc == "" and 1 or tonumber(bc)
    elseif left and (old_remaining > 0 or new_remaining > 0) then
      local prefix = text:sub(1, 1)
      if prefix == "-" and old_remaining > 0 then
        target.side, target.line = "LEFT", left
        left, old_remaining = left + 1, old_remaining - 1
      elseif prefix == "+" and new_remaining > 0 then
        target.line = right
        right, new_remaining = right + 1, new_remaining - 1
      elseif prefix == " " and old_remaining > 0 and new_remaining > 0 then
        target.line = right
        left, right = left + 1, right + 1
        old_remaining, new_remaining = old_remaining - 1, new_remaining - 1
      end
    end
    targets[#lines] = target
  end
end

local function git_path(path)
  local escapes = {
    [7] = "\\a",
    [8] = "\\b",
    [9] = "\\t",
    [10] = "\\n",
    [11] = "\\v",
    [12] = "\\f",
    [13] = "\\r",
    [34] = '\\"',
    [92] = "\\\\",
  }
  local quoted, parts = false, {}
  for index = 1, #path do
    local byte = path:byte(index)
    if escapes[byte] or byte < 32 or byte == 127 then
      quoted = true
      parts[index] = escapes[byte] or ("\\%03o"):format(byte)
    else
      parts[index] = path:sub(index, index)
    end
  end
  local text = table.concat(parts)
  return quoted and ('"' .. text .. '"') or text
end

-- Including a copy's old path can also emit that source file's own changes.
-- Keep only the requested pair, with fixed Git quoting/prefix settings.
function M.file_patch(item, patch)
  local function header(old)
    return "diff --git " .. git_path("a/" .. old) .. " " .. git_path("b/" .. item.path)
  end
  local expected, renamed = header(item.path), header(item.entry.oldpath or item.path)
  local selected, result = false, {}
  for _, line in ipairs(patch) do
    if line:match("^diff %-%-git ") then
      selected = line == expected or line == renamed
    end
    if selected then
      table.insert(result, line)
    end
  end
  return result
end

local function notify(message)
  vim.notify(message, vim.log.levels.WARN, { title = "PR skim" })
end

local function close_window(state)
  if state.timer then
    vim.fn.timer_stop(state.timer)
    state.timer = nil
  end
  if state.win and vim.api.nvim_win_is_valid(state.win) then
    state.position = vim.api.nvim_win_call(state.win, vim.fn.winsaveview)
    vim.api.nvim_win_close(state.win, true)
  end
  state.win = nil
end

local function status(state)
  if not state.win or not vim.api.nvim_win_is_valid(state.win) then
    return
  end
  local label = state.loading and "Building diff…"
    or state.error
    or (
      state.outdated and "Outdated — press r to refresh"
      or "Enter: open change · r: refresh · q: close · za: fold file"
    )
  vim.wo[state.win].winbar = "PR skim · " .. label
end

local function replace(state, lines)
  vim.bo[state.buf].modifiable = true
  vim.api.nvim_buf_set_lines(state.buf, 0, -1, false, lines)
  vim.bo[state.buf].modifiable = false
  vim.bo[state.buf].modified = false
end

local function folds(state)
  if not state.win or not vim.api.nvim_win_is_valid(state.win) then
    return
  end
  vim.api.nvim_win_call(state.win, function()
    vim.cmd("silent! normal! zE")
    for _, section in ipairs(state.sections or {}) do
      if section.finish > section.start then
        vim.cmd(section.start .. "," .. section.finish .. "fold")
      end
    end
    vim.cmd("silent! normal! zR")
    if state.position then
      vim.fn.winrestview(state.position)
    end
  end)
end

local function build(state)
  local snapshot = state.snapshot()
  if not snapshot then
    notify("This committed review is no longer active")
    return
  end
  if state.process then
    state.process:kill(15)
    state.process = nil
  end
  state.generation = (state.generation or 0) + 1
  local generation = state.generation
  local old_target = state.win and state.targets and state.targets[vim.api.nvim_win_get_cursor(state.win)[1]]
  if state.win then
    state.position = vim.api.nvim_win_call(state.win, vim.fn.winsaveview)
  end
  state.loading, state.error = true, nil
  state.build_signature = signature(snapshot)
  status(state)
  local lines = {
    ("PR skim · %s · %d files · %s..%s"):format(
      snapshot.scope,
      #snapshot.entries,
      snapshot.base:sub(1, 8),
      snapshot.head:sub(1, 8)
    ),
    "",
  }
  local targets, sections = {}, {}
  local index = 0
  local function next_file()
    if state.disposed or state.generation ~= generation then
      return
    end
    index = index + 1
    local item = snapshot.entries[index]
    if not item then
      if #snapshot.entries == 0 then
        table.insert(lines, "No matching changed files in this scope.")
      end
      state.loading, state.targets, state.sections = false, targets, sections
      state.signature = signature(snapshot)
      state.outdated = state.signature ~= signature(state.snapshot())
      replace(state, lines)
      if old_target then
        for row, target in pairs(targets) do
          if target.path == old_target.path and target.side == old_target.side and target.line == old_target.line then
            state.position = state.position or {}
            state.position.lnum, state.position.col = row, 0
            break
          end
        end
      end
      folds(state)
      status(state)
      return
    end
    local start = #lines + 1
    table.insert(lines, ("# %d. %s"):format(index, item.path:gsub("[\r\n]", " ")))
    targets[start] = { path = item.path, side = "RIGHT" }
    local args = {
      "git",
      "--no-pager",
      "--literal-pathspecs",
      "-c",
      "diff.suppressBlankEmpty=false",
      "-c",
      "core.quotePath=false",
      "-C",
      snapshot.root,
      "diff",
      "--no-ext-diff",
      "--no-textconv",
      "--no-color",
      "--find-renames",
      "--unified=3",
      "--word-diff=none",
      "--output-indicator-new=+",
      "--output-indicator-old=-",
      "--output-indicator-context= ",
      "--src-prefix=a/",
      "--dst-prefix=b/",
      "--line-prefix=",
      "--submodule=short",
      snapshot.base,
      snapshot.head,
      "--",
    }
    if item.entry.status == "C" then
      table.insert(args, #args, "--find-copies")
      table.insert(args, #args, "--find-copies-harder")
    end
    if item.entry.oldpath then
      table.insert(args, item.entry.oldpath)
    end
    table.insert(args, item.path)
    state.process = vim.system(
      args,
      { text = true },
      vim.schedule_wrap(function(result)
        if state.disposed or state.generation ~= generation then
          return
        end
        state.process = nil
        if result.code ~= 0 then
          state.loading, state.error = false, "Diff failed — press r to retry"
          state.targets = {}
          notify(vim.trim(result.stderr or "Git diff failed"))
          status(state)
          return
        end
        local patch = vim.split(result.stdout or "", "\n", { plain = true })
        if patch[#patch] == "" then
          table.remove(patch)
        end
        local selected_patch = M.file_patch(item, patch)
        if #patch > 0 and #selected_patch == 0 then
          state.loading, state.error, state.targets = false, "Unrecognized diff — press r to retry", {}
          notify("Could not identify the diff for " .. item.path)
          status(state)
          return
        end
        M.append_patch(lines, targets, item.path, selected_patch)
        table.insert(sections, { start = start, finish = #lines })
        table.insert(lines, "")
        next_file()
      end)
    )
  end
  next_file()
end

local function jump(state)
  local snapshot = state.snapshot()
  if state.loading or state.error or state.signature ~= signature(snapshot) then
    state.outdated = true
    status(state)
    notify("Refresh the skim view before navigating")
    return
  end
  local target = state.targets[vim.api.nvim_win_get_cursor(state.win)[1]]
  if not target then
    notify("Select a change or file heading")
    return
  end
  local entry
  for _, item in ipairs(snapshot.entries) do
    if item.path == target.path then
      entry = item.entry
      break
    end
  end
  if not entry then
    notify("This file is no longer in the visible scope")
    return
  end
  close_window(state)
  snapshot.view:set_file(entry, false, true)
  local attempts = 0
  local function focus()
    if state.disposed or signature(state.snapshot()) ~= state.signature then
      notify("Review changed while opening the target")
      return
    end
    if snapshot.view.cur_entry == entry then
      for _, file in ipairs(entry.layout:files()) do
        local side = file.symbol == "a" and "LEFT" or "RIGHT"
        local revision = target.side == "LEFT" and snapshot.base or snapshot.head
        if
          side == target.side
          and (not target.line or file.rev.commit == revision)
          and file.bufnr
          and vim.api.nvim_buf_is_valid(file.bufnr)
        then
          for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
            if vim.api.nvim_win_get_buf(win) == file.bufnr then
              if target.line and (target.line < 1 or target.line > vim.api.nvim_buf_line_count(file.bufnr)) then
                notify("The target line is not valid in this revision")
                return
              end
              vim.api.nvim_set_current_win(win)
              if target.line then
                vim.api.nvim_win_set_cursor(win, { target.line, 0 })
              end
              return
            end
          end
        end
      end
    end
    attempts = attempts + 1
    if attempts < 100 then
      vim.defer_fn(focus, 20)
    else
      notify("Timed out loading the diff target")
    end
  end
  focus()
end

function M.open(opts)
  local snapshot = opts.snapshot()
  if not snapshot then
    notify("Open a review with two committed revisions before skimming")
    return
  end
  local view = snapshot.view
  local state = view.review_skim
  if not state then
    state = { buf = vim.api.nvim_create_buf(false, true), snapshot = opts.snapshot, targets = {} }
    view.review_skim = state
    vim.bo[state.buf].bufhidden = "hide"
    vim.bo[state.buf].buftype = "nofile"
    vim.bo[state.buf].swapfile = false
    vim.bo[state.buf].filetype = "diff"
    vim.b[state.buf].diffview_review_skim = true
    replace(state, { "Building PR diff…" })
    vim.keymap.set("n", "q", function()
      close_window(state)
    end, { buffer = state.buf, silent = true })
    vim.keymap.set("n", "r", function()
      build(state)
    end, { buffer = state.buf, silent = true })
    vim.keymap.set("n", "<CR>", function()
      jump(state)
    end, { buffer = state.buf, silent = true })
    view.emitter:once("view_closed", function()
      state.disposed = true
      close_window(state)
      if state.process then
        state.process:kill(15)
      end
      if vim.api.nvim_buf_is_valid(state.buf) then
        vim.api.nvim_buf_delete(state.buf, { force = true })
      end
      view.review_skim = nil
    end)
  end
  if state.win and vim.api.nvim_win_is_valid(state.win) then
    vim.api.nvim_set_current_win(state.win)
    return
  end
  state.win = vim.api.nvim_open_win(state.buf, true, {
    relative = "editor",
    row = 1,
    col = 1,
    width = math.max(1, vim.o.columns - 4),
    height = math.max(1, vim.o.lines - 4),
    style = "minimal",
    border = "rounded",
  })
  vim.wo[state.win].wrap = false
  vim.wo[state.win].cursorline = true
  vim.wo[state.win].number = true
  vim.wo[state.win].foldmethod = "manual"
  vim.wo[state.win].foldtext = "getline(v:foldstart)"
  if
    state.error
    or (state.loading and state.build_signature ~= signature(snapshot))
    or (not state.loading and state.signature ~= signature(snapshot))
  then
    build(state)
  else
    state.outdated = state.signature and state.signature ~= signature(snapshot) or false
    folds(state)
    status(state)
  end
  state.timer = vim.fn.timer_start(500, function()
    if not state.win or not vim.api.nvim_win_is_valid(state.win) then
      close_window(state)
      return
    end
    state.outdated = state.signature and state.signature ~= signature(state.snapshot()) or false
    status(state)
  end, { ["repeat"] = -1 })
end

return M
