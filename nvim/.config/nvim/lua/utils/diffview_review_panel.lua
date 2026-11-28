-- One panel per review/tab combines the Guide with persistent conversation browsing.
local M = {}
local guide_view = require("utils.diffview_review_guide")
local threads = require("utils.diffview_review_threads")
local panels = {}
local NS = vim.api.nvim_create_namespace("diffview_review_panel")

function M.counts(state, entries, workspace)
  local counts = { reviewed = 0, total = #entries, running = 0, blocked = 0, unread = 0, pending = 0 }
  for _, item in ipairs(entries) do
    if item.viewed then
      counts.reviewed = counts.reviewed + 1
    end
  end
  if workspace and workspace.plan then
    local hunks = {}
    for _, chunk in ipairs(workspace.plan.chunks) do
      vim.list_extend(hunks, workspace.visible and workspace.visible(chunk) or chunk.hunks)
    end
    counts.reviewed, counts.total = require("utils.diffview_review_chunks").read_count(hunks, state)
    counts.unit = " hunks"
  end
  for _, comment in ipairs(threads.list(state)) do
    if counts[comment.agent_status] ~= nil then
      counts[comment.agent_status] = counts[comment.agent_status] + 1
    end
    if comment.agent_unread then
      counts.unread = counts.unread + 1
    end
  end
  return counts
end

function M.status(state, entries, width, workspace)
  local counts = M.counts(state, entries, workspace)
  local full = not width or width >= 85
  local text, winbar = {}, {}
  local function add(id, label)
    table.insert(text, label)
    local emphasis = id == 1 and "%#DiffviewReviewProseLabel#" or ""
    table.insert(winbar, ("%%%d@v:lua.DiffviewReviewStatusClick@%s%s%%*%%T"):format(id, emphasis, label))
  end
  add(
    1,
    full and (("Reviewed %d/%d"):format(counts.reviewed, counts.total) .. (counts.unit or ""))
      or ("%d/%d ✓"):format(counts.reviewed, counts.total)
  )
  for _, item in ipairs({
    { "blocked", 3, "needs input", "?" },
    { "unread", 4, "unread", "●" },
    { "running", 2, "investigating", "↻" },
    { "pending", 5, "queued", "…" },
  }) do
    local count = counts[item[1]]
    if count > 0 then
      add(item[2], full and (count .. " " .. item[3]) or (item[4] .. count))
    end
  end
  return { text = table.concat(text, " · "), winbar = table.concat(winbar, " · ") }
end

local function valid_window(panel)
  return panel.winid and vim.api.nvim_win_is_valid(panel.winid)
end

local function find(ctx)
  for _, panel in pairs(panels) do
    if
      panel.model.ctx.state_path == ctx.state_path
      and panel.model.ctx.view == ctx.view
      and panel.tabpage == vim.api.nvim_get_current_tabpage()
    then
      return panel
    end
  end
end

local function capture(panel)
  if valid_window(panel) and panel.displayed_mode then
    panel.views[panel.displayed_mode] = {
      view = vim.api.nvim_win_call(panel.winid, vim.fn.winsaveview),
      sections = panel.sections,
    }
  end
end

local function section_at(sections, line)
  local row, section
  for candidate, value in pairs(sections or {}) do
    if candidate <= line and (not row or candidate > row) then
      row, section = candidate, value
    end
  end
  return row, section
end

local function anchored_line(line, old, new, count)
  local row, section = section_at(old, line)
  if section then
    for new_row, value in pairs(new) do
      if value.id == section.id then
        local finish = count
        for candidate in pairs(new) do
          if candidate > new_row then
            finish = math.min(finish, candidate - 1)
          end
        end
        return math.min(new_row + line - row, finish)
      end
    end
  end
  return math.min(line, count)
end

local modes = { "guide", "threads" }
local prose_labels = {
  ["before"] = true,
  ["after"] = true,
  ["purpose/change"] = true,
  ["purpose / change"] = true,
  ["finding"] = true,
  ["question"] = true,
  ["verification gap"] = true,
  ["why"] = true,
  ["why it matters"] = true,
  ["source"] = true,
  ["section"] = true,
  ["sections"] = true,
  ["hunk"] = true,
  ["activity"] = true,
  ["needs input"] = true,
  ["error"] = true,
}

local pseudocode_keywords = {}
for word in
  (
    "if then else elif elseif end match case when otherwise for each in while do break continue return yield "
    .. "fn function let const mut var set struct enum impl use def class async await try catch raise "
    .. "true false nil none null and or not"
  ):gmatch("%S+")
do
  pseudocode_keywords[word] = true
end

local function highlight_pseudocode(buffer, row, line)
  local col = 1
  while col <= #line do
    local char = line:sub(col, col)
    local pair = line:sub(col, col + 1)
    local finish, group = col, nil
    if pair == "//" or pair == "--" or (char == "#" and (col == 1 or line:sub(col - 1, col - 1):match("%s"))) then
      finish, group = #line, "DiffviewReviewPseudoComment"
    elseif char == '"' or char == "'" then
      local next_col = col + 1
      while next_col <= #line do
        local item = line:sub(next_col, next_col)
        next_col = next_col + (item == "\\" and 2 or 1)
        if item == char then
          break
        end
      end
      finish, group = math.min(next_col - 1, #line), "DiffviewReviewPseudoString"
    else
      local _, last = line:find("^[%w_]+", col)
      if last then
        finish = last
        if pseudocode_keywords[line:sub(col, last):lower()] then
          group = "DiffviewReviewPseudoKeyword"
        elseif char:match("%d") then
          group = "DiffviewReviewPseudoString"
        elseif line:find("^%s*%(", last + 1) then
          group = "DiffviewReviewPseudoCall"
        end
      end
    end
    if group then
      vim.api.nvim_buf_set_extmark(buffer, NS, row, col - 1, {
        end_col = finish,
        hl_group = group,
        priority = 160,
      })
    end
    col = finish + 1
  end
end

local function render(panel)
  capture(panel)
  local previous = panel.views[panel.displayed_mode]
  local model = panel.model
  local workspace = model.ctx.view and model.ctx.view.review_chunks
  local view_key = panel.mode == "guide" and workspace and workspace.active and ("guide:" .. workspace.active)
    or panel.mode
  local tabs = {}
  for _, mode in ipairs(modes) do
    local title = mode == "guide" and "📖 Guide" or "💬 Threads"
    table.insert(tabs, mode == panel.mode and ("[" .. title .. "]") or title)
  end
  local view = model.ctx.view
  local base = view and view.left and view.left.commit
  local head = view and view.right and view.right.commit
  local boundary = (base and base:sub(1, 8) or "base") .. ".." .. (head and head:sub(1, 8) or "working tree")
  local lines = {
    (model.label or "Review") .. " · " .. boundary .. " · " .. (model.phoenix and "Phoenix" or "All"),
    table.concat(tabs, "   ") .. " · Tab · ? help",
    "",
  }
  panel.sections, panel.targets, panel.rows = { [1] = { id = "panel" } }, {}, {}
  local body, targets, sections, cards, code_rows
  local width = valid_window(panel) and vim.api.nvim_win_get_width(panel.winid) or 72
  if panel.mode == "guide" then
    local status = model.callbacks.status and model.callbacks.status() or nil
    body, targets, sections, code_rows =
      guide_view.lines(model.guide, model.entries, model.current, model.phoenix, status, workspace, model.state, {
        width = width,
      })
  else
    local gutter = valid_window(panel) and vim.fn.getwininfo(panel.winid)[1].textoff or 0
    body, targets, panel.detail_line, cards =
      threads.lines(model.state, panel.selected, panel.filter, workspace and workspace.plan, width - gutter)
    panel.detail_line = panel.detail_line and panel.detail_line + #lines
  end
  local offset = #lines
  for row, target in pairs(targets) do
    if panel.mode ~= "threads" then
      panel.targets[row + offset] = target
    else
      panel.rows[row + offset] = target
    end
  end
  for row, section in pairs(sections or {}) do
    panel.sections[row + offset] = section
  end
  vim.list_extend(lines, body)
  if not vim.deep_equal(lines, vim.api.nvim_buf_get_lines(panel.buffer, 0, -1, false)) then
    vim.bo[panel.buffer].modifiable = true
    vim.api.nvim_buf_set_lines(panel.buffer, 0, -1, false, lines)
    vim.bo[panel.buffer].modifiable = false
  end
  vim.api.nvim_buf_clear_namespace(panel.buffer, NS, 0, -1)
  local col = 0
  for index, tab in ipairs(tabs) do
    vim.api.nvim_buf_set_extmark(panel.buffer, NS, 1, col, {
      end_col = col + #tab,
      hl_group = modes[index] == panel.mode and "DiffviewReviewGuideHeading" or "Comment",
      priority = 150,
    })
    col = col + #tab + 3
  end
  local fence
  for row, line in ipairs(lines) do
    local opening = not fence and (line:match("^ ? ? ?(```+)") or line:match("^ ? ? ?(~~~+)"))
    local in_fence = fence or opening
    if fence and line:match("^ ? ? ?" .. fence .. fence:sub(1, 1) .. "*%s*$") then
      fence = nil
    elseif opening then
      fence = opening
    end
    local group
    if panel.mode == "guide" and panel.sections[row] then
      local section = panel.sections[row]
      local id = section.id
      if section.title_range then
        vim.api.nvim_buf_set_extmark(panel.buffer, NS, row - 1, section.title_range[1], {
          end_col = section.title_range[2],
          hl_group = "DiffviewReviewGuideSubheading",
          priority = 150,
        })
      end
      group = line:match("^## ") and "DiffviewReviewGuideHeading"
        or (line:match("^### ") or id:match("^core:") or id:match("^section:core:"))
          and "DiffviewReviewGuideSubheading"
      if id:match("^section:hunk:") and line:find("• ▶ ", 1, true) then
        group = "DiffviewReviewGuideSubheading"
      end
    end
    local card = cards and cards[row - offset]
    if card then
      local function style(first, last)
        vim.api.nvim_buf_set_extmark(panel.buffer, NS, row - 1, first, {
          end_col = last,
          hl_group = card.group,
          priority = 150,
        })
      end
      style(0, card.whole and #line or #"│")
      if not card.whole then
        style(#line - #"│", #line)
      end
    end
    if panel.mode == "guide" and not in_fence then
      local section = panel.sections[row]
      if
        (section and (section.id:match("^chunk:") or section.id == "overall-progress"))
        or line:match("^Sections viewed  ")
        or line:match("^%s*Hunks viewed  ")
      then
        local first, last = line:find("%[[^%]]+%] %d+/%d+")
        if first then
          vim.api.nvim_buf_set_extmark(panel.buffer, NS, row - 1, first - 1, {
            end_col = last,
            hl_group = "DiffviewReviewProseLabel",
            priority = 150,
          })
        end
      end
    end
    local code_style = code_rows and code_rows[row - offset]
    if code_style then
      vim.api.nvim_buf_set_extmark(panel.buffer, NS, row - 1, 0, {
        end_col = #line,
        hl_group = code_style == "text" and "DiffviewReviewGuideCode" or nil,
        line_hl_group = "DiffviewReviewGuideCode",
        priority = 150,
      })
      if code_style == "pseudocode" then
        highlight_pseudocode(panel.buffer, row - 1, line)
      end
    elseif panel.targets[row] and line:sub(1, #"↗ ") == "↗ " then
      vim.api.nvim_buf_set_extmark(panel.buffer, NS, row - 1, 0, {
        end_col = #line,
        hl_group = "DiffviewReviewGuideLink",
        priority = 150,
      })
    elseif group then
      local marker = line:match("^#+ ")
      if marker then
        vim.api.nvim_buf_set_extmark(panel.buffer, NS, row - 1, 0, {
          end_col = #marker,
          conceal = "",
          priority = 150,
        })
      end
      vim.api.nvim_buf_set_extmark(panel.buffer, NS, row - 1, 0, {
        end_col = #line,
        hl_group = group,
        line_hl_group = group,
        priority = 150,
      })
    elseif line:find("─", 1, true) == 1 then
      vim.api.nvim_buf_set_extmark(panel.buffer, NS, row - 1, 0, { line_hl_group = "Comment" })
    elseif not in_fence then
      local start, label, finish = line:match("^ ? ? ?[-*+] +()([%a /]+):()")
      if not label then
        start, label, finish = line:match("^ ? ? ?()([%a /]+):()")
      end
      if card and not card.whole then
        start, label, finish = line:match("^│ +()([%a /]+):()")
      end
      if label and prose_labels[label:lower()] then
        vim.api.nvim_buf_set_extmark(panel.buffer, NS, row - 1, start - 1, {
          end_col = finish - 1,
          hl_group = "DiffviewReviewProseLabel",
          priority = 150,
        })
      end
    end
  end
  if valid_window(panel) then
    vim.wo[panel.winid].wrap = panel.mode == "threads"
    vim.wo[panel.winid].linebreak = false
    vim.wo[panel.winid].breakindent = false
    vim.wo[panel.winid].showbreak = ""
    vim.wo[panel.winid].list = false
    vim.wo[panel.winid].conceallevel = 2
    vim.wo[panel.winid].concealcursor = "nc"
    vim.wo[panel.winid].number = false
    vim.wo[panel.winid].relativenumber = false
    vim.wo[panel.winid].winbar =
      M.status(model.state, model.entries, vim.api.nvim_win_get_width(panel.winid), workspace).winbar
    local saved = (panel.following_link and previous) or panel.views[view_key]
    if
      not panel.following_link
      and workspace
      and workspace.active
      and panel.mode == "guide"
      and panel.displayed_mode ~= view_key
      and previous
      and panel.displayed_mode:match("^guide")
    then
      local _, anchor = section_at(previous.sections, previous.view.lnum)
      if anchor and anchor.id:match("^chunk:") then
        local view = vim.deepcopy(previous.view)
        for row, section in pairs(panel.sections) do
          if section.id == "chunk:" .. workspace.active then
            view.topline = anchored_line(view.topline, previous.sections, panel.sections, #lines)
            view.lnum, view.col = row, 0
            vim.api.nvim_win_call(panel.winid, function()
              vim.fn.winrestview(view)
            end)
            panel.displayed_mode = view_key
            return
          end
        end
      end
    end
    if saved then
      local view = vim.deepcopy(saved.view)
      if panel.mode ~= "threads" then
        view.lnum = anchored_line(view.lnum, saved.sections, panel.sections, #lines)
        view.topline = anchored_line(view.topline, saved.sections, panel.sections, #lines)
      else
        view.lnum = math.min(view.lnum, #lines)
      end
      vim.api.nvim_win_call(panel.winid, function()
        vim.fn.winrestview(view)
      end)
    else
      local first = 1
      if panel.mode == "guide" and workspace and workspace.active then
        for row, section in pairs(panel.sections) do
          if section.id == "section:purpose:" .. workspace.active then
            first = row
            break
          end
        end
      end
      vim.api.nvim_win_set_cursor(panel.winid, { first, 0 })
      if first > 1 then
        vim.api.nvim_win_call(panel.winid, function()
          vim.cmd("normal! zt")
        end)
      end
    end
  end
  panel.displayed_mode = view_key
end

local function dock_width()
  return math.max(1, math.floor(vim.o.columns * 0.25))
end

local function expanded_config()
  local width = math.max(1, math.floor(vim.o.columns * 0.90))
  local height = math.max(1, math.floor(vim.o.lines * 0.88))
  return {
    relative = "editor",
    row = math.max(0, math.floor((vim.o.lines - height - 2) / 2)),
    col = math.max(0, math.floor((vim.o.columns - width - 2) / 2)),
    width = width,
    height = height,
  }
end

local function open_window(panel)
  panel.displayed_mode = nil
  if panel.expanded then
    local config = expanded_config()
    config.style = "minimal"
    config.border = "rounded"
    config.title = " Review "
    panel.winid = vim.api.nvim_open_win(panel.buffer, true, config)
  else
    if vim.api.nvim_win_is_valid(panel.source_win) then
      vim.api.nvim_set_current_win(panel.source_win)
    end
    vim.cmd("topleft vsplit")
    panel.winid = vim.api.nvim_get_current_win()
    vim.api.nvim_win_set_buf(panel.winid, panel.buffer)
    vim.api.nvim_win_set_width(panel.winid, dock_width())
    vim.wo[panel.winid].winfixwidth = true
  end
  vim.wo[panel.winid].signcolumn = "no"
  vim.wo[panel.winid].foldcolumn = "0"
  vim.wo[panel.winid].winhl = table.concat({
    "Normal:NormalFloat",
    "NormalNC:NormalFloat",
    "EndOfBuffer:NormalFloat",
    "@markup.raw.block.markdown:DiffviewReviewCodeText",
    "markdownCodeBlock:NormalFloat",
  }, ",")
end

local function expand(panel)
  capture(panel)
  panel.expanded = not panel.expanded
  if panel.expanded then
    local config = expanded_config()
    config.border, config.title = "rounded", " Review "
    vim.api.nvim_win_set_config(panel.winid, config)
  else
    vim.api.nvim_win_set_config(panel.winid, { split = "left", win = -1, width = dock_width() })
  end
  vim.wo[panel.winid].winfixwidth = not panel.expanded
  render(panel)
end

function M.close(panel)
  capture(panel)
  local focused = valid_window(panel) and vim.api.nvim_get_current_win() == panel.winid
  if valid_window(panel) then
    vim.api.nvim_win_close(panel.winid, true)
  end
  panel.winid = nil
  if focused and vim.api.nvim_win_is_valid(panel.source_win) then
    vim.api.nvim_set_current_win(panel.source_win)
  end
end

local function select(panel, id, reveal)
  panel.selected = id
  local comment = threads.find(panel.model.state, id)
  if comment and panel.model.callbacks.read then
    panel.model.callbacks.read(comment)
  end
  render(panel)
  if reveal and panel.detail_line and valid_window(panel) then
    vim.api.nvim_win_set_cursor(panel.winid, { panel.detail_line, 0 })
    vim.api.nvim_win_call(panel.winid, function()
      vim.cmd("normal! zt")
    end)
  end
end

local function next_thread(panel, direction, filter, browse)
  local candidates = threads.list(panel.model.state, filter)
  if #candidates == 0 then
    vim.notify("No matching review conversations", vim.log.levels.INFO, { title = "Review" })
    return false
  end
  -- Iterate in review order even after an unread conversation has been marked read.
  local all, start = threads.list(panel.model.state), direction == -1 and 1 or 0
  local cursor_id = panel.rows[vim.api.nvim_win_get_cursor(panel.winid)[1]]
  for index, comment in ipairs(all) do
    if threads.identity(comment) == (cursor_id or panel.selected) then
      start = index
    end
  end
  for step = 1, #all do
    local comment = all[(start - 1 + step * direction) % #all + 1]
    if threads.matches(comment, filter) then
      panel.mode, panel.filter = "threads", filter
      local id = threads.identity(comment)
      if browse then
        for row, candidate in pairs(panel.rows) do
          if candidate == id then
            vim.api.nvim_win_set_cursor(panel.winid, { row, 0 })
            break
          end
        end
      else
        select(panel, id, true)
      end
      return true
    end
  end
end

local function current_comment(panel)
  local id = panel.rows[vim.api.nvim_win_get_cursor(panel.winid)[1]] or panel.selected
  return threads.find(panel.model.state, id)
end

local function show_selection(panel)
  if panel.mode == "threads" and not panel.selected then
    local candidates = threads.list(panel.model.state, panel.filter)
    local chosen = candidates[1]
    for _, comment in ipairs(candidates) do
      if threads.matches(comment, "attention") then
        chosen = comment
        break
      end
    end
    if chosen then
      select(panel, threads.identity(chosen), true)
      return
    end
  end
  render(panel)
end

local function jump_to_heading(panel, id)
  for row, section in pairs(panel.sections) do
    if section.id == id then
      vim.wo[panel.winid].scrolloff = 0
      vim.api.nvim_win_call(panel.winid, function()
        vim.fn.winrestview({ lnum = row, col = 0, topline = row, leftcol = 0 })
      end)
      return
    end
  end
end

local function maps(panel)
  local function map(key, callback, description)
    vim.keymap.set("n", key, callback, { buffer = panel.buffer, silent = true, desc = description })
  end
  map("q", function()
    M.close(panel)
  end, "Close review panel")
  map("z", function()
    expand(panel)
  end, "Expand/restore review panel")
  for _, key in ipairs({ "<Tab>", "<S-Tab>" }) do
    map(key, function()
      local index = vim.fn.index(modes, panel.mode)
      panel.mode = modes[(index + (key == "<Tab>" and 1 or -1)) % #modes + 1]
      render(panel)
    end, "Switch Guide / Threads")
  end
  map("g1", function()
    if panel.mode == "guide" then
      jump_to_heading(panel, "overview")
    end
  end, "Jump to PR overview")
  map("g2", function()
    if panel.mode == "guide" then
      jump_to_heading(panel, "route")
    end
  end, "Jump to review sections")
  map("g3", function()
    if panel.mode == "guide" then
      local view = panel.model.ctx.view
      local workspace = view and view.review_chunks
      if workspace and workspace.active then
        jump_to_heading(panel, "section:purpose:" .. workspace.active)
      end
    end
  end, "Jump to active section details")
  map("?", function()
    local lines = {
      "Tab / Shift-Tab   Switch Guide / Threads",
      "z                 Expand or dock the panel",
      "Esc               Clear search highlights (in panel)",
      "q / Esc           Close this help",
      "",
    }
    vim.list_extend(lines, panel.mode == "guide" and {
      "Guide",
      "Enter       Open section, file, hunk, or source",
      "g1 / g2 / g3  Jump to overview / section list / active section",
      "]r / [r     Next / previous section",
      "]c / [c     Next / previous hunk",
      "v           Toggle item viewed / unviewed",
      "V           Mark whole section viewed",
      "r / u       Update / refine the guide",
    } or {
      "Threads",
      "Enter       Jump to comment in diff",
      "Up / Down   Browse conversations",
      "Space / Esc  Read conversation / return to list if no search highlights",
      "]t / [t      Read next / previous thread",
      "]a / [a      Next / previous unread reply or Pi question",
      "ga           Show all threads",
      "r / m        Reply / open action menu",
    })
    local buffer, win = vim.lsp.util.open_floating_preview(lines, "text", {
      border = "rounded",
      title = " Review shortcuts ",
    })
    vim.keymap.set("n", "<Esc>", "<cmd>close<CR>", { buffer = buffer, silent = true })
    vim.api.nvim_set_current_win(win)
  end, "Review panel help")
  local function jump()
    local target
    if panel.mode ~= "threads" then
      target = panel.targets[vim.api.nvim_win_get_cursor(panel.winid)[1]]
    else
      target = current_comment(panel)
      if target then
        select(panel, threads.identity(target), false)
      end
    end
    if target then
      if panel.expanded then
        expand(panel)
      end
      if panel.mode == "threads" then
        local id = threads.identity(target)
        panel.source_return = nil
        panel.model.callbacks.jump(target, {
          on_open = function(win, buf)
            panel.source_return = { win = win, buf = buf, id = id }
          end,
          on_return = function()
            M.return_to_thread(panel.model.ctx)
          end,
        })
      else
        local row = vim.api.nvim_win_get_cursor(panel.winid)[1]
        local _, anchor = section_at(panel.sections, row)
        panel.following_link = not target.chunk_id and target.line ~= nil
        panel.model.callbacks.jump(target, { keep_section = anchor and anchor.id:match("^section:") })
        panel.following_link = nil
      end
    end
  end
  map("<CR>", jump, "Open exact source target")
  map("<Esc>", function()
    if vim.v.hlsearch == 1 then
      vim.cmd.nohlsearch()
    elseif panel.mode == "threads" and panel.selected then
      local id = panel.selected
      panel.selected = nil
      render(panel)
      for row, candidate in pairs(panel.rows) do
        if candidate == id then
          vim.api.nvim_win_set_cursor(panel.winid, { row, 0 })
          break
        end
      end
    end
  end, "Clear search highlights or return to conversation list")
  map("<Space>", function()
    if panel.mode == "threads" then
      local comment = current_comment(panel)
      if comment then
        select(panel, threads.identity(comment), true)
      end
    else
      vim.cmd("normal! l")
    end
  end, "Read conversation details")
  for _, key in ipairs({ "<Up>", "<Down>" }) do
    map(key, function()
      if panel.mode == "threads" then
        next_thread(panel, key == "<Down>" and 1 or -1, panel.filter, true)
      else
        vim.cmd(key == "<Down>" and "normal! j" or "normal! k")
      end
    end, "Browse review conversations")
  end
  for key, direction in pairs({ ["]a"] = 1, ["[a"] = -1 }) do
    map(key, function()
      next_thread(panel, direction, "attention")
    end, "Next/previous conversation needing attention")
  end
  map("v", function()
    local target = panel.targets[vim.api.nvim_win_get_cursor(panel.winid)[1]]
    if panel.mode == "guide" and target and target.chunk_id then
      panel.model.callbacks.chunk("toggle_viewed", target)
    else
      vim.cmd("normal! v")
    end
  end, "Toggle review item viewed")
  map("V", function()
    local workspace = panel.model.ctx.view and panel.model.ctx.view.review_chunks
    if panel.mode == "threads" or not (workspace and workspace.plan) then
      vim.cmd("normal! V")
      return
    end
    local target = panel.targets[vim.api.nvim_win_get_cursor(panel.winid)[1]]
    panel.model.callbacks.chunk("viewed", target and target.chunk_id and { chunk_id = target.chunk_id } or nil)
  end, "Mark selected or active section viewed")
  for key, kind in pairs({ ["]r"] = "chunk", ["[r"] = "chunk", ["]c"] = "hunk", ["[c"] = "hunk" }) do
    map(key, function()
      if panel.mode == "guide" and panel.model.callbacks.step_chunk then
        panel.model.callbacks.step_chunk(key:sub(1, 1) == "]" and 1 or -1, kind)
      end
    end, "Next/previous review item")
  end
  local function reply(comment)
    select(panel, threads.identity(comment))
    if panel.expanded then
      expand(panel)
    end
    threads.editor("Reply", function(body)
      panel.model.callbacks.reply(comment, body)
    end, nil, threads.location(comment))
  end
  map("r", function()
    if panel.mode == "guide" then
      panel.model.callbacks.generate()
    else
      local comment = current_comment(panel)
      if comment then
        reply(comment)
      end
    end
  end, "Update guide / reply to thread")
  local function show_all()
    panel.filter, panel.selected = nil, nil
    render(panel)
    jump_to_heading(panel, "panel")
  end
  map("ga", function()
    if panel.mode == "threads" then
      show_all()
    end
  end, "Show all threads")
  for key, direction in pairs({ ["]t"] = 1, ["[t"] = -1 }) do
    map(key, function()
      if panel.mode == "threads" then
        next_thread(panel, direction, panel.filter)
      end
    end, "Read next/previous thread")
  end
  map("u", function()
    if panel.mode == "guide" then
      if panel.expanded then
        expand(panel)
      end
      panel.model.callbacks.refine()
    end
  end, "Refine guide")
  map("m", function()
    if panel.mode ~= "threads" then
      return
    end
    local comment = current_comment(panel)
    local choices = {}
    local function add(label, run)
      table.insert(choices, { label = label, run = run })
    end
    if panel.filter then
      add("Show all conversations", show_all)
    end
    if comment then
      local callbacks = panel.model.callbacks
      add("Reply", function()
        reply(comment)
      end)
      if comment.agent_status == "blocked" then
        add("Answer Pi's question", function()
          if panel.expanded then
            expand(panel)
          end
          threads.respond(panel.model.ctx.state_path, comment)
        end)
      end
      if comment.agent_request_id then
        if
          comment.agent_status == "pending"
          or comment.agent_status == "running"
          or comment.agent_status == "blocked"
        then
          add("Cancel Pi request", function()
            require("utils.diffview_review_agent").control(
              panel.model.ctx.state_path,
              comment.agent_request_id,
              { action = "cancel" }
            )
          end)
        else
          add("Retry Pi request", function()
            callbacks.retry(comment)
          end)
        end
      end
      for _, item in ipairs({ { "Resolve locally", "resolve" }, { "Delete or dismiss locally", "delete" } }) do
        add(item[1], function()
          callbacks[item[2]](comment)
          if not threads.find(panel.model.state, panel.selected) then
            panel.selected = nil
          end
          render(panel)
        end)
      end
    end
    if #choices > 0 then
      local keys, actions = {}, {}
      for index = 1, math.min(#choices, 9) do
        local action = "thread_action_" .. index
        keys[tostring(index)] = { action, mode = { "n", "i" } }
        actions[action] = function(picker)
          for row = 1, picker.list:count() do
            local item = picker.list:get(row)
            if item and item.idx == index then
              picker.list:move(row, true)
              picker:action("confirm")
              break
            end
          end
        end
      end
      vim.ui.select(choices, {
        prompt = "Thread actions",
        snacks = { actions = actions, win = { input = { keys = keys }, list = { keys = keys } } },
        format_item = function(item)
          return item.label
        end,
      }, function(choice)
        if choice and valid_window(panel) and panel.mode == "threads" then
          choice.run()
        end
      end)
    end
  end, "Thread actions")
end

local function update(panel, model)
  local callbacks = model.callbacks or panel.model.callbacks
  panel.model = vim.tbl_extend("force", panel.model, model)
  panel.model.guide, panel.model.callbacks = model.guide, callbacks
  render(panel)
end

function M.refresh(model)
  local panel = find(model.ctx)
  if panel then
    update(panel, model)
  end
end

function M.return_to_thread(ctx)
  local panel = find(ctx)
  local source = panel and panel.source_return
  if
    not (
      source
      and valid_window(panel)
      and panel.mode == "threads"
      and vim.api.nvim_get_current_win() == source.win
      and vim.api.nvim_get_current_buf() == source.buf
    )
  then
    return false
  end
  panel.source_return = nil
  vim.api.nvim_set_current_win(panel.winid)
  for row, id in pairs(panel.rows) do
    if id == source.id then
      vim.api.nvim_win_set_cursor(panel.winid, { row, 0 })
      break
    end
  end
  return true
end

function M.show_section_list(ctx)
  local panel = find(ctx)
  if panel and valid_window(panel) and panel.mode == "guide" then
    jump_to_heading(panel, "route")
  end
end

function M.open(model, opts)
  opts = opts or {}
  local panel = find(model.ctx)
  if opts.attention and #threads.list(model.state, "attention") == 0 then
    vim.notify("No review conversations need attention", vim.log.levels.INFO, { title = "Review" })
    return panel
  end
  if panel and vim.api.nvim_get_current_win() ~= panel.winid then
    panel.source_win = vim.api.nvim_get_current_win()
  end
  if not panel then
    local buffer = vim.api.nvim_create_buf(false, true)
    vim.api.nvim_buf_set_name(buffer, "review-panel://" .. buffer)
    vim.bo[buffer].bufhidden = "hide"
    vim.bo[buffer].filetype = "markdown"
    vim.b[buffer].diffview_review_panel = true
    panel = {
      buffer = buffer,
      model = model,
      views = {},
      mode = opts.mode or "guide",
      tabpage = vim.api.nvim_get_current_tabpage(),
      source_win = vim.api.nvim_get_current_win(),
    }
    panels[buffer] = panel
    maps(panel)
    vim.api.nvim_create_autocmd("BufWipeout", {
      buffer = buffer,
      callback = function()
        panels[buffer] = nil
      end,
    })
  else
    update(panel, model)
  end
  if not valid_window(panel) then
    panel.expanded = not opts.focused
    open_window(panel)
  else
    vim.api.nvim_set_current_win(panel.winid)
    if opts.focused and panel.expanded then
      expand(panel)
    end
  end
  if opts.mode then
    panel.mode = opts.mode
  end
  if panel.selected and not threads.find(panel.model.state, panel.selected) then
    panel.selected = nil
  end
  panel.filter = opts.filter
  if opts.filter then
    local selected = threads.find(panel.model.state, panel.selected)
    if not selected or not threads.matches(selected, opts.filter) then
      panel.selected = nil
    end
  end
  if opts.attention then
    next_thread(panel, 1, "attention")
  elseif opts.selected then
    select(panel, opts.selected, true)
  elseif opts.at_cursor then
    panel.selected = nil
    render(panel)
    jump_to_heading(panel, "panel")
  else
    show_selection(panel)
  end
  return panel
end

local group = vim.api.nvim_create_augroup("DiffviewReviewPanel", { clear = true })
vim.api.nvim_create_autocmd("VimResized", {
  group = group,
  callback = function()
    for _, panel in pairs(panels) do
      if panel.expanded and valid_window(panel) then
        vim.api.nvim_win_set_config(panel.winid, expanded_config())
      end
      if valid_window(panel) and panel.mode == "threads" then
        render(panel)
      end
    end
  end,
})
vim.api.nvim_create_autocmd("WinEnter", {
  group = group,
  callback = function()
    local win, tab = vim.api.nvim_get_current_win(), vim.api.nvim_get_current_tabpage()
    if vim.api.nvim_win_get_config(win).relative ~= "" or not vim.wo[win].diff then
      return
    end
    for _, panel in pairs(panels) do
      if panel.tabpage == tab and panel.expanded and valid_window(panel) then
        vim.schedule(function()
          if vim.api.nvim_get_current_win() == win and panel.expanded and valid_window(panel) then
            panel.source_win = win
            expand(panel)
          end
        end)
      end
    end
  end,
})
vim.api.nvim_create_autocmd("WinResized", {
  group = group,
  callback = function()
    for _, panel in pairs(panels) do
      if valid_window(panel) and panel.mode == "threads" and vim.tbl_contains(vim.v.event.windows, panel.winid) then
        render(panel)
      end
    end
  end,
})
vim.api.nvim_create_autocmd("TabClosed", {
  group = group,
  callback = function()
    vim.schedule(function()
      for buffer, panel in pairs(panels) do
        if not vim.api.nvim_tabpage_is_valid(panel.tabpage) then
          panels[buffer] = nil
          if vim.api.nvim_buf_is_valid(buffer) then
            vim.api.nvim_buf_delete(buffer, { force = true })
          end
        end
      end
    end)
  end,
})

return M
