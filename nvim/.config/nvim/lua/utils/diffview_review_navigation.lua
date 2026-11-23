-- Open exact pinned targets, using read-only snapshots outside the native diff.
local M = {}
local NS = vim.api.nvim_create_namespace("diffview_review_target")

local function notify(message)
  vim.notify(message, vim.log.levels.WARN, { title = "Review source" })
end

local function highlight(buffer, first, last, snapshot)
  vim.api.nvim_buf_clear_namespace(buffer, NS, 0, -1)
  if first then
    vim.api.nvim_buf_set_extmark(buffer, NS, first - 1, 0, {
      sign_text = "▎",
      sign_hl_group = "Special",
    })
    if snapshot then
      vim.api.nvim_set_hl(0, "DiffviewReviewSourceRange", { bg = "#e4ebef" })
      vim.api.nvim_buf_set_extmark(buffer, NS, first - 1, 0, {
        end_row = last or first,
        hl_group = "DiffviewReviewSourceRange",
        hl_eol = true,
        priority = 80,
      })
    elseif last and last > first then
      vim.api.nvim_buf_set_extmark(buffer, NS, last - 1, 0, {
        sign_text = "▎",
        sign_hl_group = "Special",
      })
    end
  end
end

local function snapshot_syntax(buffer, path)
  local ft = vim.filetype.match({ filename = path, buf = buffer })
  -- Use syntax without running FileType hooks on a historical buffer.
  if not ft or not ft:match("^[%w_]+$") then
    vim.cmd("noautocmd setlocal filetype=text")
    return
  end
  vim.cmd("noautocmd setlocal filetype=" .. ft)
  local language = vim.treesitter.language.get_lang(ft)
  if not pcall(vim.treesitter.start, buffer, language) then
    vim.cmd("runtime! syntax/" .. ft .. ".vim")
  end
end

-- Diffview fills commit buffers directly; :edit needs a reader for their virtual names.
function M.attach_reload(bufnr, root, file)
  local revision = file and file.rev and file.rev.commit
  if
    not revision
    or not file.path
    or file.nulled
    or file.binary
    or vim.bo[bufnr].buftype ~= "nowrite"
    or vim.b[bufnr].diffview_review_reload
  then
    return
  end
  local object = revision .. ":" .. file.path
  vim.api.nvim_create_autocmd("BufReadCmd", {
    buffer = bufnr,
    callback = function()
      local result = vim
        .system({ "git", "--no-pager", "show", "--no-ext-diff", "--no-textconv", object }, { cwd = root, text = true })
        :wait()
      if result.code ~= 0 or (result.stdout or ""):find("%z") then
        error("Could not reload pinned source: " .. object)
      end
      local lines = vim.split((result.stdout or ""):gsub("\n$", ""), "\n", { plain = true })
      vim.bo[bufnr].modifiable = true
      vim.api.nvim_buf_set_lines(bufnr, 0, -1, false, lines)
      vim.bo[bufnr].modified = false
      vim.bo[bufnr].modifiable = false
    end,
  })
  vim.b[bufnr].diffview_review_reload = true
end

local function valid_range(target, count)
  if not target.line then
    return true
  end
  local last = target.end_line or target.line
  if
    type(target.line) == "number"
    and type(last) == "number"
    and target.line % 1 == 0
    and last % 1 == 0
    and target.line >= 1
    and last >= target.line
    and last <= count
  then
    return true
  end
  notify("The target range is not valid in this revision")
  return false
end

