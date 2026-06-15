local M = {}

local review_format = require("utils.diffview_review_format")
local review_state = require("utils.diffview_review_state")

local NS = vim.api.nvim_create_namespace("diffview_review")
local SIGN_GROUP = "diffview_review"
local COMMENT_MARKER = review_format.COMMENT_MARKER
local last_unviewed_path = nil

local function notify(message, level)
	vim.notify(message, level or vim.log.levels.INFO, { title = "Diffview Review" })
end

local function starts_with(value, prefix)
	return value:sub(1, #prefix) == prefix
end

local function join_path(...)
	local result = nil
	for _, part in ipairs({ ... }) do
		if part and part ~= "" then
			part = tostring(part)
			if result then
				result = result:gsub("/+$", "") .. "/" .. part:gsub("^/+", "")
			else
				result = part
			end
		end
	end
	return result or ""
end

local function is_absolute_path(path)
	return path:sub(1, 1) == "/" or path:match("^%a:[/\\]") ~= nil
end

local function normalize_dir(path)
	if not path or path == "" then
		return nil
	end

	path = vim.fn.fnamemodify(path, ":p")
	if path ~= "/" then
		path = path:gsub("/+$", "")
	end
	return path
end

local function normalize_file(path)
	if not path or path == "" then
		return nil
	end

	return path:gsub("\\", "/"):gsub("^%./", "")
end

local function current_view()
	local ok, lib = pcall(require, "diffview.lib")
	if not ok then
		return nil
	end

	local view_ok, view = pcall(lib.get_current_view)
	if view_ok then
		return view
	end
end

local function git_context_from_command(cwd)
	cwd = cwd or vim.fn.getcwd()
	local output = vim.fn.systemlist({ "git", "-C", cwd, "rev-parse", "--show-toplevel", "--git-dir" })
	if vim.v.shell_error ~= 0 or #output < 2 then
		return nil, nil
	end

	local root = normalize_dir(output[1])
	local gitdir = output[2]
	if root and gitdir and not is_absolute_path(gitdir) then
		gitdir = join_path(root, gitdir)
	end

	return root, normalize_dir(gitdir)
end

local function repo_context(view)
	local root = nil
	local gitdir = nil

	if view and view.adapter and view.adapter.ctx then
		root = normalize_dir(view.adapter.ctx.toplevel)
		gitdir = view.adapter.ctx.dir
		if root and gitdir and not is_absolute_path(gitdir) then
			gitdir = join_path(root, gitdir)
		end
		gitdir = normalize_dir(gitdir)
	end

	if not root or not gitdir then
		local git_root, command_gitdir = git_context_from_command(root or vim.fn.getcwd())
		root = root or git_root
		gitdir = gitdir or command_gitdir
	end

	if not root or not gitdir or vim.fn.isdirectory(gitdir) ~= 1 then
		return nil
	end

	return {
		root = root,
		gitdir = gitdir,
		state_path = join_path(root, "diffview-review.json"),
	}
end

local function file_from_panel(view)
	if not view or not view.panel then
		return nil, nil
	end

	local focused_ok, focused = pcall(function()
		return view.panel:is_focused()
	end)
	if not focused_ok or not focused then
		return nil, nil
	end

	local item_ok, item = pcall(function()
		return view.panel:get_item_at_cursor()
	end)
	if item_ok and type(item) == "table" and item.path and item.layout then
		return normalize_file(item.path), item
	end

	return nil, nil
end

local function file_from_buffer_name(bufnr, ctx)
	local name = vim.api.nvim_buf_get_name(bufnr)
	if name == "" then
		return nil
	end

	if ctx.root then
		local root_prefix = ctx.root:gsub("/+$", "") .. "/"
		if starts_with(name, root_prefix) then
			return normalize_file(name:sub(#root_prefix + 1))
		end
	end

	if ctx.gitdir then
		local diffview_prefix = "diffview://" .. ctx.gitdir:gsub("/+$", "") .. "/"
		if starts_with(name, diffview_prefix) then
			local rest = name:sub(#diffview_prefix + 1)
			local path = rest:match("^[^/]+/(.+)$")
			return normalize_file(path)
		end
	end

	return nil
end

local function entry_layout_files(entry)
	if not entry or not entry.layout then
		return {}
	end

	local files_ok, files = pcall(function()
		return entry.layout:files()
	end)
	if not files_ok or type(files) ~= "table" then
		return {}
	end
	return files
end

local function entry_file_for_buffer(entry, bufnr)
	for _, file in ipairs(entry_layout_files(entry)) do
		if file.bufnr == bufnr then
			return file
		end
	end
end

local function file_from_entry_buffer(entry, bufnr)
	local file = entry_file_for_buffer(entry, bufnr)
	if file then
		return normalize_file(file.path or entry.path)
	end
end

local function is_file_panel_buffer(bufnr)
	local filetype = vim.bo[bufnr].filetype
	return filetype == "DiffviewFiles" or filetype == "DiffviewFileHistory"
end

local function file_for_buffer(bufnr, ctx, view)
	if is_file_panel_buffer(bufnr) then
		return nil
	end

	local from_entry = file_from_entry_buffer(view and view.cur_entry, bufnr)
	if from_entry then
		return from_entry
	end

	return file_from_buffer_name(bufnr, ctx)
end

local function entry_main_bufnr(entry)
	if not (entry and entry.layout and entry.layout.get_main_win) then
		return nil
	end

	local ok, win = pcall(function()
		return entry.layout:get_main_win()
	end)
	if ok and type(win) == "table" and win.file then
		return win.file.bufnr
	end
end

local function review_comment_bufnr(visible, view)
	local entry = view and view.cur_entry or nil
	local entry_path = normalize_file(entry and entry.path)
	if not entry_path then
		return nil
	end

	local current_win = vim.api.nvim_get_current_win()
	local main_bufnr = entry_main_bufnr(entry)
	local current_candidate = nil
	local main_candidate = nil
	local preferred_candidate = nil
	local fallback_candidate = nil

	for _, item in ipairs(visible) do
		if item.file == entry_path then
			fallback_candidate = item
			if item.winid == current_win then
				current_candidate = item
			end
			if main_bufnr and item.bufnr == main_bufnr then
				main_candidate = item
			end

			local entry_file = entry_file_for_buffer(entry, item.bufnr)
			if entry_file and entry_file.symbol ~= "a" then
				preferred_candidate = item
			end
		end
	end

	if current_candidate then
		local current_entry_file = entry_file_for_buffer(entry, current_candidate.bufnr)
		if not current_entry_file or current_entry_file.symbol ~= "a" then
			return current_candidate.bufnr
		end
	end
	if main_candidate then
		return main_candidate.bufnr
	end
	return (preferred_candidate or current_candidate or fallback_candidate or {}).bufnr
end

local function current_file_context()
	local view = current_view()
	local ctx = repo_context(view)
	if not ctx then
		return { view = view }
	end

	ctx.view = view

	local panel_file, panel_entry = file_from_panel(view)
	if panel_file then
		ctx.file = panel_file
		ctx.entry = panel_entry
		return ctx
	end

	if view and view.cur_entry and view.cur_entry.path then
		ctx.file = normalize_file(view.cur_entry.path)
		ctx.entry = view.cur_entry
		return ctx
	end

	ctx.file = file_from_buffer_name(0, ctx)
	return ctx
end

local function require_active_diffview(ctx, action)
	if ctx and ctx.view then
		return true
	end

	notify("Open Diffview before " .. action, vim.log.levels.WARN)
	return false
end

local function require_repo_context(ctx, action)
	if ctx and ctx.state_path then
		return true
	end

	notify("Open Diffview in a git repo before " .. action, vim.log.levels.WARN)
	return false
end

local function load_state(ctx)
	return review_state.load(ctx, notify)
end

local function save_state(ctx, state)
	return review_state.save(ctx, state, notify)
end

local normalize_comment_text = review_format.normalize_comment_text
local boxed_comment_lines = review_format.boxed_comment_lines
local comment_preview = review_format.comment_preview
local line_range_label = review_format.line_range_label
local range_label = review_format.range_label
local split_comment_text = review_format.split_comment_text

local function clamp_comment_range(comment, line_count)
	local start_line = tonumber(comment.line)
	if not start_line then
		return nil, nil
	end

	local end_line = tonumber(comment.end_line) or start_line
	start_line, end_line = math.min(start_line, end_line), math.max(start_line, end_line)
	start_line = math.min(math.max(start_line, 1), line_count)
	end_line = math.min(math.max(end_line, 1), line_count)
	return start_line, end_line
end

local function sorted_file_comments(state, file, line_count)
	local comments = {}
	for index, comment in ipairs(state.comments or {}) do
		if comment.file == file then
			local start_line, end_line = clamp_comment_range(comment, line_count)
			if start_line then
				table.insert(comments, {
					comment = comment,
					end_line = end_line,
					index = index,
					start_line = start_line,
				})
			end
		end
	end

	table.sort(comments, function(left, right)
		if left.start_line ~= right.start_line then
			return left.start_line < right.start_line
		end
		if left.end_line ~= right.end_line then
			return left.end_line < right.end_line
		end
		local left_created = tostring(left.comment.created_at or "")
		local right_created = tostring(right.comment.created_at or "")
		if left_created ~= right_created then
			return left_created < right_created
		end
		local left_body = normalize_comment_text(left.comment.body)
		local right_body = normalize_comment_text(right.comment.body)
		if left_body ~= right_body then
			return left_body < right_body
		end
		return left.index < right.index
	end)
	return comments
end


local function find_comment(state, file, line)
	for index, comment in ipairs(state.comments) do
		local start_line = tonumber(comment.line)
		local end_line = tonumber(comment.end_line) or start_line
		if comment.file == file and start_line and start_line <= tonumber(line) and tonumber(line) <= end_line then
			return comment, index
		end
	end

	return nil, nil
end

local function line_from_opts(opts)
	if opts and opts.line then
		return tonumber(opts.line)
	end
	if opts and opts.line1 and tonumber(opts.line1) and tonumber(opts.line1) > 0 then
		return tonumber(opts.line1)
	end
	return vim.api.nvim_win_get_cursor(0)[1]
end

local function range_from_opts(opts)
	local start_line = line_from_opts(opts)
	local end_line = opts and tonumber(opts.end_line) or nil
	if not end_line and opts and opts.line1 and opts.line2 and opts.line1 ~= opts.line2 then
		end_line = tonumber(opts.line2)
	end
	end_line = end_line or start_line
	return math.min(start_line, end_line), math.max(start_line, end_line)
end

local function entry_path(entry)
	if type(entry) ~= "table" or not entry.path then
		return nil
	end
	return normalize_file(entry.path)
end

local function ordered_file_list(view)
	if not view or not view.panel then
		return {}
	end

	local ok, entries = pcall(function()
		return view.panel:ordered_file_list()
	end)
	if not ok or type(entries) ~= "table" then
		return {}
	end
	return entries
end

local function review_entries(view, state)
	local entries = {}
	for _, entry in ipairs(ordered_file_list(view)) do
		local path = entry_path(entry)
		if path then
			table.insert(entries, {
				entry = entry,
				path = path,
				viewed = state.viewed[path] == true,
			})
		end
	end
	return entries
end

local function comments_for_file(state, file)
	local comments = {}
	for index, comment in ipairs(state.comments or {}) do
		if comment.file == file then
			table.insert(comments, {
				comment = comment,
				end_line = tonumber(comment.end_line) or tonumber(comment.line) or 1,
				index = index,
				start_line = tonumber(comment.line) or 1,
			})
		end
	end
	table.sort(comments, function(left, right)
		if left.start_line ~= right.start_line then
			return left.start_line < right.start_line
		end
		if left.end_line ~= right.end_line then
			return left.end_line < right.end_line
		end
		return left.index < right.index
	end)
	return comments
end

local function jump_to_entry(view, item, line)
	local ok = pcall(function()
		if view.set_file then
			view:set_file(item.entry, true, true)
		else
			view:use_entry(item.entry)
		end
	end)
	if not ok then
		notify("Could not open " .. item.path, vim.log.levels.WARN)
		return
	end
	vim.defer_fn(function()
		if line then
			pcall(vim.api.nvim_win_set_cursor, 0, { math.max(1, tonumber(line) or 1), 0 })
		end
		M.refresh_visible()
	end, 60)
end

local function review_status(file, state)
	if state.viewed[file] then
		return {
			panel_hl = "DiffviewReviewPanelViewed",
			panel_text = "  ✓ reviewed",
			viewed = true,
			winbar_hl = "DiffviewReviewWinbarViewed",
			winbar_text = " ✓ Reviewed ",
		}
	end

	return {
		panel_hl = "DiffviewReviewPanelUnviewed",
		panel_text = "  ○ not reviewed",
		viewed = false,
		winbar_hl = "DiffviewReviewWinbarUnviewed",
		winbar_text = " ○ Not reviewed ",
	}
end

local function basename(path)
	return tostring(path or ""):match("([^/]+)$") or tostring(path or "")
end

local function refresh_buffer(bufnr, file, state, show_comments)
	bufnr = bufnr == 0 and vim.api.nvim_get_current_buf() or bufnr
	if not file or not vim.api.nvim_buf_is_valid(bufnr) then
		return
	end

	vim.api.nvim_buf_clear_namespace(bufnr, NS, 0, -1)
	vim.fn.sign_unplace(SIGN_GROUP, { buffer = bufnr })

	local line_count = vim.api.nvim_buf_line_count(bufnr)
	if line_count == 0 then
		return
	end

	if show_comments == false then
		return
	end

	local comment_boxes = {}
	for _, entry in ipairs(sorted_file_comments(state, file, line_count)) do
		for lnum = entry.start_line, entry.end_line do
			vim.fn.sign_place(0, SIGN_GROUP, "DiffviewReviewComment", bufnr, { lnum = lnum, priority = 30 })
			vim.api.nvim_buf_set_extmark(bufnr, NS, lnum - 1, 0, {
				virt_text = { { COMMENT_MARKER, "DiffviewReviewCommentRange" } },
				virt_text_pos = "right_align",
				priority = 35,
			})
		end

		local display_line = entry.start_line
		comment_boxes[display_line] = comment_boxes[display_line] or {}
		for _, line in ipairs(boxed_comment_lines(entry.comment, entry.start_line, entry.end_line)) do
			table.insert(comment_boxes[display_line], line)
		end
	end

	local display_lines = vim.tbl_keys(comment_boxes)
	table.sort(display_lines)
	for _, display_line in ipairs(display_lines) do
		vim.api.nvim_buf_set_extmark(bufnr, NS, display_line - 1, 0, {
			virt_lines = comment_boxes[display_line],
			virt_lines_above = true,
			priority = 30,
		})
	end

end

local function refresh_winbar(winid, file, state)
	local escaped_file = file:gsub("%%", "%%%%")
	local status = review_status(file, state)
	vim.wo[winid].winbar = "%#"
		.. status.winbar_hl
		.. "#"
		.. status.winbar_text
		.. "%#DiffviewReviewWinbarFile# · "
		.. escaped_file
end

local function refresh_file_panel(bufnr, view, state)
	if not vim.api.nvim_buf_is_valid(bufnr) then
		return
	end

	vim.api.nvim_buf_clear_namespace(bufnr, NS, 0, -1)

	local lines_ok, lines = pcall(vim.api.nvim_buf_get_lines, bufnr, 0, -1, false)
	if not lines_ok or type(lines) ~= "table" then
		return
	end

	local entries = review_entries(view, state)
	local basename_counts = {}
	for _, item in ipairs(entries) do
		local name = basename(item.path)
		basename_counts[name] = (basename_counts[name] or 0) + 1
	end

	local used_lines = {}
	local function matching_lines(needle)
		local matches = {}
		for lnum, line in ipairs(lines) do
			if not used_lines[lnum] and line:find(needle, 1, true) then
				table.insert(matches, lnum)
			end
		end
		return matches
	end

	for _, item in ipairs(entries) do
		local matches = matching_lines(item.path)
		if #matches == 0 and basename_counts[basename(item.path)] == 1 then
			matches = matching_lines(basename(item.path))
		end

		if #matches == 1 then
			local lnum = matches[1]
			used_lines[lnum] = true
			local status = review_status(item.path, state)
			pcall(vim.api.nvim_buf_set_extmark, bufnr, NS, lnum - 1, 0, {
				virt_text = { { status.panel_text, status.panel_hl } },
				virt_text_pos = "eol",
				priority = 45,
			})
		end
	end
end


local function open_comment_editor(ctx, line, end_line, initial, on_save)
	local height = math.min(8, math.max(5, math.floor(vim.o.lines * 0.18)))
	local title = (" Review comment %s:%s "):format(ctx.file, range_label(line, end_line))
	local source_win = vim.api.nvim_get_current_win()
	local source_cursor = vim.api.nvim_win_get_cursor(source_win)
	local bufnr = vim.api.nvim_create_buf(false, true)

	vim.api.nvim_buf_set_lines(bufnr, 0, -1, false, split_comment_text(initial))
	pcall(vim.api.nvim_buf_set_name, bufnr, "diffview-review-comment")
	vim.bo[bufnr].bufhidden = "wipe"
	vim.bo[bufnr].buftype = "acwrite"
	vim.bo[bufnr].filetype = "markdown"
	vim.bo[bufnr].swapfile = false

	vim.cmd(("botright %dsplit"):format(height))
	local winid = vim.api.nvim_get_current_win()
	vim.api.nvim_win_set_buf(winid, bufnr)
	vim.wo[winid].wrap = true
	vim.wo[winid].cursorline = true
	vim.wo[winid].number = false
	vim.wo[winid].relativenumber = false
	vim.wo[winid].signcolumn = "no"
	vim.wo[winid].winbar = title .. "  (:w save, :wq save+close, :q close)"
	vim.wo[winid].winhl = "Normal:DiffviewNormal,NormalNC:DiffviewNormal,EndOfBuffer:EndOfBuffer,SignColumn:SignColumn"

	local closed = false
	local function restore_source()
		if vim.api.nvim_win_is_valid(source_win) then
			vim.api.nvim_set_current_win(source_win)
			pcall(vim.api.nvim_win_set_cursor, source_win, source_cursor)
		end
	end

	local function close()
		if closed then
			return
		end
		closed = true
		if vim.api.nvim_win_is_valid(winid) then
			vim.api.nvim_win_close(winid, true)
		end
		restore_source()
	end

	local function save(close_after)
		if not vim.api.nvim_buf_is_valid(bufnr) then
			return
		end
		local lines = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
		vim.bo[bufnr].modified = false
		on_save(table.concat(lines, "\n"))
		if close_after then
			close()
		end
	end

	vim.api.nvim_create_autocmd("BufWriteCmd", {
		buffer = bufnr,
		callback = function()
			save(false)
		end,
	})
	vim.api.nvim_create_autocmd({ "TextChanged", "TextChangedI" }, {
		buffer = bufnr,
		callback = function()
			vim.bo[bufnr].modified = false
		end,
	})
	vim.api.nvim_create_autocmd("WinClosed", {
		pattern = tostring(winid),
		callback = function()
			vim.schedule(restore_source)
		end,
	})
	vim.bo[bufnr].modified = false
	vim.cmd.startinsert()
end

function M.apply_highlights()
	local set = vim.api.nvim_set_hl

	-- GitHub light UI surface colors. These override the Solarized
	-- colorscheme while Diffview is open so unchanged diff areas look
	-- closer to github.com instead of Solarized's cream background.
	set(0, "Normal", { bg = "#ffffff", fg = "#24292f" })
	set(0, "NormalNC", { bg = "#ffffff", fg = "#24292f" })
	set(0, "SignColumn", { bg = "#ffffff" })
	set(0, "FoldColumn", { bg = "#ffffff" })
	set(0, "LineNr", { bg = "#ffffff", fg = "#6e7781" })
	set(0, "CursorLine", { bg = "#f6f8fa" })
	set(0, "CursorLineNr", { bg = "#f6f8fa", fg = "#24292f", bold = true })
	set(0, "EndOfBuffer", { bg = "#ffffff", fg = "#ffffff" })
	set(0, "WinSeparator", { bg = "#ffffff", fg = "#d0d7de" })
	set(0, "StatusLine", { bg = "#f6f8fa", fg = "#24292f" })
	set(0, "StatusLineNC", { bg = "#f6f8fa", fg = "#57606a" })
	set(0, "VertSplit", { bg = "#ffffff", fg = "#d0d7de" })
	set(0, "DiffviewNormal", { bg = "#ffffff", fg = "#24292f" })
	set(0, "DiffviewCursorLine", { bg = "#f6f8fa" })
	set(0, "DiffviewStatusLine", { bg = "#f6f8fa", fg = "#24292f" })
	set(0, "DiffviewStatusLineNC", { bg = "#f6f8fa", fg = "#57606a" })

	set(0, "DiffAdd", { bg = "#dafbe1" })
	set(0, "DiffChange", { bg = "#ddf4ff" })
	set(0, "DiffText", { bg = "#aceebb", fg = "#24292f", bold = true })
	set(0, "DiffDelete", { bg = "#ffebe9" })
	set(0, "DiffviewDiffAdd", { bg = "#dafbe1" })
	set(0, "DiffviewDiffAddAsDelete", { bg = "#ffebe9" })
	set(0, "DiffviewDiffChange", { bg = "#ddf4ff" })
	set(0, "DiffviewDiffDelete", { bg = "#ffebe9" })
	set(0, "DiffviewDiffDeleteDim", { bg = "#ffffff", fg = "#d0d7de" })
	set(0, "DiffviewDiffFiller", { bg = "#ffffff", fg = "#d0d7de" })
	set(0, "DiffviewDiffText", { bg = "#aceebb", fg = "#24292f", bold = true })
	set(0, "DiffviewLeftDiffText", { bg = "#ffcecb", fg = "#24292f", bold = true })
	set(0, "DiffviewRightDiffText", { bg = "#aceebb", fg = "#24292f", bold = true })
	set(0, "DiffviewFilePanelInsertions", { fg = "#1a7f37", bold = true })
	set(0, "DiffviewFilePanelDeletions", { fg = "#cf222e", bold = true })
	set(0, "DiffviewFilePanelTitle", { fg = "#0969da", bold = true })
	set(0, "DiffviewFolderSign", { fg = "#0969da" })
	set(0, "DiffviewNonText", { fg = "#57606a" })
	set(0, "DiffviewReviewCommentSign", { fg = "#0969da", bold = true })
	set(0, "DiffviewReviewCommentBorder", { fg = "#0969da" })
	set(0, "DiffviewReviewCommentRange", { bg = "#ddf4ff", fg = "#0969da", bold = true })
	set(0, "DiffviewReviewCommentVirt", { fg = "#0969da" })
	set(0, "DiffviewReviewPanelUnviewed", { fg = "#9a6700", bold = true })
	set(0, "DiffviewReviewPanelViewed", { fg = "#6e7781" })
	set(0, "DiffviewReviewStatusComment", { bg = "#ddf4ff", fg = "#0969da" })
	set(0, "DiffviewReviewStatusUnviewed", { bg = "#fff8c5", fg = "#9a6700", bold = true })
	set(0, "DiffviewReviewStatusViewed", { bg = "#f6f8fa", fg = "#1a7f37" })
	set(0, "DiffviewReviewWinbarFile", { bg = "#f6f8fa", fg = "#57606a" })
	set(0, "DiffviewReviewWinbarUnviewed", { bg = "#fff8c5", fg = "#9a6700", bold = true })
	set(0, "DiffviewReviewWinbarViewed", { bg = "#f6f8fa", fg = "#1a7f37" })
end

function M.refresh_visible()
	local view = current_view()
	local ctx = repo_context(view)
	if not ctx then
		return
	end

	local state = load_state(ctx)

	local visible = {}
	for _, winid in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
		local bufnr = vim.api.nvim_win_get_buf(winid)
		if is_file_panel_buffer(bufnr) then
			refresh_file_panel(bufnr, view, state)
		else
			local file = file_for_buffer(bufnr, ctx, view)
			if file then
				table.insert(visible, { bufnr = bufnr, file = file, winid = winid })
			end
		end
	end

	local comment_bufnr = review_comment_bufnr(visible, view)
	for _, item in ipairs(visible) do
		refresh_buffer(item.bufnr, item.file, state, item.bufnr == comment_bufnr)
		refresh_winbar(item.winid, item.file, state)
	end
end

function M.refresh_current()
	local ctx = current_file_context()
	if not ctx.state_path then
		return
	end
	if not ctx.file then
		return
	end

	local state = load_state(ctx)
	refresh_buffer(0, ctx.file, state, true)
	refresh_winbar(0, ctx.file, state)
end

function M.add_comment(opts)
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "adding a review comment") then
		return
	end
	if not require_repo_context(ctx, "adding a review comment") then
		return
	end
	if not ctx.file then
		notify("Open a Diffview file before adding a review comment", vim.log.levels.WARN)
		return
	end

	local line, end_line = range_from_opts(opts)
	local state = load_state(ctx)
	local existing = find_comment(state, ctx.file, line)
	local provided = opts and opts.args and opts.args ~= "" and opts.args or nil

	local function save_comment(input)
		if not input then
			return
		end
		input = vim.trim(input)
		if input == "" then
			notify("Empty review comment skipped", vim.log.levels.WARN)
			return
		end

		if existing then
			existing.body = input
			existing.updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
		else
			local comment = {
				file = ctx.file,
				line = line,
				body = input,
				created_at = os.date("!%Y-%m-%dT%H:%M:%SZ"),
			}
			if end_line ~= line then
				comment.end_line = end_line
			end
			table.insert(state.comments, comment)
		end

		if save_state(ctx, state) then
			notify(("Saved review comment for %s:%s"):format(ctx.file, range_label(line, end_line)))
			M.refresh_visible()
		end
	end

	if provided then
		save_comment(provided)
		return
	end

	open_comment_editor(ctx, line, end_line, existing and existing.body or "", save_comment)
end

function M.add_comment_visual()
	local start_line = vim.fn.line("v")
	local end_line = vim.fn.line(".")
	M.add_comment({ line = math.min(start_line, end_line), end_line = math.max(start_line, end_line) })
end

function M.delete_comment(opts)
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "deleting a review comment") then
		return
	end
	if not require_repo_context(ctx, "deleting a review comment") then
		return
	end
	if not ctx.file then
		notify("Open a Diffview file before deleting a review comment", vim.log.levels.WARN)
		return
	end

	local line = line_from_opts(opts)
	local state = load_state(ctx)
	local _, index = find_comment(state, ctx.file, line)
	if not index then
		notify(("No review comment at %s:%d"):format(ctx.file, line), vim.log.levels.WARN)
		return
	end

	table.remove(state.comments, index)
	if save_state(ctx, state) then
		notify(("Deleted review comment at %s:%d"):format(ctx.file, line))
		M.refresh_visible()
	end
end

function M.toggle_file_viewed()
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "toggling reviewed state") then
		return
	end
	if not require_repo_context(ctx, "toggling reviewed state") then
		return
	end
	if not ctx.file then
		notify("Open a Diffview file before toggling reviewed state", vim.log.levels.WARN)
		return
	end

	local state = load_state(ctx)
	state.viewed[ctx.file] = not state.viewed[ctx.file] or nil
	last_unviewed_path = nil

	if save_state(ctx, state) then
		local status = state.viewed[ctx.file] and "reviewed" or "unreviewed"
		notify(("Marked %s as %s"):format(ctx.file, status))
		M.refresh_visible()
	end
end

local function comment_targets(view, state)
	local targets = {}
	for _, item in ipairs(review_entries(view, state)) do
		for _, comment in ipairs(comments_for_file(state, item.path)) do
			table.insert(targets, {
				item = item,
				line = comment.start_line,
			})
		end
	end
	return targets
end

local function current_comment_target_index(targets, file, line)
	local fallback = nil
	for index, target in ipairs(targets) do
		if target.item.path == file then
			if not fallback then
				fallback = index
			end
			if target.line >= line then
				return index
			end
		end
	end
	return fallback
end

function M.next_review_comment(direction)
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "jumping to review comment") or not require_repo_context(ctx, "jumping to review comment") then
		return
	end

	local state = load_state(ctx)
	local targets = comment_targets(ctx.view, state)
	if #targets == 0 then
		notify("No local Diffview review comments")
		return
	end

	direction = direction == -1 and -1 or 1
	local cursor_line = vim.api.nvim_win_get_cursor(0)[1]
	local current_index = current_comment_target_index(targets, ctx.file, cursor_line)
	local target_index
	if current_index then
		target_index = ((current_index - 1 + direction) % #targets) + 1
	else
		target_index = direction == -1 and #targets or 1
	end

	local target = targets[target_index]
	jump_to_entry(ctx.view, target.item, target.line)
end

function M.next_unviewed_file()
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "jumping to next unreviewed file") or not require_repo_context(ctx, "jumping to next unreviewed file") then
		return
	end

	local state = load_state(ctx)
	local entries = review_entries(ctx.view, state)
	local unviewed = {}
	local current_index = nil
	local last_index = nil
	for index, item in ipairs(entries) do
		if item.path == ctx.file then
			current_index = index
		end
		if item.path == last_unviewed_path then
			last_index = index
		end
		if not item.viewed then
			table.insert(unviewed, { item = item, index = index })
		end
	end

	if #unviewed == 0 then
		last_unviewed_path = nil
		notify("No unreviewed Diffview files")
		return
	end

	local start_index = last_index or current_index or 0
	local target = unviewed[1]
	for _, candidate in ipairs(unviewed) do
		if candidate.index > start_index then
			target = candidate
			break
		end
	end

	last_unviewed_path = target.item.path
	jump_to_entry(ctx.view, target.item)
