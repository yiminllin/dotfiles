-- Focus the original revision buffers with folds and restore each section's reading position.
local M = {}
local chunks = require("utils.diffview_review_chunks")
local scope_view = require("utils.diffview_review_scope")
local OPTIONS = { "foldmethod", "foldenable", "foldlevel", "foldcolumn", "foldminlines", "foldtext" }
local capture

local function restore(win, record)
  if vim.api.nvim_win_is_valid(win) then
    vim.api.nvim_win_call(win, function()
      if vim.wo.foldmethod == "manual" then
        vim.cmd("normal! zE")
      end
      for _, name in ipairs(OPTIONS) do
        vim.wo[name] = record.options[name]
      end
    end)
  end
end

function M.leave(ctx)
  local workspace = ctx.view.review_chunks
  if not workspace then
    return
  end
  capture(ctx, workspace)
  for win, record in pairs(workspace.windows) do
    if vim.api.nvim_win_is_valid(win) and vim.api.nvim_win_get_buf(win) == record.buffer then
      restore(win, record)
    end
  end
  workspace.windows, workspace.active, workspace.hunk = {}, nil, nil
  local scope = ctx.view.review_scope
  if scope then
    scope.chunk_paths, scope.chunk_order, scope.order_key = nil, nil, nil
  end
  scope_view.apply_order(ctx.view, workspace.guide)
end

function M.visible(ctx, chunk)
  local scope, result, paths = ctx.view.review_scope, {}, {}
  if not scope or not scope.enabled then
    return chunk.hunks
  end
  local codeowners = require("utils.codeowners")
  for _, hunk in ipairs(chunk.hunks) do
    if paths[hunk.path] == nil then
      paths[hunk.path] = codeowners.owned_by(scope.rules, hunk.path, "@ZiplineTeam/phoenix-reviewers")
    end
    if paths[hunk.path] then
      table.insert(result, hunk)
    end
  end
  return result
end

local function restrict(ctx, workspace)
  local chunk = workspace.plan and workspace.plan.by_id[workspace.active]
  if not chunk then
    return
  end
  local paths, order = {}, {}
  for _, hunk in ipairs(M.visible(ctx, chunk)) do
    if not paths[hunk.path] then
      paths[hunk.path] = true
      table.insert(order, { path = hunk.path })
    end
  end
  local scope = ctx.view.review_scope
  if scope then
    scope.chunk_paths, scope.chunk_order, scope.order_key = paths, order, nil
    scope_view.apply_order(ctx.view, workspace.guide)
  end
end