function M.open(snapshot, target)
  local path = target.path or target.file
  local side = target.side or "RIGHT"
  local revision = side == "LEFT" and snapshot.base or snapshot.head
  if not path or path == "" or path:sub(1, 1) == "/" or path:find("%z") or ("/" .. path .. "/"):find("/%.%./") then
    notify("Source references must use a repository-relative path")
    return false
  end
  if target.anchor_status == "stale" or target.anchor_status == "ambiguous" then
    notify("This comment's source anchor needs to be refreshed")
    return false
  end
  if not revision or not revision:match("^%x+$") or (target.revision and target.revision ~= revision) then
    notify("The source reference does not match this pinned review")
    return false
  end
  local view = snapshot.view
  if
    (view.closing and view.closing:check())
    or not view.left
    or not view.right
    or view.left.commit ~= snapshot.base
    or view.right.commit ~= snapshot.head
  then
    notify("The review changed; reopen the source reference from the current panel")
    return false
  end
  local tab = vim.api.nvim_get_current_tabpage()
  local caller = vim.api.nvim_get_current_win()
  view._review_source_jump = (view._review_source_jump or 0) + 1
  local generation = view._review_source_jump
  local function current()
    return view._review_source_jump == generation
      and vim.api.nvim_get_current_tabpage() == tab
      and vim.api.nvim_get_current_win() == caller
      and view.left.commit == snapshot.base
      and view.right.commit == snapshot.head
      and not (view.closing and view.closing:check())
  end
  local item
  for _, candidate in ipairs(snapshot.entries) do
    if candidate.path == path or (side == "LEFT" and candidate.entry.oldpath == path) then
      item = candidate
      break
    end
  end
  if item then
    local loaded = view.cur_entry == item.entry and item.entry.opened == true
    if not loaded then
      view.emitter:on("file_open_post", function(_, entry)
        if entry == item.entry then
          loaded = true
          return true
        end
        if view._review_source_jump ~= generation then
          return true
        end
      end)
    end
    if view.cur_entry ~= item.entry then
      view:set_file(item.entry, false, true)
    end
    local attempts = 0
    local function focus()
      if not current() then
        return
      end
      if loaded and view.cur_entry == item.entry then
        for _, file in ipairs(item.entry.layout:files()) do
          local file_side = file.symbol == "a" and "LEFT" or "RIGHT"
          if
            file_side == side
            and file.rev.commit == revision
            and file.bufnr
            and vim.api.nvim_buf_is_valid(file.bufnr)
          then
            for _, win in ipairs(vim.api.nvim_tabpage_list_wins(tab)) do
              if vim.api.nvim_win_get_buf(win) == file.bufnr then
                if not valid_range(target, vim.api.nvim_buf_line_count(file.bufnr)) then
                  return
                end
                highlight(file.bufnr, target.line, target.end_line)
                if snapshot.before_open then
                  snapshot.before_open(win)
                end
                vim.api.nvim_set_current_win(win)
                vim.api.nvim_win_set_cursor(win, { target.line or 1, 0 })
                vim.cmd("normal! zvzz")
                if snapshot.on_open then
                  snapshot.on_open(win, file.bufnr)
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
        notify("Timed out loading the source target")
      end
    end
    focus()
  else
    vim.system(
      { "git", "--no-pager", "show", "--no-ext-diff", "--no-textconv", revision .. ":" .. path },
      {
        cwd = snapshot.root,
        text = true,
      },
      vim.schedule_wrap(function(result)
        if not current() then
          return
        end
        if result.code ~= 0 or (result.stdout or ""):find("%z") then
          notify("No readable source at " .. revision:sub(1, 12) .. ":" .. path)
          return
        end
        local lines = vim.split(result.stdout or "", "\n", { plain = true })
        if #lines > 1 and lines[#lines] == "" then
          table.remove(lines)
        end
        if not valid_range(target, #lines) then
          return
        end
        vim.cmd("botright new")
        local win = vim.api.nvim_get_current_win()
        local buffer = vim.api.nvim_get_current_buf()
        vim.api.nvim_buf_set_name(buffer, "review-source://" .. buffer .. "/" .. revision .. "/" .. path)
        vim.bo[buffer].buftype = "nofile"
        vim.bo[buffer].bufhidden = "wipe"
        vim.bo[buffer].swapfile = false
        vim.api.nvim_buf_set_lines(buffer, 0, -1, false, lines)
        vim.bo[buffer].modifiable = false
        snapshot_syntax(buffer, path)
        vim.wo.number = true
        vim.wo.relativenumber = false
        vim.wo.signcolumn = "yes:1"
        vim.wo.wrap = false
        vim.wo.winbar = (
          side
          .. " · "
          .. revision:sub(1, 12)
          .. " · "
          .. path
          .. " · read-only snapshot · q return"
        ):gsub("%%", "%%%%")
        highlight(buffer, target.line, target.end_line, true)
        vim.api.nvim_win_set_cursor(0, { target.line or 1, 0 })
        vim.cmd("normal! zz")
        if snapshot.on_open then
          snapshot.on_open(win, buffer)
        end
        local function close()
          if snapshot.on_return then
            snapshot.on_return()
          end
          vim.api.nvim_win_close(win, true)
          if vim.api.nvim_win_is_valid(caller) then
            vim.api.nvim_set_current_win(caller)
          end
        end
        vim.keymap.set("n", "q", close, { buffer = buffer, silent = true })
        vim.keymap.set("n", "<Esc>", close, { buffer = buffer, silent = true })
      end)
    )
  end
  return true
end

return M
