local M = {}

local review_format = require("utils.diffview_review_format")
local review_state = require("utils.diffview_review_state")

local NS = vim.api.nvim_create_namespace("diffview_review")
local STATUS_NS = vim.api.nvim_create_namespace("diffview_review_status")
local SIGN_GROUP = "diffview_review"
local COMMENT_MARKER = review_format.COMMENT_MARKER
local GUIDE_MARKER = review_format.GUIDE_MARKER
local last_unviewed_path = nil
local active_guide_context = nil
local guide_cache = nil

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

local function normalize_guide(decoded)
	if type(decoded) ~= "table" then
		return nil
	end

	local guide = {
		pr_number = type(decoded.pr) == "table" and decoded.pr.number or nil,
		pr_url = type(decoded.pr) == "table" and decoded.pr.url or nil,
		schema_version = decoded.schema_version or decoded.version,
		summary = type(decoded.summary) == "string" and decoded.summary or "",
		change_map = string_list(decoded.change_map),
		high_risk = string_list(decoded.high_risk),
		review_strategy = string_list(decoded.review_strategy),
		validation_focus = string_list(decoded.validation_focus),
		files = {},
		files_by_path = {},
	}

	for _, file in ipairs(type(decoded.files) == "table" and decoded.files or {}) do
		local path = type(file) == "table" and normalize_file(file.path) or nil
		if path then
			local guide_file = {
				id = string_id(file.guide_id) or string_id(file.id),
				notes = string_list(file.notes),
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
	for _, comment in ipairs(state.comments or {}) do
		if review_format.is_file_level_comment(comment) then
			comment.line = nil
			comment.end_line = nil
		end
	end

	return review_state.save(ctx, state, notify)
end

local function active_guide_path(ctx)
	if not active_guide_context or not active_guide_context.path then
		return nil
	end
	if active_guide_context.repo and ctx and ctx.root and normalize_dir(active_guide_context.repo) ~= ctx.root then
		return nil
	end
	return active_guide_context.path
end

local function load_active_guide(ctx)
	local path = active_guide_path(ctx)
	if not path then
		return nil
	end

	local mtime = vim.fn.getftime(path)
	if mtime < 0 then
		guide_cache = { path = path, mtime = mtime, guide = nil }
		return nil
	end
	if guide_cache and guide_cache.path == path and guide_cache.mtime == mtime then
		return guide_cache.guide
	end

	local read_ok, lines = pcall(vim.fn.readfile, path)
	if not read_ok then
		notify("Could not read guide JSON: " .. path, vim.log.levels.WARN)
		guide_cache = { path = path, mtime = mtime, guide = nil }
		return nil
	end

	local decode_ok, decoded = pcall(vim.fn.json_decode, table.concat(lines, "\n"))
	local guide = decode_ok and normalize_guide(decoded) or nil
	if not guide then
		notify("Ignoring invalid guide JSON: " .. path, vim.log.levels.WARN)
	else
		guide.source_path = path
		guide.context_pr_number = active_guide_context and active_guide_context.pr_number or nil
		guide.repo_key = active_guide_context and active_guide_context.repo_key or nil
	end
	guide_cache = { path = path, mtime = mtime, guide = guide }
	return guide
end

local normalize_comment_text = review_format.normalize_comment_text
local boxed_comment_lines = review_format.boxed_comment_lines
local comment_preview = review_format.comment_preview
local line_range_label = review_format.line_range_label
local range_label = review_format.range_label
local split_comment_text = review_format.split_comment_text

local function guide_hash(...)
	return vim.fn.sha256(table.concat({ ... }, "\n")):sub(1, 16)
end

local function guide_note_id(file)
	if file.id then
		return "guide:note:" .. file.path .. ":" .. file.id
	end
	return "guide:note:" .. guide_hash(file.path, "guide_note")
end

local function guide_suggestion_id(file, suggestion)
	if suggestion.id then
		return "guide:suggestion:" .. file.path .. ":" .. suggestion.id
	end
	local line_key = suggestion.line and tostring(suggestion.line) or "file"
	local end_line_key = suggestion.line and suggestion.end_line and tostring(suggestion.end_line) or line_key
	return "guide:suggestion:" .. guide_hash(
		file.path,
		"guide_suggestion",
		line_key,
		end_line_key,
		normalize_comment_text(suggestion.body)
	)
end

local function guide_note_body(notes)
	local lines = {}
	for _, note in ipairs(notes or {}) do
		table.insert(lines, "• " .. normalize_comment_text(note))
	end
	return table.concat(lines, "\n")
end

local function comment_index_by_guide_id(state)
	local index_by_id = {}
	for index, comment in ipairs(state.comments or {}) do
		if type(comment) == "table" and comment.guide_id then
			index_by_id[comment.guide_id] = index_by_id[comment.guide_id] or index
		end
	end
	return index_by_id
end

local function apply_imported_guide_comment(state, index_by_id, comment)
	if state.dismissed_guide_comments and state.dismissed_guide_comments[comment.guide_id] then
		return false
	end

	local index = index_by_id[comment.guide_id]
	if not index then
		comment.created_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
		table.insert(state.comments, comment)
		index_by_id[comment.guide_id] = #state.comments
		return true
	end

	local existing = state.comments[index]
	local changed = false
	for key, value in pairs(comment) do
		if existing[key] ~= value then
			existing[key] = value
			changed = true
		end
	end
	for _, key in ipairs({ "line", "end_line" }) do
		if comment[key] == nil and existing[key] ~= nil then
			existing[key] = nil
			changed = true
		end
	end
	if changed then
		existing.updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
	end
	return changed
end

local function import_guide_comments(state, guide)
	if not guide then
		return false
	end

	state.comments = state.comments or {}
	state.dismissed_guide_comments = state.dismissed_guide_comments or {}
	local index_by_id = comment_index_by_guide_id(state)
	local active_guide_ids = {}
	local changed = false
	local guide_pr_number = guide.pr_number or guide.context_pr_number

	for _, file in ipairs(guide.files or {}) do
		if #(file.notes or {}) > 0 then
			local guide_id = guide_note_id(file)
			active_guide_ids[guide_id] = true
			changed = apply_imported_guide_comment(state, index_by_id, {
				body = guide_note_body(file.notes),
				file = file.path,
				file_level = true,
				guide_id = guide_id,
				guide_path = guide.source_path,
				guide_pr_number = guide_pr_number,
				kind = "guide_note",
				repo_key = guide.repo_key,
				severity = "Info",
				source = "guide",
			}) or changed
		end

		for _, suggestion in ipairs(file.suggestions or {}) do
			local file_level = not suggestion.line
			local line = suggestion.line
			local end_line = suggestion.end_line or line
			local guide_id = guide_suggestion_id(file, suggestion)
			active_guide_ids[guide_id] = true
			local comment = {
				body = suggestion.body,
				file = file.path,
				file_level = file_level,
				guide_id = guide_id,
				guide_path = guide.source_path,
				guide_pr_number = guide_pr_number,
				kind = "guide_suggestion",
				repo_key = guide.repo_key,
				severity = suggestion.severity or "Medium",
				source = "guide",
				why = suggestion.why,
			}
			if not file_level then
				comment.line = line
				comment.end_line = end_line
			end
			changed = apply_imported_guide_comment(state, index_by_id, comment) or changed
		end
	end

	if guide.source_path then
		for index = #state.comments, 1, -1 do
			local comment = state.comments[index]
			if
				review_format.is_guide_comment(comment)
				and comment.guide_path == guide.source_path
				and not active_guide_ids[comment.guide_id]
			then
				table.remove(state.comments, index)
				changed = true
			end
		end
	end

	return changed
end

local function load_state_with_guide(ctx)
	local state = load_state(ctx)
	local guide = load_active_guide(ctx)
	if import_guide_comments(state, guide) then
		save_state(ctx, state)
	end
	return state, guide
end

local function clamp_comment_range(comment, line_count)
	if review_format.is_file_level_comment(comment) then
		return 1, 1
	end

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

local function find_comment(state, file, line, opts)
	local manual_only = opts and opts.manual_only
	local file_level_line = opts and tonumber(opts.file_level_line)
	line = tonumber(line)
	for index, comment in ipairs(state.comments) do
		local is_guide = review_format.is_guide_comment(comment)
		local matches_file_level = review_format.is_file_level_comment(comment)
			and file_level_line
			and line == file_level_line
		local start_line = not matches_file_level and tonumber(comment.line) or nil
		local end_line = start_line and tonumber(comment.end_line) or start_line
		if
			comment.file == file
			and (matches_file_level or (start_line and start_line <= line and line <= end_line))
			and (not manual_only or not is_guide)
		then
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

local function is_file_reviewed(state, file)
	if state.viewed[file] == true then
		return true
	end

	for saved_file, viewed in pairs(state.viewed or {}) do
		if viewed == true and normalize_file(saved_file) == file then
			return true
		end
	end
	return false
end

local function review_entries(view, state)
	local entries = {}
	for _, entry in ipairs(ordered_file_list(view)) do
		local path = entry_path(entry)
		if path then
			table.insert(entries, {
				entry = entry,
				path = path,
				viewed = is_file_reviewed(state, path),
			})
		end
	end
	return entries
end

local function order_review_entries_by_guide(entries, guide)
	if not (guide and type(guide.files) == "table") then
		return entries
	end

	local entries_by_path = {}
	for _, item in ipairs(entries) do
		if item.path and not entries_by_path[item.path] then
			entries_by_path[item.path] = item
		end
	end

	local ordered = {}
	local added = {}
	for _, file in ipairs(guide.files) do
		local path = type(file) == "table" and normalize_file(file.path) or nil
		local item = path and entries_by_path[path] or nil
		if item and not added[path] then
			table.insert(ordered, item)
			added[path] = true
		end
	end
	if #ordered == 0 then
		return entries
	end

	for _, item in ipairs(entries) do
		if item.path and not added[item.path] then
			table.insert(ordered, item)
			added[item.path] = true
		end
	end
	return ordered
end

local apply_buffer_keymaps

local function comments_for_file(state, file)
	local comments = {}
	for index, comment in ipairs(state.comments or {}) do
		if comment.file == file then
			local start_line, end_line = clamp_comment_range(comment, math.huge)
			table.insert(comments, {
				comment = comment,
				end_line = end_line or 1,
				index = index,
				start_line = start_line or 1,
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
			view:set_file(item.entry, false, true)
		else
			view:use_entry(item.entry)
		end
	end)
	if not ok then
		notify("Could not open " .. item.path, vim.log.levels.WARN)
		return
	end

	if line then
		vim.defer_fn(function()
			pcall(vim.api.nvim_win_set_cursor, 0, { math.max(1, tonumber(line) or 1), 0 })
		end, 120)
	end
end

local function review_status(file, state)
	if is_file_reviewed(state, file) then
		return {
			panel_hl = "DiffviewReviewPanelViewed",
			panel_sign = "DiffviewReviewFileReviewed",
			viewed = true,
			winbar_hl = "DiffviewReviewWinbarViewed",
			winbar_short_text = " ✓ ",
			winbar_text = " ✓ ",
		}
	end

	return {
		panel_hl = "DiffviewReviewPanelUnviewed",
		panel_sign = "DiffviewReviewFileUnreviewed",
		viewed = false,
		winbar_hl = "DiffviewReviewWinbarUnviewed",
		winbar_short_text = " ○ ",
		winbar_text = " ○ ",
	}
end

local function basename(path)
	return tostring(path or ""):match("([^/]+)$") or tostring(path or "")
end

local function with_buffer_window(bufnr, winid, fn)
	if not winid or not vim.api.nvim_win_is_valid(winid) then
		return nil
	end

	local ok, win_bufnr = pcall(vim.api.nvim_win_get_buf, winid)
	if not ok or win_bufnr ~= bufnr then
		return nil
	end

	local call_ok, result = pcall(vim.api.nvim_win_call, winid, fn)
	if call_ok then
		return result
	end
end

local function first_open_diff_line(bufnr, winid, line_count)
	return with_buffer_window(bufnr, winid, function()
		for lnum = 1, line_count do
			if vim.fn.foldclosed(lnum) == -1 then
				local ok, hl_id = pcall(vim.fn.diff_hlID, lnum, 1)
				if not ok then
					return nil
				end
				if (tonumber(hl_id) or 0) > 0 then
					return lnum
				end
			end
		end
	end)
end

local function first_open_nonempty_line(bufnr, winid, line_count)
	local ok, lines = pcall(vim.api.nvim_buf_get_lines, bufnr, 0, line_count, false)
	if not ok or type(lines) ~= "table" then
		return nil
	end

	return with_buffer_window(bufnr, winid, function()
		for lnum, line in ipairs(lines) do
			if vim.fn.foldclosed(lnum) == -1 and line:match("%S") then
				return lnum
			end
		end
	end)
end

local function first_open_line(bufnr, winid, line_count)
	return with_buffer_window(bufnr, winid, function()
		for lnum = 1, line_count do
			if vim.fn.foldclosed(lnum) == -1 then
				return lnum
			end
		end
	end)
end

local function first_nonempty_line(bufnr, line_count)
	local ok, lines = pcall(vim.api.nvim_buf_get_lines, bufnr, 0, line_count, false)
	if not ok or type(lines) ~= "table" then
		return nil
	end

	for lnum, line in ipairs(lines) do
		if line:match("%S") then
			return lnum
		end
	end
end

local function file_level_display_line(bufnr, winid, line_count)
	return first_open_diff_line(bufnr, winid, line_count)
		or first_open_nonempty_line(bufnr, winid, line_count)
		or first_open_line(bufnr, winid, line_count)
		or first_nonempty_line(bufnr, line_count)
		or 1
end

local function blank_comment_virt_lines(row_count)
	local lines = {}
	for _ = 1, row_count do
		table.insert(lines, { { " ", "DiffviewNormal" } })
	end
	return lines
end

local function render_comment_spacers(bufnr, spacer_rows_by_line, line_count)
	for display_line, row_count in pairs(spacer_rows_by_line or {}) do
		display_line = math.min(math.max(tonumber(display_line) or 1, 1), line_count)
		row_count = tonumber(row_count) or 0
		if row_count > 0 then
			vim.api.nvim_buf_set_extmark(bufnr, NS, display_line - 1, 0, {
				virt_lines = blank_comment_virt_lines(row_count),
				virt_lines_above = true,
				priority = 30,
			})
		end
	end
end

local function refresh_buffer(bufnr, file, state, show_comments, winid, spacer_rows_by_line)
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
		render_comment_spacers(bufnr, spacer_rows_by_line, line_count)
		return
	end

	local comment_boxes = {}
	local spacer_rows = {}
	for _, entry in ipairs(sorted_file_comments(state, file, line_count)) do
		local hls = review_format.comment_highlights(entry.comment)
		local marker = review_format.is_guide_comment(entry.comment) and GUIDE_MARKER or COMMENT_MARKER
		local file_level = review_format.is_file_level_comment(entry.comment)
		if not file_level then
			for lnum = entry.start_line, entry.end_line do
				vim.fn.sign_place(0, SIGN_GROUP, hls.sign, bufnr, { lnum = lnum, priority = 30 })
				vim.api.nvim_buf_set_extmark(bufnr, NS, lnum - 1, 0, {
					virt_text = { { marker, hls.range } },
					virt_text_pos = "right_align",
					priority = 35,
				})
			end
		end

		local display_line = file_level and file_level_display_line(bufnr, winid, line_count)
			or entry.start_line
		comment_boxes[display_line] = comment_boxes[display_line] or {}
		for _, line in ipairs(boxed_comment_lines(entry.comment, entry.start_line, entry.end_line)) do
			table.insert(comment_boxes[display_line], line)
		end
		spacer_rows[display_line] = #comment_boxes[display_line]
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

	return spacer_rows
end

local function fit_suffix(value, max_width)
	value = tostring(value or "")
	if max_width <= 0 then
		return ""
	end
	if vim.fn.strdisplaywidth(value) <= max_width then
		return value
	end
	if max_width <= 1 then
		return ""
	end

	local suffix = ""
	for index = #value, 1, -1 do
		local candidate = value:sub(index, #value)
		if vim.fn.strdisplaywidth(candidate) + 1 > max_width then
			break
		end
		suffix = candidate
	end
	return "…" .. suffix
end

local function winbar_file_label(file, max_width)
	if max_width <= 0 then
		return ""
	end
	if vim.fn.strdisplaywidth(file) <= max_width then
		return file
	end

	local name = basename(file)
	if vim.fn.strdisplaywidth(name) <= max_width then
		return name
	end
	return fit_suffix(name, max_width)
end

local function refresh_winbar(winid, file, state)
	local width = vim.api.nvim_win_get_width(winid)
	local status = review_status(file, state)
	local status_text = status.winbar_text
	if width < vim.fn.strdisplaywidth(status_text) + 4 then
		status_text = status.winbar_short_text
	end

	local separator = " · "
	local file_width = width - vim.fn.strdisplaywidth(status_text) - vim.fn.strdisplaywidth(separator) - 1
	local file_label = winbar_file_label(file, file_width)
	local file_part = ""
	if file_label ~= "" then
		file_part = "%#DiffviewReviewWinbarFile#" .. separator .. file_label:gsub("%%", "%%%%")
	end

	vim.wo[winid].winbar = "%#" .. status.winbar_hl .. "#" .. status_text .. file_part
end

local function refresh_file_panel(bufnr, view, state)
	if not vim.api.nvim_buf_is_valid(bufnr) then
		return
	end

	vim.api.nvim_buf_clear_namespace(bufnr, NS, 0, -1)
	vim.fn.sign_unplace(SIGN_GROUP, { buffer = bufnr })

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
			vim.fn.sign_place(0, SIGN_GROUP, status.panel_sign, bufnr, { lnum = lnum, priority = 45 })
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

function M.set_active_guide_context(context)
	active_guide_context = context and {
		path = context.path,
		pr_number = context.pr_number,
		repo = context.repo,
		repo_key = context.repo_key,
	} or nil
	guide_cache = nil
end

function M.clear_active_guide_context()
	active_guide_context = nil
	guide_cache = nil
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
	set(0, "DiffviewReviewGuideHigh", { fg = "#cf222e", bold = true })
	set(0, "DiffviewReviewGuideHighBorder", { fg = "#cf222e" })
	set(0, "DiffviewReviewGuideHighRange", { bg = "#ffebe9", fg = "#cf222e", bold = true })
	set(0, "DiffviewReviewGuideHighVirt", { fg = "#cf222e" })
	set(0, "DiffviewReviewGuideMedium", { fg = "#9a6700", bold = true })
	set(0, "DiffviewReviewGuideMediumBorder", { fg = "#9a6700" })
	set(0, "DiffviewReviewGuideMediumRange", { bg = "#fff8c5", fg = "#9a6700", bold = true })
	set(0, "DiffviewReviewGuideMediumVirt", { fg = "#9a6700" })
	set(0, "DiffviewReviewGuideLow", { fg = "#57606a", bold = true })
	set(0, "DiffviewReviewGuideLowBorder", { fg = "#57606a" })
	set(0, "DiffviewReviewGuideLowRange", { bg = "#f6f8fa", fg = "#57606a", bold = true })
	set(0, "DiffviewReviewGuideLowVirt", { fg = "#57606a" })
	set(0, "DiffviewReviewGuideInfo", { fg = "#57606a", bold = true })
	set(0, "DiffviewReviewGuideInfoBorder", { fg = "#57606a" })
	set(0, "DiffviewReviewGuideInfoRange", { bg = "#f6f8fa", fg = "#57606a", bold = true })
	set(0, "DiffviewReviewGuideInfoVirt", { fg = "#57606a" })
	set(0, "DiffviewReviewPanelUnviewed", { fg = "#9a6700", bold = true })
	set(0, "DiffviewReviewPanelViewed", { fg = "#6e7781" })
	set(0, "DiffviewReviewStatusHeader", { fg = "#24292f", bold = true })
	set(0, "DiffviewReviewStatusFile", { fg = "#57606a", bold = true })
	set(0, "DiffviewReviewStatusMuted", { fg = "#6e7781" })
	set(0, "DiffviewReviewStatusComment", { fg = "#0969da" })
	set(0, "DiffviewReviewStatusGuideHigh", { fg = "#cf222e", bold = true })
	set(0, "DiffviewReviewStatusGuideMedium", { fg = "#9a6700", bold = true })
	set(0, "DiffviewReviewStatusGuideLow", { fg = "#57606a" })
	set(0, "DiffviewReviewStatusGuideInfo", { fg = "#57606a" })
	set(0, "DiffviewReviewStatusGuideHeader", { fg = "#24292f", bold = true })
	set(0, "DiffviewReviewStatusUnviewed", { fg = "#9a6700", bold = true })
	set(0, "DiffviewReviewStatusViewed", { fg = "#1a7f37", bold = true })
	set(0, "DiffviewReviewWinbarFile", { bg = "#f6f8fa", fg = "#57606a" })
	set(0, "DiffviewReviewWinbarUnviewed", { bg = "#fff8c5", fg = "#9a6700", bold = true })
	set(0, "DiffviewReviewWinbarViewed", { bg = "#dafbe1", fg = "#1a7f37", bold = true })
end

function M.refresh_visible()
	local view = current_view()
	local ctx = repo_context(view)
	if not ctx then
		return
	end

	local state = load_state_with_guide(ctx)

	local visible = {}
	for _, winid in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
		local bufnr = vim.api.nvim_win_get_buf(winid)
		if is_file_panel_buffer(bufnr) then
			pcall(function()
				vim.wo[winid].signcolumn = "yes:1"
			end)
			refresh_file_panel(bufnr, view, state)
		else
			local file = file_for_buffer(bufnr, ctx, view)
			if file then
				table.insert(visible, { bufnr = bufnr, file = file, winid = winid })
			end
		end
	end

	local current_entry_path = normalize_file(view and view.cur_entry and view.cur_entry.path)
	local current_entry_buffers = {}
	for _, file in ipairs(entry_layout_files(view and view.cur_entry)) do
		if file.bufnr then
			current_entry_buffers[file.bufnr] = true
		end
	end

	local comment_bufnr = review_comment_bufnr(visible, view)
	local spacer_rows_by_line = {}
	if comment_bufnr then
		for _, item in ipairs(visible) do
			if item.bufnr == comment_bufnr then
				spacer_rows_by_line = refresh_buffer(item.bufnr, item.file, state, true, item.winid) or {}
			end
		end
	end

	for _, item in ipairs(visible) do
		if item.bufnr ~= comment_bufnr then
			local spacers = nil
			if current_entry_buffers[item.bufnr] or item.file == current_entry_path then
				spacers = spacer_rows_by_line
			end
			refresh_buffer(item.bufnr, item.file, state, false, item.winid, spacers)
		end
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

	local state = load_state_with_guide(ctx)
	refresh_buffer(0, ctx.file, state, true, vim.api.nvim_get_current_win())
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
	local state = load_state_with_guide(ctx)
	local existing = find_comment(state, ctx.file, line, { manual_only = true })
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
	local state = load_state_with_guide(ctx)
	local comment, index = find_comment(state, ctx.file, line, { manual_only = true })
	if not index then
		local line_count = vim.api.nvim_buf_line_count(0)
		comment, index = find_comment(state, ctx.file, line, {
			file_level_line = file_level_display_line(0, vim.api.nvim_get_current_win(), line_count),
		})
	end
	if not index then
		notify(("No review comment at %s:%d"):format(ctx.file, line), vim.log.levels.WARN)
		return
	end

	if review_format.is_guide_comment(comment) and comment.guide_id then
		state.dismissed_guide_comments = state.dismissed_guide_comments or {}
		state.dismissed_guide_comments[comment.guide_id] = true
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

	local state = load_state_with_guide(ctx)
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

function M.next_unviewed_file(direction)
	direction = direction == -1 and -1 or 1
	local ctx = current_file_context()
	local action = direction == -1 and "jumping to previous unreviewed file" or "jumping to next unreviewed file"
	if not require_active_diffview(ctx, action) or not require_repo_context(ctx, action) then
		return
	end

	local state = load_state(ctx)
	local guide = load_active_guide(ctx)
	local entries = order_review_entries_by_guide(review_entries(ctx.view, state), guide)
	local unreviewed = {}
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
			table.insert(unreviewed, { item = item, index = index })
		end
	end

	if #unreviewed == 0 then
		last_unviewed_path = nil
		notify("No unreviewed Diffview files")
		return
	end

	local start_index = last_index or current_index or 0
	local target = direction == -1 and unreviewed[#unreviewed] or unreviewed[1]
	for _, candidate in ipairs(unreviewed) do
		if direction == 1 and candidate.index > start_index then
			target = candidate
			break
		end
		if direction == -1 and candidate.index < start_index then
			target = candidate
		end
	end

	last_unviewed_path = target.item.path
	jump_to_entry(ctx.view, target.item)
end

local function guide_comment_counts(state, guide)
	local counts = { notes = 0, suggestions = 0, total = 0 }
	for _, comment in ipairs(state.comments or {}) do
		if
			review_format.is_guide_comment(comment)
			and (not (guide and guide.source_path) or comment.guide_path == guide.source_path)
		then
			counts.total = counts.total + 1
			if comment.kind == "guide_note" then
				counts.notes = counts.notes + 1
			elseif comment.kind == "guide_suggestion" then
				counts.suggestions = counts.suggestions + 1
			end
		end
	end
	return counts
end

local function status_row(action)
	return { action = action, chunks = {}, text = "" }
end

local function add_status_text(row, text, hl_group)
	local start_col = #row.text
	row.text = row.text .. text
	if hl_group then
		table.insert(row.chunks, { end_col = #row.text, hl_group = hl_group, start_col = start_col })
	end
end

local function truncate_display(value, width)
	value = tostring(value or "")
	if width <= 0 then
		return ""
	end
	if review_format.display_width(value) <= width then
		return value
	end
	if width <= 1 then
		return "…"
	end

	local result = ""
	for index = 0, vim.fn.strchars(value) - 1 do
		local char = vim.fn.strcharpart(value, index, 1)
		if review_format.display_width(result .. char .. "…") > width then
			return result .. "…"
		end
		result = result .. char
	end
	return result
end

local function take_display_prefix(value, width)
	local result = ""
	for index = 0, vim.fn.strchars(value) - 1 do
		local char = vim.fn.strcharpart(value, index, 1)
		if review_format.display_width(result .. char) > width then
			if result == "" then
				return char, vim.fn.strcharpart(value, index + 1)
			end
			return result, vim.fn.strcharpart(value, index)
		end
		result = result .. char
	end
	return result, ""
end

local function wrap_status_text(value, first_width, next_width)
	local text = review_format.normalize_comment_text(value)
	if text == "" then
		return {}
	end

	local lines = {}
	local line = ""
	local width = math.max(first_width, 1)
	local continuation_width = math.max(next_width, 1)
	for word in text:gmatch("%S+") do
		local pending = word
		while pending ~= "" do
			local separator = line ~= "" and " " or ""
			if review_format.display_width(line .. separator .. pending) <= width then
				line = line .. separator .. pending
				pending = ""
			elseif line ~= "" then
				table.insert(lines, line)
				line = ""
				width = continuation_width
			else
				local piece, rest = take_display_prefix(pending, width)
				table.insert(lines, piece)
				pending = rest
				width = continuation_width
			end
		end
	end

	if line ~= "" then
		table.insert(lines, line)
	end
	return lines
end

local function add_review_summary(rows, counts)
	local row = status_row()
	add_status_text(row, "Review:", "DiffviewReviewStatusHeader")
	add_status_text(
		row,
		(" %d files · %d reviewed · %d unreviewed · %d comments · %s %d"):format(
			counts.files,
			counts.reviewed,
			counts.unreviewed,
			counts.comments,
			GUIDE_MARKER,
			counts.guide
		),
		"DiffviewReviewStatusMuted"
	)
	table.insert(rows, row)
end

local function add_guide_status(rows, state, guide, width)
	local counts = guide_comment_counts(state, guide)
	if not guide and counts.total == 0 then
		return
	end

	local header = status_row()
	add_status_text(header, GUIDE_MARKER, "DiffviewReviewStatusGuideInfo")
	if counts.total > 0 then
		add_status_text(
			header,
			(" · %d notes · %d suggestions"):format(counts.notes, counts.suggestions),
			"DiffviewReviewStatusMuted"
		)
	end
	table.insert(rows, header)

	if guide and #(guide.change_map or {}) > 0 then
		local title = status_row()
		add_status_text(title, "  Change map:", "DiffviewReviewStatusMuted")
		table.insert(rows, title)

		for _, line in ipairs(guide.change_map) do
			local prefix = "    "
			local row = status_row()
			add_status_text(row, prefix)
			add_status_text(
				row,
				truncate_display(line, width - review_format.display_width(prefix)),
				"DiffviewReviewStatusGuideInfo"
			)
			table.insert(rows, row)
		end
	end

	if guide and guide.summary and guide.summary ~= "" then
		local prefix = "  Summary: "
		local indent = string.rep(" ", review_format.display_width(prefix))
		local summary_lines = wrap_status_text(
			guide.summary,
			width - review_format.display_width(prefix),
			width - review_format.display_width(indent)
		)
		for index, line in ipairs(summary_lines) do
			local row = status_row()
			if index == 1 then
				add_status_text(row, prefix, "DiffviewReviewStatusMuted")
			else
				add_status_text(row, indent)
			end
			add_status_text(row, line, "DiffviewReviewStatusGuideInfo")
			table.insert(rows, row)
		end
	end

	local bullet_count = 0
	for _, section in ipairs({
		{ hl = "DiffviewReviewStatusGuideHigh", items = guide and guide.high_risk or {}, label = "High" },
		{ hl = "DiffviewReviewStatusGuideMedium", items = guide and guide.validation_focus or {}, label = "Validate" },
	}) do
		for _, item in ipairs(section.items) do
			if bullet_count >= 3 then
				break
			end
			local prefix = "  • "
			local label = section.label .. ": "
			local indent = string.rep(" ", review_format.display_width(prefix .. label))
			local item_lines = wrap_status_text(
				item,
				width - review_format.display_width(prefix .. label),
				width - review_format.display_width(indent)
			)
			for index, line in ipairs(item_lines) do
				local row = status_row()
				if index == 1 then
					add_status_text(row, prefix, "DiffviewReviewStatusMuted")
					add_status_text(row, label, section.hl)
				else
					add_status_text(row, indent)
				end
				add_status_text(row, line, "DiffviewReviewStatusGuideInfo")
				table.insert(rows, row)
			end
			bullet_count = bullet_count + 1
		end
	end
	table.insert(rows, status_row())
end

local function status_comment_row(entry, item, width)
	local comment = entry.comment
	local is_guide = review_format.is_guide_comment(comment)
	local label
	if is_guide then
		label = review_format.is_file_level_comment(comment) and "File-level"
			or range_label(entry.start_line, entry.end_line)
	else
		label = line_range_label(entry.start_line, entry.end_line)
	end
	local row = status_row({ item = item, line = entry.start_line })
	local indent = "    "
	add_status_text(row, indent)

	if not is_guide then
		local prefix = COMMENT_MARKER .. " " .. label .. ": "
		add_status_text(row, COMMENT_MARKER, "DiffviewReviewStatusComment")
		add_status_text(row, " " .. label .. ": ", "DiffviewReviewStatusMuted")
		add_status_text(
			row,
			truncate_display(comment_preview(comment), width - review_format.display_width(indent .. prefix)),
			"DiffviewReviewStatusMuted"
		)
		return row
	end

	local guide_marker = GUIDE_MARKER
	local severity_hl = "DiffviewReviewStatusGuideInfo"
	local prefix = guide_marker .. " "
	if comment.kind ~= "guide_note" then
		local severity_key
		local severity
		severity, severity_key = review_format.severity_label(comment.severity)
		guide_marker = review_format.severity_emoji(severity)
		severity_hl = review_format.comment_highlights({ source = "guide", severity = severity_key }).status
		prefix = guide_marker .. label .. ": "
	end

	add_status_text(row, prefix, severity_hl)
	add_status_text(
		row,
		truncate_display(comment_preview(comment), width - review_format.display_width(indent .. prefix)),
		"DiffviewReviewStatusMuted"
	)
	return row
end

local function count_file_comments(comments)
	local counts = { guide = 0, manual = 0, total = #comments }
	for _, entry in ipairs(comments) do
		if review_format.is_guide_comment(entry.comment) then
			counts.guide = counts.guide + 1
		else
			counts.manual = counts.manual + 1
		end
	end
	return counts
end

local function status_file_row(item, comments, width)
	local counts = count_file_comments(comments)
	local row = status_row({ item = item })
	local marker_hl = item.viewed and "DiffviewReviewStatusViewed" or "DiffviewReviewStatusUnviewed"
	local suffix_width = 0

	if counts.guide > 0 then
		suffix_width = suffix_width + review_format.display_width(GUIDE_MARKER .. counts.guide)
	end
	if counts.manual > 0 then
		if suffix_width > 0 then
			suffix_width = suffix_width + 2
		end
		suffix_width = suffix_width + review_format.display_width("💬" .. counts.manual)
	end

	local gap_width = suffix_width > 0 and 2 or 0
	local path_width = math.max(12, width - 2 - gap_width - suffix_width)
	add_status_text(row, item.viewed and "✓" or "○", marker_hl)
	add_status_text(row, " ")
	if suffix_width > 0 then
		add_status_text(row, review_format.pad_right(truncate_display(item.path, path_width), path_width), "DiffviewReviewStatusFile")
		add_status_text(row, "  ")
		if counts.guide > 0 then
			add_status_text(row, GUIDE_MARKER .. counts.guide, "DiffviewReviewStatusGuideInfo")
		end
		if counts.manual > 0 then
			if counts.guide > 0 then
				add_status_text(row, "  ")
			end
			add_status_text(row, "💬" .. counts.manual, "DiffviewReviewStatusComment")
		end
	else
		add_status_text(row, truncate_display(item.path, path_width), "DiffviewReviewStatusFile")
	end
	return row
end

function M.show_status()
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "showing review status") or not require_repo_context(ctx, "showing review status") then
		return
	end

	local state, guide = load_state_with_guide(ctx)
	local entries = review_entries(ctx.view, state)
	local width = math.max(48, math.floor(vim.o.columns * 0.58))
	width = math.min(width, math.max(48, vim.o.columns - 4))
	local content_width = math.max(40, width - 2)
	local rows = {}
	local line_to_action = {}
	local comments_by_path = {}
	local counts = { comments = 0, files = #entries, guide = 0, reviewed = 0, unreviewed = 0 }

	for _, item in ipairs(entries) do
		if item.viewed then
			counts.reviewed = counts.reviewed + 1
		else
			counts.unreviewed = counts.unreviewed + 1
		end
		local comments = comments_for_file(state, item.path)
		comments_by_path[item.path] = comments
		local file_counts = count_file_comments(comments)
		counts.comments = counts.comments + file_counts.total
		counts.guide = counts.guide + file_counts.guide
	end

	add_review_summary(rows, counts)
	add_guide_status(rows, state, guide, content_width)

	for _, item in ipairs(entries) do
		local comments = comments_by_path[item.path] or {}
		local file_row = status_file_row(item, comments, content_width)
		table.insert(rows, file_row)

		for _, comment in ipairs(comments) do
			table.insert(rows, status_comment_row(comment, item, content_width))
		end
	end
	if #entries == 0 then
		local row = status_row()
		add_status_text(row, "No files in current Diffview", "DiffviewReviewStatusMuted")
		table.insert(rows, row)
	end

	local height = math.max(10, math.floor(vim.o.lines * 0.82))
	height = math.min(height, math.max(10, #rows))
	local bufnr = vim.api.nvim_create_buf(false, true)
	local lines = {}
	for index, row in ipairs(rows) do
		lines[index] = row.text
		line_to_action[index] = row.action
	end
	vim.api.nvim_buf_set_lines(bufnr, 0, -1, false, lines)
	vim.bo[bufnr].bufhidden = "wipe"
	vim.bo[bufnr].filetype = "markdown"
	vim.bo[bufnr].modifiable = false
	for lnum, row in ipairs(rows) do
		for _, chunk in ipairs(row.chunks) do
			pcall(vim.api.nvim_buf_set_extmark, bufnr, STATUS_NS, lnum - 1, chunk.start_col, {
				end_col = chunk.end_col,
				hl_group = chunk.hl_group,
				strict = false,
			})
		end
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
		if vim.api.nvim_buf_is_valid(bufnr) then
			pcall(vim.api.nvim_buf_clear_namespace, bufnr, STATUS_NS, 0, -1)
		end
		if vim.api.nvim_win_is_valid(winid) then
			pcall(vim.api.nvim_win_close, winid, true)
		end
		if vim.api.nvim_buf_is_valid(bufnr) then
			pcall(vim.api.nvim_buf_delete, bufnr, { force = true })
		end
	end

	vim.keymap.set("n", "q", close_popup, { buffer = bufnr, nowait = true, silent = true })
	vim.keymap.set("n", "<CR>", function()
		local cursor_ok, cursor = pcall(vim.api.nvim_win_get_cursor, winid)
		if not cursor_ok then
			close_popup()
			return
		end
		local action = line_to_action[cursor[1]]
		if not action then
			return
		end
		close_popup()
		jump_to_entry(ctx.view, action.item, action.line)
	end, { buffer = bufnr, nowait = true, silent = true })
end

apply_buffer_keymaps = function(bufnr)
	if not vim.api.nvim_buf_is_valid(bufnr) then
		return
	end
	vim.keymap.set("n", "<Tab>", function() M.next_unviewed_file(1) end, {
		buffer = bufnr,
		desc = "Next unreviewed Diffview file",
		nowait = true,
		silent = true,
	})
	vim.keymap.set("n", "<S-Tab>", function() M.next_unviewed_file(-1) end, {
		buffer = bufnr,
		desc = "Previous unreviewed Diffview file",
		nowait = true,
		silent = true,
	})
end

function M.diffview_keymaps()
	-- Diffview local-review keymap contract:
	-- <leader>gda/gdd edit local comments, <leader>gdv toggles reviewed,
	-- <leader>gds opens the review dashboard, <leader>gd[/] jump comments,
	-- and <Tab>/<S-Tab> move only through unreviewed files.
	return {
		view = {
			{ "n", "<leader>gda", M.add_comment, { desc = "[G]it [D]iffview [A]dd Review Comment" } },
			{ "x", "<leader>gda", M.add_comment_visual, { desc = "[G]it [D]iffview [A]dd Review Comment" } },
			{ "n", "<leader>gdd", M.delete_comment, { desc = "[G]it [D]iffview [D]elete Review Comment" } },
			{ "n", "<leader>gdv", M.toggle_file_viewed, { desc = "[G]it [D]iffview Toggle File Reviewed" } },
			{ "n", "<leader>gds", M.show_status, { desc = "[G]it [D]iffview Review [S]tatus" } },
			{ "n", "<leader>gd]", function() M.next_review_comment(1) end, { desc = "Next Diffview review comment" } },
			{ "n", "<leader>gd[", function() M.next_review_comment(-1) end, { desc = "Previous Diffview review comment" } },
			{ "n", "<Tab>", function() M.next_unviewed_file(1) end, { desc = "Next unreviewed Diffview file" } },
			{ "n", "<S-Tab>", function() M.next_unviewed_file(-1) end, { desc = "Previous unreviewed Diffview file" } },
		},
		file_panel = {
			{ "n", "<leader>gdv", M.toggle_file_viewed, { desc = "[G]it [D]iffview Toggle File Reviewed" } },
			{ "n", "<leader>gds", M.show_status, { desc = "[G]it [D]iffview Review [S]tatus" } },
			{ "n", "<leader>gd]", function() M.next_review_comment(1) end, { desc = "Next Diffview review comment" } },
			{ "n", "<leader>gd[", function() M.next_review_comment(-1) end, { desc = "Previous Diffview review comment" } },
			{ "n", "<Tab>", function() M.next_unviewed_file(1) end, { desc = "Next unreviewed Diffview file" } },
			{ "n", "<S-Tab>", function() M.next_unviewed_file(-1) end, { desc = "Previous unreviewed Diffview file" } },
		},
	}
end

function M.setup()
	vim.fn.sign_define("DiffviewReviewComment", { text = COMMENT_MARKER, texthl = "DiffviewReviewCommentSign" })
	for _, sign_name in ipairs(review_format.GUIDE_SIGN_NAMES) do
		vim.fn.sign_define(sign_name, { text = GUIDE_MARKER, texthl = sign_name })
	end
	vim.fn.sign_define("DiffviewReviewFileReviewed", { text = "✓", texthl = "DiffviewReviewPanelViewed" })
	vim.fn.sign_define("DiffviewReviewFileUnreviewed", { text = "○", texthl = "DiffviewReviewPanelUnviewed" })

	local group = vim.api.nvim_create_augroup("DiffviewReview", { clear = true })
	vim.api.nvim_create_autocmd("User", {
		group = group,
		pattern = { "DiffviewViewPostLayout", "DiffviewDiffBufWinEnter" },
		callback = function()
			vim.defer_fn(function()
				M.apply_highlights()
				M.refresh_visible()
				for _, winid in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
					if vim.api.nvim_win_is_valid(winid) then
						apply_buffer_keymaps(vim.api.nvim_win_get_buf(winid))
					end
				end
			end, 100)
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