function M.sync(ctx, guide, context)
  local view = ctx.view
  local base, head = view and view.left and view.left.commit, view and view.right and view.right.commit
  local workspace = view and view.review_chunks
  if
    workspace
    and (
      workspace.base ~= base
      or workspace.head ~= head
      or workspace.root ~= ctx.root
      or workspace.state_path ~= ctx.state_path
    )
  then
    M.leave(ctx)
    workspace.error, workspace.plan = "Review context changed; reopen review before using sections", nil
    return workspace
  end
  if not base or not head or (not context and not (guide and guide.chunks and #guide.chunks > 0)) then
    return workspace
  end
  if not workspace then
    local catalog, err = chunks.inventory(ctx.root, base, head, view.path_args)
    workspace = {
      catalog = catalog,
      error = err,
      windows = {},
      positions = {},
      base = base,
      head = head,
      root = ctx.root,
      state_path = ctx.state_path,
    }
    view.review_chunks = workspace
    if catalog and context and context.assistant_name and context.path then
      local path = vim.fs.joinpath(vim.fn.fnamemodify(context.path, ":h"), "review-hunks.json")
      local document = { context = catalog.context, hunks = catalog.hunks }
      vim.fn.mkdir(vim.fn.fnamemodify(path, ":h"), "p")
      local ok = pcall(vim.fn.writefile, { vim.json.encode(document) }, path .. ".tmp")
      if ok then
        vim.uv.fs_rename(path .. ".tmp", path)
      end
    end
  end
  workspace.visible = function(chunk)
    return M.visible(ctx, chunk)
  end
  if workspace.catalog and workspace.observed ~= guide then
    workspace.observed = guide
    local plan, err = chunks.plan(workspace.catalog, guide)
    workspace.error = err
    if plan then
      local old_hunk = workspace.hunk
      workspace.plan, workspace.guide = plan, guide
      if old_hunk then
        workspace.active = plan.owner[old_hunk]
      end
      if workspace.active and not plan.by_id[workspace.active] then
        workspace.active = nil
      end
      restrict(ctx, workspace)
    end
  end
  if workspace.active and #M.visible(ctx, workspace.plan.by_id[workspace.active]) == 0 then
    M.leave(ctx)
  end
  return workspace
end

local function source_windows(ctx, callback)
  local entry = ctx.view.cur_entry
  if not entry or not entry.layout or not entry.opened then
    return
  end
  for _, file in ipairs(entry.layout:files()) do
    if file.bufnr and vim.api.nvim_buf_is_valid(file.bufnr) then
      for _, win in ipairs(vim.api.nvim_tabpage_list_wins(ctx.view.tabpage)) do
        if vim.api.nvim_win_get_buf(win) == file.bufnr then
          callback(win, file, entry.path)
        end
      end
    end
  end
end

function M.apply(ctx)
  local workspace = ctx.view.review_chunks
  local chunk = workspace and workspace.plan and workspace.plan.by_id[workspace.active]
  if not chunk then
    return
  end
  local ids = {}
  for _, hunk in ipairs(chunk.hunks) do
    table.insert(ids, hunk.id)
  end
  table.sort(ids)
  local signature = table.concat(ids, ":")
  workspace.source_error = nil
  source_windows(ctx, function(win, file, path)
    local record = workspace.windows[win]
    local key = tostring(file.bufnr) .. signature
    if record and record.key == key and vim.wo[win].foldmethod == "manual" then
      return
    end
    if record then
      restore(win, record)
      workspace.windows[win] = nil
    end
    local side = file.symbol == "a" and "LEFT" or "RIGHT"
    local hidden, err = chunks.hidden_ranges(chunk.hunks, path, side, vim.api.nvim_buf_line_count(file.bufnr))
    if not hidden then
      workspace.source_error = err
      return
    end
    local options = {}
    for _, name in ipairs(OPTIONS) do
      options[name] = vim.wo[win][name]
    end
    workspace.windows[win] = { key = key, buffer = file.bufnr, options = options }
    vim.api.nvim_win_call(win, function()
      local position = vim.fn.winsaveview()
      vim.wo.foldmethod, vim.wo.foldenable, vim.wo.foldlevel = "manual", true, 0
      vim.wo.foldcolumn, vim.wo.foldminlines = "1", 0
      vim.wo.foldtext = "printf('… %d lines outside active section …', v:foldend-v:foldstart+1)"
      vim.cmd("normal! zE")
      for _, range in ipairs(hidden) do
        vim.cmd(range[1] .. "," .. range[2] .. "fold")
      end
      vim.fn.winrestview(position)
    end)
  end)
end

function M.can_read(ctx, hunk)
  local workspace = ctx.view.review_chunks
  local chunk = workspace and workspace.plan and workspace.plan.by_id[workspace.active]
  if not chunk or not hunk or workspace.source_error then
    return false
  end
  for _, visible in ipairs(M.visible(ctx, chunk)) do
    if visible.id == hunk.id then
      return true
    end
  end
  return false
end

function M.current(ctx)
  local workspace = ctx.view.review_chunks
  local chunk = workspace and workspace.plan and workspace.plan.by_id[workspace.active]
  if not chunk then
    return
  end
  local buffer, row = vim.api.nvim_get_current_buf(), vim.api.nvim_win_get_cursor(0)[1]
  local result
  source_windows(ctx, function(_, file, path)
    if file.bufnr ~= buffer then
      return
    end
    local side = file.symbol == "a" and "LEFT" or "RIGHT"
    for _, hunk in ipairs(chunk.hunks) do
      local first = side == "LEFT" and hunk.left_start or hunk.right_start
      local count = side == "LEFT" and hunk.left_count or hunk.right_count
      if
        hunk.path == path
        and (hunk.kind == "file" or (row >= math.max(1, first) and row <= math.max(1, first) + math.max(count, 1) - 1))
      then
        result = hunk
      end
    end
  end)
  return result
end

capture = function(ctx, workspace)
  if not workspace.active then
    return
  end
  local current = M.current(ctx)
  local saved = { hunk = current and current.id or workspace.hunk, views = {} }
  source_windows(ctx, function(win, file, path)
    saved.views[path .. ":" .. file.symbol] = vim.api.nvim_win_call(win, vim.fn.winsaveview)
  end)
  workspace.positions[workspace.active] = saved
end

function M.activate(ctx, id, hunk_id, state, source, opts)
  opts = opts or {}
  local workspace = ctx.view.review_chunks
  local chunk = workspace and workspace.plan and workspace.plan.by_id[id]
  if not chunk then
    return false, workspace and workspace.error or "Generate a section plan first"
  end
  local visible = M.visible(ctx, chunk)
  if #visible == 0 then
    return false, "This section has no hunks in the current ownership scope"
  end
  capture(ctx, workspace)
  local saved = workspace.positions[id]
  local wanted = hunk_id or (saved and saved.hunk)
  local hunk
  for _, item in ipairs(visible) do
    if item.id == wanted then
      hunk = item
    end
  end
  if hunk_id and not hunk then
    return false, "This hunk is outside the current section/scope"
  end
  if not hunk then
    for _, item in ipairs(visible) do
      if not (state.read_hunks or {})[item.id] then
        hunk = item
        break
      end
    end
  end
  hunk = hunk or visible[1]
  workspace.active, workspace.hunk = id, hunk.id
  restrict(ctx, workspace)
  local entries = {}
  for _, entry in ipairs(ctx.view.panel:ordered_file_list()) do
    table.insert(entries, { path = entry.path, entry = entry })
  end
  local target = source or chunks.jump_source(hunk, workspace.catalog)
  if not source then
    target.revision = target.side == "LEFT" and workspace.base or workspace.head
  end
  require("utils.diffview_review_navigation").open({
    root = ctx.root,
    view = ctx.view,
    base = workspace.base,
    head = workspace.head,
    entries = entries,
    before_open = function()
      M.apply(ctx)
    end,
    on_return = opts.on_return,
    on_open = function(win, buf)
      if opts.on_open then
        opts.on_open(win, buf)
      end
      if not hunk_id and saved and saved.hunk == hunk.id then
        source_windows(ctx, function(win, file, path)
          local position = saved.views[path .. ":" .. file.symbol]
          if position then
            vim.api.nvim_win_call(win, function()
              vim.fn.winrestview(position)
            end)
          end
        end)
      end
    end,
  }, target)
  return true
end

function M.next(ctx, direction, kind)
  local workspace = ctx.view.review_chunks
  if not (workspace and workspace.plan) then
    return nil
  end
  local route = {}
  for _, chunk in ipairs(workspace.plan.chunks) do
    local visible = M.visible(ctx, chunk)
    if kind == "chunk" then
      if #visible > 0 then
        table.insert(route, { chunk_id = chunk.id })
      end
    elseif chunk.id == workspace.active then
      for _, hunk in ipairs(visible) do
        table.insert(route, { chunk_id = chunk.id, hunk_id = hunk.id })
      end
    end
  end
  local current = M.current(ctx)
  local current_id = current and current.id or workspace.hunk
  local start = direction > 0 and 0 or #route + 1
  for index, item in ipairs(route) do
    if kind == "chunk" and item.chunk_id == workspace.active or kind ~= "chunk" and item.hunk_id == current_id then
      start = index
      break
    end
  end
  if #route > 0 then
    return route[(start - 1 + direction) % #route + 1]
  end
end

return M