end

function M.show_status()
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "showing review status") or not require_repo_context(ctx, "showing review status") then
		return
	end

	local state = load_state(ctx)
	local entries = review_entries(ctx.view, state)
	local lines = {}
	local line_to_action = {}
	local line_hls = {}

	for _, item in ipairs(entries) do
		local marker = item.viewed and "✓" or "○"
		table.insert(lines, ("%s %s"):format(marker, item.path))
		line_to_action[#lines] = { item = item, type = "file" }
		line_hls[#lines] = item.viewed and "DiffviewReviewStatusViewed" or "DiffviewReviewStatusUnviewed"

		for _, comment in ipairs(comments_for_file(state, item.path)) do
			local label = line_range_label(comment.start_line, comment.end_line)
			table.insert(lines, ("  " .. COMMENT_MARKER .. " %s: %s"):format(label, comment_preview(comment.comment)))
			line_to_action[#lines] = { item = item, line = comment.start_line, type = "comment" }
			line_hls[#lines] = "DiffviewReviewStatusComment"
		end
	end
	if #entries == 0 then
		table.insert(lines, "No files in current Diffview")
	end

	local width = math.max(40, math.floor(vim.o.columns * 0.58))
	width = math.min(width, math.max(40, vim.o.columns - 4))
	local height = math.max(10, math.floor(vim.o.lines * 0.82))
	height = math.min(height, math.max(10, #lines))
	local bufnr = vim.api.nvim_create_buf(false, true)
	vim.api.nvim_buf_set_lines(bufnr, 0, -1, false, lines)
	vim.bo[bufnr].bufhidden = "wipe"
	vim.bo[bufnr].filetype = "markdown"
	vim.bo[bufnr].modifiable = false
	for lnum, hl in pairs(line_hls) do
		pcall(vim.api.nvim_buf_set_extmark, bufnr, NS, lnum - 1, 0, { line_hl_group = hl })
	end

	local winid = vim.api.nvim_open_win(bufnr, true, {
		border = "rounded",
		col = math.max(math.floor((vim.o.columns - width) / 2), 0),
		height = height,
		relative = "editor",
		row = math.max(math.floor((vim.o.lines - height) / 2), 0),
		style = "minimal",
		title = " Diffview Review ",
		title_pos = "center",
		width = width,
	})
	vim.wo[winid].cursorline = true

	local function close_popup()
		if vim.api.nvim_win_is_valid(winid) then
			vim.api.nvim_win_close(winid, true)
		end
	end

	vim.keymap.set("n", "q", close_popup, { buffer = bufnr, nowait = true, silent = true })
	vim.keymap.set("n", "<CR>", function()
		local action = line_to_action[vim.api.nvim_win_get_cursor(winid)[1]]
		if not action then
			return
		end
		close_popup()
		jump_to_entry(ctx.view, action.item, action.line)
	end, { buffer = bufnr, nowait = true, silent = true })
end

local function apply_buffer_keymaps(bufnr)
	if not vim.api.nvim_buf_is_valid(bufnr) then
		return
	end
	vim.keymap.set("n", "<Tab>", M.next_unviewed_file, {
		buffer = bufnr,
		desc = "Next unreviewed Diffview file",
		nowait = true,
		silent = true,
	})
end

function M.diffview_keymaps()
	-- Diffview local-review keymap contract:
	-- <leader>gda/gdd edit local comments, <leader>gdv toggles reviewed,
	-- <leader>gds opens the minimal status popup, <leader>gd[/] jump comments,
	-- and <Tab> advances only through unreviewed files.
	return {
		view = {
			{ "n", "<leader>gda", M.add_comment, { desc = "[G]it [D]iffview [A]dd Review Comment" } },
			{ "x", "<leader>gda", M.add_comment_visual, { desc = "[G]it [D]iffview [A]dd Review Comment" } },
			{ "n", "<leader>gdd", M.delete_comment, { desc = "[G]it [D]iffview [D]elete Review Comment" } },
			{ "n", "<leader>gdv", M.toggle_file_viewed, { desc = "[G]it [D]iffview Toggle File Reviewed" } },
			{ "n", "<leader>gds", M.show_status, { desc = "[G]it [D]iffview Review [S]tatus" } },
			{ "n", "<leader>gd]", function() M.next_review_comment(1) end, { desc = "Next Diffview review comment" } },
			{ "n", "<leader>gd[", function() M.next_review_comment(-1) end, { desc = "Previous Diffview review comment" } },
			{ "n", "<Tab>", M.next_unviewed_file, { desc = "Next unreviewed Diffview file" } },
		},
		file_panel = {
			{ "n", "<leader>gdv", M.toggle_file_viewed, { desc = "[G]it [D]iffview Toggle File Reviewed" } },
			{ "n", "<leader>gds", M.show_status, { desc = "[G]it [D]iffview Review [S]tatus" } },
			{ "n", "<leader>gd]", function() M.next_review_comment(1) end, { desc = "Next Diffview review comment" } },
			{ "n", "<leader>gd[", function() M.next_review_comment(-1) end, { desc = "Previous Diffview review comment" } },
			{ "n", "<Tab>", M.next_unviewed_file, { desc = "Next unreviewed Diffview file" } },
		},
	}
end

function M.setup()
	vim.fn.sign_define("DiffviewReviewComment", { text = COMMENT_MARKER, texthl = "DiffviewReviewCommentSign" })

	local group = vim.api.nvim_create_augroup("DiffviewReview", { clear = true })
	vim.api.nvim_create_autocmd("User", {
		group = group,
		pattern = { "DiffviewViewOpened", "DiffviewViewPostLayout", "DiffviewDiffBufWinEnter" },
		callback = function()
			vim.schedule(function()
				M.apply_highlights()
				M.refresh_visible()
				for _, winid in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
					apply_buffer_keymaps(vim.api.nvim_win_get_buf(winid))
				end
			end)
		end,
	})

	vim.api.nvim_create_user_command("DiffviewReviewComment", M.add_comment, {
		nargs = "*",
		range = true,
		force = true,
		desc = "Add or update a local Diffview review comment",
	})
	vim.api.nvim_create_user_command("DiffviewReviewDeleteComment", M.delete_comment, {
		range = true,
		force = true,
		desc = "Delete a local Diffview review comment at the current line",
	})
	vim.api.nvim_create_user_command("DiffviewReviewToggleViewed", M.toggle_file_viewed, {
		force = true,
		desc = "Toggle the current Diffview file reviewed state",
	})
	vim.api.nvim_create_user_command("DiffviewReviewStatus", M.show_status, {
		force = true,
		desc = "Show local Diffview review status",
	})
end

return M
