local M = {}

local review_format = require("utils.diffview_review_format")
local review_state = require("utils.diffview_review_state")

local NS = vim.api.nvim_create_namespace("diffview_review")
local STATUS_NS = vim.api.nvim_create_namespace("diffview_review_status")
local SIGN_GROUP = "diffview_review"
local COMMENT_MARKER = review_format.COMMENT_MARKER
local GUIDE_MARKER = review_format.GUIDE_MARKER
local GITHUB_MARKER = review_format.GITHUB_MARKER
local COMMENTS_QF_TITLE = "Diffview Review Comments"
local COMMENTS_QF_SOURCE = "diffview_review_comments"
local last_unviewed_path = nil
local active_comments_quickfix_context = nil
local active_guide_context = nil
local auto_imported_github_contexts = {}
local auto_import_scheduled_contexts = {}
local guide_cache = nil
local post_confirmation_open = false
local github_post_in_progress = false

local function notify(message, level)
	vim.notify(tostring(message or ""), level or vim.log.levels.INFO, { title = "Diffview Review" })
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

local function json_value(value)
	if value == vim.NIL then
		return nil
	end
	return value
end

local function github_repo_from_url(value)
	value = tostring(value or ""):gsub("%.git/?$", ""):gsub("/+$", "")
	value = value:gsub("/pull/%d+.*$", "")
	if value == "" then
		return nil, nil
	end

	local owner, repo = value:match("github%.com[:/]([^/]+)/([^/]+)$")
	if owner and repo then
		return owner, repo
	end
	return nil, nil
end

local function is_stale_github_anchor(comment)
	return review_format.is_imported_github_comment(comment)
		and comment.github_line == nil
		and comment.original_line ~= nil
end

local function github_status_label(comment)
	local stale_anchor = is_stale_github_anchor(comment)
	if comment.sync_status == "edited-locally" then
		return stale_anchor and "edited locally; stale original anchor" or "edited locally"
	end
	if stale_anchor then
		return "stale original anchor"
	end
	if comment.outdated == true or comment.stale == true then
		return "outdated"
	end
	if comment.sync_status == "github-unknown-resolution" then
		return "unknown resolution"
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

local function origin_repo(ctx)
	if not (ctx and ctx.root) then
		return nil, nil
	end

	local output = vim.fn.systemlist({ "git", "-C", ctx.root, "remote", "get-url", "origin" })
	if vim.v.shell_error ~= 0 then
		return nil, nil
	end
	return github_repo_from_url(table.concat(output or {}, "\n"))
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

local function active_guide_markdown_path(ctx)
	local guide_path = active_guide_path(ctx)
	if not guide_path then
		return nil
	end
	return active_guide_context.markdown_path or join_path(vim.fn.fnamemodify(guide_path, ":p:h"), "guide.md")
end

local function read_nonempty_file(path)
	if not path or vim.fn.filereadable(path) ~= 1 then
		return nil
	end

	local read_ok, lines = pcall(vim.fn.readfile, path)
	if not read_ok then
		return nil
	end
	if vim.trim(table.concat(lines, "\n")) == "" then
		return nil
	end
	return lines
end

local function review_state_path(ctx)
	local guide_path = active_guide_path(ctx)
	if guide_path then
		return join_path(vim.fn.fnamemodify(guide_path, ":p:h"), "diffview-review.json")
	end
	return join_path(ctx.root, "diffview-review.json")
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

	local ctx = {
		root = root,
		gitdir = gitdir,
	}
	ctx.state_path = review_state_path(ctx)
	return ctx
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

local function valid_tab_winid(winid)
	return type(winid) == "number"
		and vim.api.nvim_win_is_valid(winid)
		and vim.api.nvim_win_get_tabpage(winid) == vim.api.nvim_get_current_tabpage()
end

local function layout_main_winid(layout)
	if not (layout and layout.get_main_win) then
		return nil
	end

	local ok, win = pcall(function()
		return layout:get_main_win()
	end)
	local winid = ok and type(win) == "table" and win.id or nil
	if valid_tab_winid(winid) then
		return winid
	end
end

local function diffview_entry_main_winid(view, entry)
	local winid = layout_main_winid(entry and entry.layout)
	if winid then
		return winid
	end
	winid = layout_main_winid(view and view.cur_layout)
	if winid then
		return winid
	end

	local main_bufnr = entry_main_bufnr(entry)
	if not main_bufnr then
		return nil
	end
	for _, winid in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
		if vim.api.nvim_win_get_buf(winid) == main_bufnr then
			return winid
		end
	end
end

local function focus_diffview_entry(view, entry, line)
	local winid = diffview_entry_main_winid(view, entry)
	if not winid then
		return false
	end

	local focus_ok = pcall(vim.api.nvim_set_current_win, winid)
	if not focus_ok then
		return false
	end
	if not line then
		return true
	end

	local bufnr = vim.api.nvim_win_get_buf(winid)
	local line_count = math.max(vim.api.nvim_buf_line_count(bufnr), 1)
	local cursor_line = math.min(math.max(1, tonumber(line) or 1), line_count)
	return pcall(vim.api.nvim_win_set_cursor, winid, { cursor_line, 0 })
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
	local preferred_main_candidate = nil
	local main_candidate = nil
	local preferred_candidate = nil
	local fallback_candidate = nil

	for _, item in ipairs(visible) do
		if item.file == entry_path then
			fallback_candidate = item

			local entry_file = entry_file_for_buffer(entry, item.bufnr)
			if entry_file then
				if item.winid == current_win and entry_file.symbol ~= "a" then
					current_candidate = item
				end
				if main_bufnr and item.bufnr == main_bufnr then
					main_candidate = item
					if entry_file.symbol ~= "a" then
						preferred_main_candidate = item
					end
				end
				if entry_file.symbol ~= "a" and not preferred_candidate then
					preferred_candidate = item
				end
			end
		end
	end

	if current_candidate then
		return current_candidate.bufnr
	end
	if preferred_main_candidate then
		return preferred_main_candidate.bufnr
	end
	return (preferred_candidate or main_candidate or fallback_candidate or {}).bufnr
end

local function review_file_level_comment_item(visible, view)
	local entry = view and view.cur_entry or nil
	local entry_path = normalize_file(entry and entry.path)
	if not entry_path then
		return nil, nil
	end

	local current_win = vim.api.nvim_get_current_win()
	local fallback_candidate = nil
	for _, item in ipairs(visible) do
		local entry_file = entry_file_for_buffer(entry, item.bufnr)
		if entry_file and entry_file.symbol == "a" then
			if item.winid == current_win then
				return item, entry_path
			end
			fallback_candidate = fallback_candidate or item
		end
	end

	return fallback_candidate, entry_path
end

local function visible_item_by_bufnr(visible, bufnr)
	if not bufnr then
		return nil
	end
	for _, item in ipairs(visible) do
		if item.bufnr == bufnr then
			return item
		end
	end
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

local function side_from_current_buffer(view)
	local file = entry_file_for_buffer(view and view.cur_entry, vim.api.nvim_get_current_buf())
	if not file then
		return nil
	end
	return file.symbol == "a" and "LEFT" or "RIGHT"
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

local entry_path
local ordered_file_list

local function active_pr_context_matches_view(context, ctx)
	if not (context and context.diffview_rev_arg) then
		return true
	end

	return ctx and ctx.view and ctx.view.rev_arg == context.diffview_rev_arg
end

local function active_pr_context(ctx, action)
	local context = active_guide_context
	if context and context.repo and ctx and ctx.root and normalize_dir(context.repo) ~= ctx.root then
		context = nil
	end
	if context and not active_pr_context_matches_view(context, ctx) then
		context = nil
	end

	local pr_number = string_id(context and context.pr_number)
	if not pr_number then
		return nil, "Open a PR Diffview with :DiffviewPrOpen before " .. (action or "using GitHub PR comments")
	end

	local owner = context and context.owner or nil
	local repo = context and context.repo_name or nil
	if not owner or not repo then
		owner, repo = github_repo_from_url(context and context.pr_url)
	end
	if not owner or not repo then
		owner, repo = origin_repo(ctx)
	end
	if not owner or not repo then
		return nil, "Could not derive GitHub owner/repo from the active PR context or origin remote"
	end

	return {
		base_oid = string_id(context and context.base_oid),
		body = context and context.pr_body or nil,
		head_oid = string_id(context and (context.head_oid or context.pr_head_oid)),
		owner = owner,
		pull_number = pr_number,
		repo = repo,
		title = context and context.pr_title or nil,
		url = context and context.pr_url or nil,
	}
end

local function is_already_posted(comment)
	local sync_status = tostring(comment.sync_status or "")
	return sync_status == "posted"
		or sync_status == "exported"
		or sync_status == "exported-to-github"
		or comment.github_posted_at ~= nil
		or comment.github_posted_pr ~= nil
		or comment.github_comment_id ~= nil
		or comment.github_id ~= nil
		or comment.github_review_id ~= nil
end

local function is_local_manual_comment(comment)
	local source = json_value(comment and comment.source)
	return type(comment) == "table"
		and (source == nil or source == "manual")
		and not review_format.is_guide_comment(comment)
		and not review_format.is_imported_github_comment(comment)
		and not is_already_posted(comment)
end

local function set_comment_pr_context(comment, pr)
	if not (comment and pr) then
		return
	end

	local pull_number = tostring(pr.pull_number)
	local review_context = type(comment.review_context) == "table" and comment.review_context or {}
	comment.pr_number = pull_number
	if pr.url then
		comment.pr_url = pr.url
	end
	if pr.head_oid then
		comment.pr_head_oid = pr.head_oid
	end
	review_context.kind = "pr"
	review_context.head_oid = pr.head_oid
	review_context.owner = pr.owner
	review_context.repo = pr.repo
	review_context.pull_number = pull_number
	review_context.url = pr.url
	comment.review_context = review_context
end

local function comment_pr_metadata(comment)
	local review_context = type(comment.review_context) == "table" and comment.review_context or {}
	if json_value(review_context.kind) ~= "pr" then
		return nil
	end

	local pull_number = string_id(json_value(review_context.pull_number))
		or string_id(json_value(review_context.pr_number))
		or string_id(json_value(comment.pr_number))
	if not pull_number then
		return nil
	end

	local owner = json_value(review_context.owner) or json_value(comment.pr_owner) or json_value(comment.owner)
	local repo = json_value(review_context.repo) or json_value(comment.pr_repo) or json_value(comment.repo_name)
	local head_oid = json_value(review_context.head_oid) or json_value(review_context.pr_head_oid) or json_value(comment.pr_head_oid)
	local pr_url = json_value(review_context.url) or json_value(comment.pr_url)
	if (not owner or not repo) and pr_url then
		local url_owner, url_repo = github_repo_from_url(pr_url)
		owner = owner or url_owner
		repo = repo or url_repo
	end

	return {
		head_oid = head_oid and tostring(head_oid) or nil,
		owner = owner and tostring(owner) or nil,
		pull_number = pull_number,
		repo = repo and tostring(repo) or nil,
	}
end

local function comment_matches_pr(comment, pr)
	local metadata = comment_pr_metadata(comment)
	if not metadata then
		return false, "missing-pr-context"
	end
	if not metadata.owner or not metadata.repo then
		return false, "missing-pr-context"
	end
	if metadata.pull_number ~= tostring(pr.pull_number) then
		return false, "different-pr-context"
	end
	if metadata.owner:lower() ~= tostring(pr.owner):lower() then
		return false, "different-pr-context"
	end
	if metadata.repo:lower() ~= tostring(pr.repo):lower() then
		return false, "different-pr-context"
	end
	if not metadata.head_oid or metadata.head_oid == "" or not pr.head_oid or pr.head_oid == "" then
		return false, "missing-head-context"
	end
	if metadata.head_oid:lower() ~= tostring(pr.head_oid):lower() then
		return false, "different-head-context"
	end
	return true
end

local function diffview_file_set(view)
	local files = {}
	for _, entry in ipairs(ordered_file_list(view)) do
		local path = entry_path(entry)
		if path then
			files[path] = true
		end
	end
	return files
end

local function github_import_context_key(ctx, pr)
	return table.concat({ ctx.root or "", pr.owner or "", pr.repo or "", pr.pull_number or "" }, "\n")
end

local function flatten_github_comment_pages(decoded)
	if type(decoded[1]) == "table" and json_value(decoded[1].id) == nil and json_value(decoded[1].path) == nil then
		local comments = {}
		for _, page in ipairs(decoded) do
			if type(page) ~= "table" then
				return nil, "gh api returned invalid paginated JSON"
			end
			vim.list_extend(comments, page)
		end
		return comments
	end
	return decoded
end

local function split_top_level_json_values(text)
	local values = {}
	local start = nil
	local depth = 0
	local in_string = false
	local escaped = false
	for index = 1, #text do
		local char = text:sub(index, index)
		if in_string then
			if escaped then
				escaped = false
			elseif char == "\\" then
				escaped = true
			elseif char == '"' then
				in_string = false
			end
		elseif char == '"' then
			in_string = true
		elseif char == "{" or char == "[" then
			if depth == 0 then
				start = index
			end
			depth = depth + 1
		elseif char == "}" or char == "]" then
			depth = depth - 1
			if depth < 0 then
				return nil
			end
			if depth == 0 and start then
				table.insert(values, text:sub(start, index))
				start = nil
			end
		elseif depth == 0 and not char:match("%s") then
			return nil
		end
	end
	if in_string or depth ~= 0 then
		return nil
	end
	return values
end

local function decode_concatenated_github_comments(text)
	local values = split_top_level_json_values(text)
	if not values or #values == 0 then
		return nil, "gh api returned invalid JSON"
	end

	local comments = {}
	for _, value in ipairs(values) do
		local ok, decoded = pcall(vim.fn.json_decode, value)
		if not ok or type(decoded) ~= "table" then
			return nil, "gh api returned invalid paginated JSON"
		end
		local page, page_error = flatten_github_comment_pages(decoded)
		if not page then
			return nil, page_error
		end
		vim.list_extend(comments, page)
	end
	return comments
end

local function decode_github_comments(output, allow_concatenated)
	local text = table.concat(output or {}, "\n")
	local ok, decoded = pcall(vim.fn.json_decode, text)
	if ok and type(decoded) == "table" then
		return flatten_github_comment_pages(decoded)
	end
	if allow_concatenated then
		return decode_concatenated_github_comments(text)
	end
	return nil, "gh api returned invalid JSON"
end

local function is_unknown_slurp_flag_error(output)
	local details = table.concat(output or {}, "\n"):lower()
	return details:match("unknown flag") ~= nil and details:match("slurp") ~= nil
end

local function fetch_github_comments(pr)
	if vim.fn.executable("gh") ~= 1 then
		return nil, "gh CLI is unavailable; install gh and run gh auth login before importing GitHub comments"
	end

	local endpoint = ("repos/%s/%s/pulls/%s/comments?per_page=100"):format(pr.owner, pr.repo, pr.pull_number)
	local output = vim.fn.systemlist({ "gh", "api", "--paginate", "--slurp", endpoint })
	if vim.v.shell_error ~= 0 then
		if is_unknown_slurp_flag_error(output) then
			local fallback_output = vim.fn.systemlist({ "gh", "api", "--paginate", endpoint })
			if vim.v.shell_error == 0 then
				return decode_github_comments(fallback_output, true)
			end
			local fallback_details = vim.trim(table.concat(fallback_output or {}, "\n"))
			if fallback_details ~= "" then
				return nil, "gh api fallback without --slurp failed: " .. fallback_details
			end
			return nil, "gh api fallback without --slurp failed; check gh auth status and network access"
		end
		local details = vim.trim(table.concat(output or {}, "\n"))
		if details ~= "" then
			return nil, "gh api failed: " .. details
		end
		return nil, "gh api failed; check gh auth status and network access"
	end
	return decode_github_comments(output)
end

local function copy_json_field(target, source, key)
	local value = json_value(source[key])
	if value ~= nil then
		target[key] = value
	end
end

local function normalize_github_comment(raw, files)
	if type(raw) ~= "table" then
		return nil, "invalid"
	end

	local raw_path = json_value(raw.path)
	local path = type(raw_path) == "string" and normalize_file(raw_path) or nil
	if not path then
		return nil, "missing-path"
	end
	if not files[path] then
		return nil, "unmappable-path"
	end

	local github_id = string_id(json_value(raw.id))
	if not github_id then
		return nil, "missing-id"
	end

	local user = json_value(raw.user)
	local current_line = positive_line(json_value(raw.line))
	local original_line = positive_line(json_value(raw.original_line))
	local start_line = current_line and positive_line(json_value(raw.start_line)) or nil
	local original_start_line = positive_line(json_value(raw.original_start_line))
	local body = tostring(json_value(raw.body) or "")
	local resolved = json_value(raw.resolved)
	local sync_status = "github-unknown-resolution"
	if resolved == true then
		sync_status = "github-resolved-hidden"
	elseif resolved == false then
		sync_status = "imported"
	end
	local comment = {
		author = type(user) == "table" and json_value(user.login) or nil,
		body = body,
		file = path,
		github_body = body,
		github_id = github_id,
		github_in_reply_to_id = string_id(json_value(raw.in_reply_to_id)),
		github_node_id = json_value(raw.node_id),
		github_review_id = string_id(json_value(raw.pull_request_review_id)),
		github_thread_id = string_id(json_value(raw.thread_id)),
		github_url = json_value(raw.html_url) or json_value(raw.url),
		kind = "github_review_comment",
		original_line = original_line,
		original_start_line = original_start_line,
		path = path,
		pull_request_url = json_value(raw.pull_request_url),
		source = "github",
		start_line = start_line,
		sync_status = sync_status,
	}

	if current_line then
		comment.line = current_line
		comment.github_line = current_line
		if start_line and current_line ~= start_line then
			comment.end_line = current_line
		end
	else
		comment.file_level = true
	end

	for _, key in ipairs({
		"commit_id",
		"created_at",
		"diff_hunk",
		"original_commit_id",
		"original_position",
		"outdated",
		"position",
		"pull_request_url",
		"resolved",
		"side",
		"stale",
		"start_side",
		"subject_type",
		"updated_at",
	}) do
		copy_json_field(comment, raw, key)
	end
	if not current_line and original_line then
		comment.file_level = true
		comment.outdated = true
	end

	return comment
end

local function comment_index_by_github_id(state)
	local index_by_id = {}
	for index, comment in ipairs(state.comments or {}) do
		if review_format.is_imported_github_comment(comment) and comment.github_id then
			index_by_id[tostring(comment.github_id)] = index_by_id[tostring(comment.github_id)] or index
		end
	end
	return index_by_id
end

local GITHUB_OPTIONAL_FIELDS = {
	"author",
	"commit_id",
	"diff_hunk",
	"end_line",
	"file_level",
	"github_line",
	"github_in_reply_to_id",
	"github_node_id",
	"github_review_id",
	"github_thread_id",
	"github_url",
	"line",
	"original_commit_id",
	"original_line",
	"original_position",
	"original_start_line",
	"outdated",
	"position",
	"pull_request_url",
	"resolved",
	"side",
	"stale",
	"start_side",
	"start_line",
	"subject_type",
}

local function update_github_comment(existing, incoming, preserve_body)
	local changed = false
	for key, value in pairs(incoming) do
		if key ~= "body" or not preserve_body then
			if existing[key] ~= value then
				existing[key] = value
				changed = true
			end
		end
	end
	for _, key in ipairs(GITHUB_OPTIONAL_FIELDS) do
		if incoming[key] == nil and existing[key] ~= nil then
			existing[key] = nil
			changed = true
		end
	end
	return changed
end

local function apply_imported_github_comment(state, index_by_id, incoming, stats)
	if state.dismissed_github_comments and state.dismissed_github_comments[incoming.github_id] then
		stats.dismissed = stats.dismissed + 1
		return false
	end

	local index = index_by_id[incoming.github_id]
	if not index then
		table.insert(state.comments, incoming)
		index_by_id[incoming.github_id] = #state.comments
		stats.imported = stats.imported + 1
		return true
	end

	local existing = state.comments[index]
	local remote_body = tostring(incoming.github_body or "")
	local prior_remote_body = tostring(existing.github_body or "")
	local local_body = tostring(existing.body or "")
	local preserve_body = local_body ~= prior_remote_body and local_body ~= remote_body
	if preserve_body then
		incoming.sync_status = "edited-locally"
		stats.edited_locally = stats.edited_locally + 1
	end

	if update_github_comment(existing, incoming, preserve_body) then
		stats.updated = stats.updated + 1
		return true
	end
	stats.unchanged = stats.unchanged + 1
	return false
end

local function import_github_comments_into_state(state, raw_comments, files)
	state.comments = state.comments or {}
	state.dismissed_github_comments = state.dismissed_github_comments or {}
	local stats = { dismissed = 0, edited_locally = 0, imported = 0, skipped = 0, unchanged = 0, updated = 0 }
	local index_by_id = comment_index_by_github_id(state)
	local changed = false

	for _, raw in ipairs(raw_comments or {}) do
		local comment = normalize_github_comment(raw, files)
		if comment then
			changed = apply_imported_github_comment(state, index_by_id, comment, stats) or changed
		else
			stats.skipped = stats.skipped + 1
		end
	end

	return changed, stats
end

local function is_hidden_comment(comment)
	return comment.resolved == true or comment.sync_status == "github-resolved-hidden"
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
	if review_format.is_imported_github_comment(comment) then
		start_line = tonumber(comment.start_line) or start_line
	end
	if not start_line then
		return nil, nil
	end

	local end_line = tonumber(comment.end_line) or tonumber(comment.line) or start_line
	start_line, end_line = math.min(start_line, end_line), math.max(start_line, end_line)
	start_line = math.min(math.max(start_line, 1), line_count)
	end_line = math.min(math.max(end_line, 1), line_count)
	return start_line, end_line
end

local function sorted_file_comments(state, file, line_count)
	local comments = {}
	file = normalize_file(file)
	for index, comment in ipairs(state.comments or {}) do
		if
			normalize_file(comment.file) == file
			and not is_hidden_comment(comment)
		then
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

local function comment_source_rank(comment)
	if review_format.is_imported_github_comment(comment) then
		return 1
	end
	if review_format.is_guide_comment(comment) then
		return 2
	end
	return 3
end

local function comment_thread_key(entry)
	if review_format.is_file_level_comment(entry.comment) then
		return "file-level"
	end
	return ("%d:%d"):format(entry.start_line, entry.end_line)
end

local function sort_thread_entries(entries)
	table.sort(entries, function(left, right)
		local left_rank = comment_source_rank(left.comment)
		local right_rank = comment_source_rank(right.comment)
		if left_rank ~= right_rank then
			return left_rank < right_rank
		end
		local left_created = tostring(left.comment.created_at or "")
		local right_created = tostring(right.comment.created_at or "")
		if left_created ~= right_created then
			return left_created < right_created
		end
		return left.index < right.index
	end)
end

local function comment_threads_for_file(state, file, line_count, side)
	side = tostring(side or ""):upper()
	if side ~= "LEFT" and side ~= "RIGHT" then
		side = nil
	end

	local threads = {}
	local threads_by_key = {}
	for _, entry in ipairs(sorted_file_comments(state, file, line_count)) do
		local file_level = review_format.is_file_level_comment(entry.comment)
		local comment_side = tostring(entry.comment.side or ""):upper()
		if comment_side ~= "LEFT" and comment_side ~= "RIGHT" then
			comment_side = "RIGHT"
		end

		if not side or file_level or comment_side == side then
			local key = comment_thread_key(entry)
			local thread = threads_by_key[key]
			if not thread then
				thread = {
					end_line = entry.end_line,
					entries = {},
					file_level = file_level,
					start_line = entry.start_line,
				}
				threads_by_key[key] = thread
				table.insert(threads, thread)
			end
			table.insert(thread.entries, entry)
		end
	end

	for _, thread in ipairs(threads) do
		sort_thread_entries(thread.entries)
	end
	return threads
end

local function thread_source_summary(entries)
	local counts = {}
	local order = {}
	for _, entry in ipairs(entries) do
		local label = review_format.comment_source_label(entry.comment)
		local status = review_format.comment_status_text(entry.comment)
		if status ~= "" then
			label = label .. " [" .. status .. "]"
		end
		if not counts[label] then
			counts[label] = 0
			table.insert(order, label)
		end
		counts[label] = counts[label] + 1
	end

	local labels = {}
	for _, label in ipairs(order) do
		local count = counts[label]
		table.insert(labels, count > 1 and (label .. " ×" .. count) or label)
	end
	return table.concat(labels, " → ")
end

local function thread_banner_lines(thread)
	if #(thread.entries or {}) <= 1 then
		return {}
	end

	local anchor = thread.file_level and "File-level" or line_range_label(thread.start_line, thread.end_line)
	local header = "╭─ Review thread • " .. anchor .. " • " .. thread_source_summary(thread.entries) .. " "
	header = header
		.. string.rep("─", math.max(review_format.COMMENT_BOX_WIDTH - review_format.display_width(header) - 1, 0))
		.. "╮"
	return {
		{ { header, "DiffviewReviewStatusMuted" } },
		{ { "╰" .. string.rep("─", review_format.COMMENT_BOX_WIDTH - 2) .. "╯", "DiffviewReviewStatusMuted" } },
	}
end

local function find_comment(state, file, line, opts)
	local manual_only = opts and opts.manual_only
	local file_level_line = opts and tonumber(opts.file_level_line)
	line = tonumber(line)
	for index, comment in ipairs(state.comments or {}) do
		local is_guide = review_format.is_guide_comment(comment)
		local is_github = review_format.is_imported_github_comment(comment)
		local matches_file_level = review_format.is_file_level_comment(comment)
			and file_level_line
			and line == file_level_line
		local start_line, end_line = nil, nil
		if not matches_file_level then
			start_line, end_line = clamp_comment_range(comment, math.huge)
		end
		if
			comment.file == file
			and not is_hidden_comment(comment)
			and (matches_file_level or (start_line and start_line <= line and line <= end_line))
			and (not manual_only or (not is_guide and not is_github))
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

entry_path = function(entry)
	if type(entry) ~= "table" or not entry.path then
		return nil
	end
	return normalize_file(entry.path)
end

ordered_file_list = function(view)
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

local function first_guide_ordered_entry(entries, guide)
	if not (guide and type(guide.files) == "table") then
		return nil
	end

	local entries_by_path = {}
	for _, item in ipairs(entries) do
		if item.path and not entries_by_path[item.path] then
			entries_by_path[item.path] = item
		end
	end

	for _, file in ipairs(guide.files) do
		local path = type(file) == "table" and normalize_file(file.path) or nil
		local item = path and entries_by_path[path] or nil
		if item then
			return item
		end
	end
end

local apply_buffer_keymaps

local function comments_for_file(state, file)
	local comments = {}
	for _, entry in ipairs(sorted_file_comments(state, file, math.huge)) do
		table.insert(comments, {
			comment = entry.comment,
			end_line = entry.end_line or 1,
			index = entry.index,
			start_line = entry.start_line or 1,
		})
	end
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

	local focus_ok = focus_diffview_entry(view, item.entry, line)
	if not focus_ok then
		notify("Could not focus " .. item.path, vim.log.levels.WARN)
		return false
	end
	if line then
		vim.defer_fn(function()
			focus_diffview_entry(view, item.entry, line)
		end, 120)
	end

	return true
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

local function review_virtual_rows_extmark(display_line, virt_lines)
	return display_line <= 1 and 0 or display_line - 1, {
		virt_lines = virt_lines,
		virt_lines_above = display_line > 1,
		priority = 30,
	}
end

local function render_comment_spacers(bufnr, spacer_rows_by_line, line_count)
	for display_line, row_count in pairs(spacer_rows_by_line or {}) do
		display_line = math.min(math.max(tonumber(display_line) or 1, 1), line_count)
		row_count = tonumber(row_count) or 0
		if row_count > 0 then
			local lnum, opts = review_virtual_rows_extmark(display_line, blank_comment_virt_lines(row_count))
			vim.api.nvim_buf_set_extmark(bufnr, NS, lnum, 0, opts)
		end
	end
end

local function comment_render_mode(mode)
	if mode == false or mode == "spacers" then
		return "spacers"
	end
	if mode == "file_level_only" or mode == "exclude_file_level" then
		return mode
	end
	return "all"
end

local function render_thread_in_mode(thread, mode)
	if mode == "spacers" then
		return false
	end
	if mode == "file_level_only" then
		return thread.file_level
	end
	if mode == "exclude_file_level" then
		return not thread.file_level
	end
	return true
end

local function thread_card_row_count(thread)
	local row_count = #thread_banner_lines(thread)
	for _, entry in ipairs(thread.entries) do
		row_count = row_count + #boxed_comment_lines(entry.comment, entry.start_line, entry.end_line)
	end
	return row_count
end

local function merge_spacer_rows(...)
	local merged = {}
	for _, spacer_rows in ipairs({ ... }) do
		for display_line, row_count in pairs(spacer_rows or {}) do
			merged[display_line] = (merged[display_line] or 0) + row_count
		end
	end
	return merged
end

local function comment_spacer_rows_for_file(bufnr, file, state, mode, winid, side)
	bufnr = bufnr == 0 and vim.api.nvim_get_current_buf() or bufnr
	if not file or not vim.api.nvim_buf_is_valid(bufnr) then
		return {}
	end

	local line_count = vim.api.nvim_buf_line_count(bufnr)
	if line_count == 0 then
		return {}
	end

	mode = comment_render_mode(mode)
	local spacer_rows = {}
	for _, thread in ipairs(comment_threads_for_file(state, file, line_count, side)) do
		if render_thread_in_mode(thread, mode) then
			local display_line = thread.file_level and file_level_display_line(bufnr, winid, line_count)
				or thread.start_line
			spacer_rows[display_line] = (spacer_rows[display_line] or 0) + thread_card_row_count(thread)
		end
	end
	return spacer_rows
end

local function refresh_buffer(bufnr, file, state, mode, winid, spacer_rows_by_line, side)
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

	mode = comment_render_mode(mode)
	render_comment_spacers(bufnr, spacer_rows_by_line, line_count)
	if mode == "spacers" then
		return
	end

	local comment_boxes = {}
	local spacer_rows = {}
	for _, thread in ipairs(comment_threads_for_file(state, file, line_count, side)) do
		if render_thread_in_mode(thread, mode) then
			for _, entry in ipairs(thread.entries) do
				local hls = review_format.comment_highlights(entry.comment)
				local marker = review_format.is_imported_github_comment(entry.comment) and GITHUB_MARKER
					or (review_format.is_guide_comment(entry.comment) and GUIDE_MARKER or COMMENT_MARKER)
				if not review_format.is_file_level_comment(entry.comment) then
					for lnum = entry.start_line, entry.end_line do
						vim.fn.sign_place(0, SIGN_GROUP, hls.sign, bufnr, { lnum = lnum, priority = 30 })
						vim.api.nvim_buf_set_extmark(bufnr, NS, lnum - 1, 0, {
							virt_text = { { marker, hls.range } },
							virt_text_pos = "right_align",
							priority = 35,
						})
					end
				end
			end

			local display_line = thread.file_level and file_level_display_line(bufnr, winid, line_count)
				or thread.start_line
			comment_boxes[display_line] = comment_boxes[display_line] or {}
			for _, line in ipairs(thread_banner_lines(thread)) do
				table.insert(comment_boxes[display_line], line)
			end
			for _, entry in ipairs(thread.entries) do
				for _, line in ipairs(boxed_comment_lines(entry.comment, entry.start_line, entry.end_line)) do
					table.insert(comment_boxes[display_line], line)
				end
			end
			spacer_rows[display_line] = #comment_boxes[display_line]
		end
	end

	local display_lines = vim.tbl_keys(comment_boxes)
	table.sort(display_lines)
	for _, display_line in ipairs(display_lines) do
		local lnum, opts = review_virtual_rows_extmark(display_line, comment_boxes[display_line])
		vim.api.nvim_buf_set_extmark(bufnr, NS, lnum, 0, opts)
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
		base_oid = context.base_oid,
		context_kind = context.context_kind,
		diffview_rev_arg = context.diffview_rev_arg,
		head_oid = context.head_oid or context.pr_head_oid,
		markdown_path = context.markdown_path,
		owner = context.owner,
		path = context.path,
		pr_body = context.pr_body,
		pr_number = context.pr_number,
		pr_title = context.pr_title,
		pr_url = context.pr_url,
		repo_name = context.repo_name,
		repo = context.repo,
		repo_key = context.repo_key,
		initial_guide_jump_done = false,
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
	set(0, "DiffviewReviewGithub", { fg = "#8250df", bold = true })
	set(0, "DiffviewReviewGithubBorder", { fg = "#8250df" })
	set(0, "DiffviewReviewGithubRange", { bg = "#fbefff", fg = "#8250df", bold = true })
	set(0, "DiffviewReviewGithubVirt", { fg = "#8250df" })
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
	set(0, "DiffviewReviewStatusGithub", { fg = "#8250df", bold = true })
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
				local entry_file = entry_file_for_buffer(view and view.cur_entry, bufnr)
				local side = entry_file and (entry_file.symbol == "a" and "LEFT" or "RIGHT") or nil
				table.insert(visible, {
					bufnr = bufnr,
					file = file,
					side = side,
					winid = winid,
				})
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

	local left_comment_item = nil
	local right_comment_item = nil
	for _, item in ipairs(visible) do
		if item.side == "LEFT" then
			left_comment_item = left_comment_item or item
		elseif item.side == "RIGHT" then
			right_comment_item = right_comment_item or item
		end
	end
	local normal_comment_item = right_comment_item or visible_item_by_bufnr(visible, review_comment_bufnr(visible, view))
	local file_level_item, file_level_file = review_file_level_comment_item(visible, view)
	if not file_level_item then
		file_level_item = normal_comment_item
		file_level_file = normal_comment_item and normal_comment_item.file or nil
	end

	local spacer_rows_by_line = {}
	local rendered_buffers = {}
	local render_targets = {}
	local render_target_by_bufnr = {}

	local function add_render_target(item, file, mode, side)
		if not item then
			return
		end
		local target = render_target_by_bufnr[item.bufnr]
		if not target then
			target = {
				file = file or item.file,
				item = item,
				mode = mode,
				side = side,
			}
			render_target_by_bufnr[item.bufnr] = target
			table.insert(render_targets, target)
			return
		end

		target.file = file or target.file
		if target.mode ~= mode then
			target.mode = "all"
		end
		if side and target.side and target.side ~= side then
			target.side = nil
			target.all_sides = true
		elseif side and not target.all_sides then
			target.side = side
		end
	end

	add_render_target(left_comment_item, nil, "exclude_file_level", "LEFT")
	local normal_comment_side = normal_comment_item and tostring(normal_comment_item.side or ""):upper() or ""
	if normal_comment_side ~= "LEFT" and normal_comment_side ~= "RIGHT" then
		normal_comment_side = "RIGHT"
	end
	add_render_target(
		normal_comment_item,
		nil,
		"exclude_file_level",
		normal_comment_side
	)
	add_render_target(
		file_level_item,
		file_level_file,
		"file_level_only",
		file_level_item and file_level_item.side
	)

	for _, target in ipairs(render_targets) do
		target.spacers = comment_spacer_rows_for_file(
			target.item.bufnr,
			target.file,
			state,
			target.mode,
			target.item.winid,
			target.side
		)
	end

	for _, target in ipairs(render_targets) do
		local other_spacers = {}
		for _, other in ipairs(render_targets) do
			if other ~= target then
				other_spacers = merge_spacer_rows(other_spacers, other.spacers)
			end
		end
		refresh_buffer(
			target.item.bufnr,
			target.file,
			state,
			target.mode,
			target.item.winid,
			other_spacers,
			target.side
		)
		rendered_buffers[target.item.bufnr] = true
		spacer_rows_by_line = merge_spacer_rows(spacer_rows_by_line, target.spacers)
	end

	for _, item in ipairs(visible) do
		if not rendered_buffers[item.bufnr] then
			local spacers = nil
			if current_entry_buffers[item.bufnr] or item.file == current_entry_path then
				spacers = spacer_rows_by_line
			end
			refresh_buffer(item.bufnr, item.file, state, "spacers", item.winid, spacers)
		end
		refresh_winbar(item.winid, item.file, state)
	end
end

function M.jump_to_initial_guide_file()
	local context = active_guide_context
	if not context or context.initial_guide_jump_done then
		return
	end

	local view = current_view()
	local ctx = repo_context(view)
	if not (view and ctx) then
		return
	end
	if context.repo and ctx.root and normalize_dir(context.repo) ~= ctx.root then
		return
	end
	if not active_pr_context_matches_view(context, ctx) then
		return
	end

	local state, guide = load_state_with_guide(ctx)
	local entries = review_entries(view, state)
	if #entries == 0 then
		return
	end

	local item = first_guide_ordered_entry(entries, guide)
	context.initial_guide_jump_done = true
	if item and normalize_file(view.cur_entry and view.cur_entry.path) ~= item.path then
		jump_to_entry(view, item)
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
	refresh_buffer(
		0,
		ctx.file,
		state,
		true,
		vim.api.nvim_get_current_win(),
		nil,
		side_from_current_buffer(ctx.view)
	)
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
	local side = side_from_current_buffer(ctx.view)
	local pr = active_pr_context(ctx)

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
			if side then
				existing.side = side
			end
			if pr and is_local_manual_comment(existing) then
				set_comment_pr_context(existing, pr)
			end
			existing.updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
		else
			local comment = {
				file = ctx.file,
				line = line,
				body = input,
				created_at = os.date("!%Y-%m-%dT%H:%M:%SZ"),
				side = side,
			}
			if end_line ~= line then
				comment.end_line = end_line
			end
			if pr then
				set_comment_pr_context(comment, pr)
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

local function remove_comment_at_index(state, index)
	local comment = state.comments and state.comments[index] or nil
	if not comment then
		return nil
	end

	if review_format.is_guide_comment(comment) and comment.guide_id then
		state.dismissed_guide_comments = state.dismissed_guide_comments or {}
		state.dismissed_guide_comments[comment.guide_id] = true
	end
	if review_format.is_imported_github_comment(comment) and comment.github_id then
		state.dismissed_github_comments = state.dismissed_github_comments or {}
		state.dismissed_github_comments[tostring(comment.github_id)] = true
	end
	table.remove(state.comments, index)
	return comment
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

	remove_comment_at_index(state, index)
	if save_state(ctx, state) then
		notify(("Deleted review comment at %s:%d"):format(ctx.file, line))
		M.refresh_visible()
	end
end

function M.resolve_comment(opts)
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "resolving a review comment") then
		return
	end
	if not require_repo_context(ctx, "resolving a review comment") then
		return
	end
	if not ctx.file then
		notify("Open a Diffview file before resolving a review comment", vim.log.levels.WARN)
		return
	end

	local line = line_from_opts(opts)
	local state = load_state_with_guide(ctx)
	local _, index = find_comment(state, ctx.file, line, { manual_only = true })
	if not index then
		local line_count = vim.api.nvim_buf_line_count(0)
		_, index = find_comment(state, ctx.file, line, {
			file_level_line = file_level_display_line(0, vim.api.nvim_get_current_win(), line_count),
		})
	end
	if not index then
		notify(("No review comment at %s:%d"):format(ctx.file, line), vim.log.levels.WARN)
		return
	end

	local comment = state.comments[index]
	comment.resolved = true
	if review_format.is_imported_github_comment(comment) then
		comment.sync_status = "github-resolved-hidden"
	end
	comment.updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
	if save_state(ctx, state) then
		notify(("Resolved review comment at %s:%d"):format(ctx.file, line))
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

local function is_comments_quickfix_context(context)
	return type(context) == "table" and context.source == COMMENTS_QF_SOURCE
end

local function comment_qf_marker(comment)
	if review_format.is_imported_github_comment(comment) then
		return GITHUB_MARKER
	end
	if review_format.is_guide_comment(comment) then
		if comment.kind == "guide_note" then
			return GUIDE_MARKER
		end
		local severity = review_format.severity_label(comment.severity)
		return review_format.severity_emoji(severity)
	end
	return COMMENT_MARKER
end

local function comment_qf_text(entry)
	local comment = entry.comment
	local range = review_format.is_file_level_comment(comment) and "file-level"
		or line_range_label(entry.start_line, entry.end_line)
	local parts = { comment_qf_marker(comment), range, review_format.comment_source_label(comment) }
	local status = review_format.comment_status_text(comment)
	if status ~= "" then
		table.insert(parts, "[" .. status .. "]")
	end

	return table.concat(parts, " ") .. " — " .. comment_preview(comment)
end

local function quickfix_target(ctx, item, entry)
	local comment = entry.comment
	return {
		body = normalize_comment_text(comment.body),
		created_at = comment.created_at,
		end_line = entry.end_line,
		file_level = review_format.is_file_level_comment(comment),
		github_id = comment.github_id and tostring(comment.github_id) or nil,
		guide_id = comment.guide_id,
		line = entry.start_line,
		marker = comment_qf_marker(comment),
		path = item.path,
		source = COMMENTS_QF_SOURCE,
		state_index = entry.index,
		state_path = ctx.state_path,
	}
end

local function comments_quickfix_items(ctx, state)
	local qf_items = {}
	local targets = {}
	for _, item in ipairs(review_entries(ctx.view, state)) do
		for _, entry in ipairs(comments_for_file(state, item.path)) do
			local target = quickfix_target(ctx, item, entry)
			table.insert(targets, target)
			table.insert(qf_items, {
				filename = join_path(ctx.root, item.path),
				lnum = target.line or 1,
				end_lnum = target.end_line,
				col = 1,
				text = comment_qf_text(entry),
				user_data = target,
			})
		end
	end
	return qf_items, targets
end

local function comments_quickfix_info()
	local info = vim.fn.getqflist({ context = 0, id = 0, idx = 0, items = 0, title = 0 })
	if not is_comments_quickfix_context(info.context) then
		return nil
	end
	return info
end

local function qf_cursor_index(info)
	local item_count = #(info.items or {})
	if vim.bo.filetype == "qf" then
		local cursor = vim.api.nvim_win_get_cursor(0)[1]
		if cursor >= 1 and cursor <= item_count then
			return cursor
		end
	end
	local index = tonumber(info.idx) or 1
	if index < 1 or index > item_count then
		return 1
	end
	return index
end

local function quickfix_target_at(info, index)
	local item = info.items and info.items[index] or nil
	local target = item and item.user_data or nil
	if type(target) == "table" and target.source == COMMENTS_QF_SOURCE then
		return target
	end

	local context_targets = type(info.context) == "table" and info.context.targets or nil
	target = type(context_targets) == "table" and context_targets[index] or nil
	if type(target) == "table" and target.source == COMMENTS_QF_SOURCE then
		return target
	end
end

local function view_has_valid_main_window(view)
	local layout = view and view.cur_layout
	if not (layout and layout.get_main_win) then
		return false
	end

	local ok, main_win = pcall(function()
		return layout:get_main_win()
	end)
	local winid = ok and type(main_win) == "table" and main_win.id or nil
	return type(winid) == "number"
		and vim.api.nvim_win_is_valid(winid)
		and vim.api.nvim_win_get_tabpage(winid) == vim.api.nvim_get_current_tabpage()
end

local function active_quickfix_context(target, action)
	local view = current_view()
	local ctx = view and repo_context(view) or nil
	if ctx then
		ctx.view = view
	end
	if not ctx and active_comments_quickfix_context and active_comments_quickfix_context.view then
		ctx = {
			gitdir = active_comments_quickfix_context.gitdir,
			root = active_comments_quickfix_context.root,
			state_path = active_comments_quickfix_context.state_path,
			view = active_comments_quickfix_context.view,
		}
	end
	if not require_active_diffview(ctx, action) or not require_repo_context(ctx, action) then
		return nil
	end
	if view == nil then
		if not view_has_valid_main_window(ctx.view) then
			active_comments_quickfix_context = nil
			notify("Open Diffview before " .. action, vim.log.levels.WARN)
			return nil
		end
	end
	if target and target.state_path and target.state_path ~= ctx.state_path then
		notify("Active Diffview review state no longer matches the quickfix list", vim.log.levels.WARN)
		return nil
	end
	return ctx
end

local function entry_for_target(ctx, target, state)
	for _, item in ipairs(review_entries(ctx.view, state)) do
		if item.path == target.path then
			return item
		end
	end
end

local function jump_to_quickfix_target(target)
	local ctx = active_quickfix_context(target, "jumping to a review comment")
	if not ctx then
		return false
	end

	local state = load_state_with_guide(ctx)
	local item = entry_for_target(ctx, target, state)
	if not item then
		notify("Comment file is not in the active Diffview: " .. tostring(target.path), vim.log.levels.WARN)
		return false
	end
	return jump_to_entry(ctx.view, item, target.line or 1) == true
end

local function comment_target_range(comment)
	local start_line, end_line = clamp_comment_range(comment, math.huge)
	return start_line or 1, end_line or 1
end

local function comment_matches_quickfix_target(comment, target)
	if normalize_file(comment.file) ~= normalize_file(target.path) then
		return false
	end
	if target.guide_id then
		return comment.guide_id == target.guide_id
	end
	if target.github_id then
		return tostring(comment.github_id or "") == target.github_id
	end

	local start_line, end_line = comment_target_range(comment)
	if start_line ~= target.line or end_line ~= target.end_line then
		return false
	end
	if target.created_at and tostring(comment.created_at or "") ~= tostring(target.created_at) then
		return false
	end
	if target.body and normalize_comment_text(comment.body) ~= target.body then
		return false
	end
	return true
end

local function find_quickfix_comment(state, target)
	for index, comment in ipairs(state.comments or {}) do
		if target.guide_id and comment.guide_id == target.guide_id then
			return comment, index
		end
		if target.github_id and tostring(comment.github_id or "") == target.github_id then
			return comment, index
		end
	end

	local indexed = state.comments and state.comments[target.state_index] or nil
	if indexed and comment_matches_quickfix_target(indexed, target) then
		return indexed, target.state_index
	end

	for index, comment in ipairs(state.comments or {}) do
		if comment_matches_quickfix_target(comment, target) then
			return comment, index
		end
	end
end

local function is_global_quickfix_win(winid)
	local ok, infos = pcall(vim.fn.getwininfo, winid)
	local info = ok and type(infos) == "table" and infos[1] or nil
	if type(info) == "table" and info.quickfix ~= nil then
		return info.quickfix == 1 and info.loclist ~= 1
	end
end

local function quickfix_winid()
	local fallback_winid = nil
	local fallback_bufnr = nil
	for _, winid in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
		local bufnr = vim.api.nvim_win_get_buf(winid)
		local is_global = is_global_quickfix_win(winid)
		if is_global then
			return winid, bufnr
		elseif is_global == nil and not fallback_winid and vim.bo[bufnr].filetype == "qf" then
			fallback_winid = winid
			fallback_bufnr = bufnr
		end
	end
	return fallback_winid, fallback_bufnr
end

local function clear_comments_quickfix_keymaps(bufnr)
	for _, lhs in ipairs({ "<CR>", "o", "d", "dd", "R", "r", "q", "<M-j>", "<M-k>" }) do
		pcall(vim.keymap.del, "n", lhs, { buffer = bufnr })
	end
	vim.b[bufnr].diffview_review_comments_qf_keymaps = nil
end

local function pass_through_quickfix_key(bufnr, lhs)
	clear_comments_quickfix_keymaps(bufnr)
	vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes(lhs, true, false, true), "n", false)
end

local function with_comments_quickfix(bufnr, lhs, fn)
	if not comments_quickfix_info() then
		pass_through_quickfix_key(bufnr, lhs)
		return
	end
	fn()
end

local function set_quickfix_cursor(index)
	local winid = quickfix_winid()
	if winid and vim.api.nvim_win_is_valid(winid) then
		pcall(vim.api.nvim_win_set_cursor, winid, { index, 0 })
	end
end

local function set_quickfix_index(info, index)
	local id = tonumber(info and info.id)
	if not id then
		return false
	end
	return pcall(vim.fn.setqflist, {}, "r", { id = id, idx = index })
end

local quickfix_comment_actions = {}

local function apply_comments_quickfix_keymaps(bufnr)
	if not vim.api.nvim_buf_is_valid(bufnr) then
		return
	end
	if not comments_quickfix_info() then
		return
	end
	local _, quickfix_bufnr = quickfix_winid()
	if bufnr ~= quickfix_bufnr then
		if vim.b[bufnr].diffview_review_comments_qf_keymaps then
			clear_comments_quickfix_keymaps(bufnr)
		end
		return
	end
	if vim.b[bufnr].diffview_review_comments_qf_keymaps then
		return
	end
	vim.b[bufnr].diffview_review_comments_qf_keymaps = true

	vim.keymap.set("n", "<CR>", function()
		with_comments_quickfix(bufnr, "<CR>", function()
			local info = comments_quickfix_info()
			local index = info and qf_cursor_index(info)
			local target = index and quickfix_target_at(info, index)
			if target and jump_to_quickfix_target(target) then
				set_quickfix_index(info, index)
				set_quickfix_cursor(index)
			end
		end)
	end, { buffer = bufnr, desc = "Jump to Diffview review comment", nowait = true, silent = true })
	vim.keymap.set("n", "o", function()
		with_comments_quickfix(bufnr, "o", function()
			local info = comments_quickfix_info()
			local index = info and qf_cursor_index(info)
			local target = index and quickfix_target_at(info, index)
			if target and jump_to_quickfix_target(target) then
				set_quickfix_index(info, index)
				set_quickfix_cursor(index)
			end
		end)
	end, { buffer = bufnr, desc = "Jump to Diffview review comment", nowait = true, silent = true })
	vim.keymap.set("n", "d", function()
		with_comments_quickfix(bufnr, "d", function()
			quickfix_comment_actions.delete()
		end)
	end, { buffer = bufnr, desc = "Delete Diffview review comment", silent = true })
	vim.keymap.set("n", "dd", function()
		with_comments_quickfix(bufnr, "dd", function()
			quickfix_comment_actions.delete()
		end)
	end, { buffer = bufnr, desc = "Delete Diffview review comment", nowait = true, silent = true })
	vim.keymap.set("n", "R", function()
		with_comments_quickfix(bufnr, "R", function()
			quickfix_comment_actions.resolve()
		end)
	end, { buffer = bufnr, desc = "Resolve/hide Diffview review comment", nowait = true, silent = true })
	vim.keymap.set("n", "r", function()
		with_comments_quickfix(bufnr, "r", function()
			M.show_comments_quickfix({ cursor = qf_cursor_index(comments_quickfix_info() or { items = {} }) })
		end)
	end, { buffer = bufnr, desc = "Refresh Diffview review comments", nowait = true, silent = true })
	vim.keymap.set("n", "q", function()
		with_comments_quickfix(bufnr, "q", function()
			vim.cmd.cclose()
		end)
	end, { buffer = bufnr, desc = "Close quickfix", nowait = true, silent = true })
	vim.keymap.set("n", "<M-j>", function()
		with_comments_quickfix(bufnr, "<M-j>", function()
			if not M.navigate_comments_quickfix(1) then
				pass_through_quickfix_key(bufnr, "<M-j>")
			end
		end)
	end, { buffer = bufnr, desc = "Next Diffview review comment", nowait = true, silent = true })
	vim.keymap.set("n", "<M-k>", function()
		with_comments_quickfix(bufnr, "<M-k>", function()
			if not M.navigate_comments_quickfix(-1) then
				pass_through_quickfix_key(bufnr, "<M-k>")
			end
		end)
	end, { buffer = bufnr, desc = "Previous Diffview review comment", nowait = true, silent = true })
end

local function open_comments_quickfix(ctx, state, cursor)
	local items, targets = comments_quickfix_items(ctx, state)
	local context = {
		root = ctx.root,
		source = COMMENTS_QF_SOURCE,
		state_path = ctx.state_path,
		targets = targets,
	}
	active_comments_quickfix_context = {
		gitdir = ctx.gitdir,
		root = ctx.root,
		state_path = ctx.state_path,
		view = ctx.view,
	}
	vim.fn.setqflist({}, "r", { context = context, items = items, title = COMMENTS_QF_TITLE })
	pcall(vim.cmd.copen)

	local winid, bufnr = quickfix_winid()
	if bufnr then
		apply_comments_quickfix_keymaps(bufnr)
	end
	if winid and #items > 0 then
		local index = math.min(math.max(tonumber(cursor) or 1, 1), #items)
		set_quickfix_index(comments_quickfix_info(), index)
		set_quickfix_cursor(index)
	end
	if #items == 0 then
		notify("No Diffview review comments")
	end
end

function M.show_comments_quickfix(opts)
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "showing review comments quickfix") then
		return
	end
	if not require_repo_context(ctx, "showing review comments quickfix") then
		return
	end

	local state = load_state_with_guide(ctx)
	open_comments_quickfix(ctx, state, opts and opts.cursor)
end

quickfix_comment_actions.delete = function()
	local info = comments_quickfix_info()
	if not info then
		return false
	end

	local index = qf_cursor_index(info)
	local target = quickfix_target_at(info, index)
	if not target then
		return false
	end

	local ctx = active_quickfix_context(target, "deleting a review comment")
	if not ctx then
		return false
	end

	local state = load_state_with_guide(ctx)
	local _, state_index = find_quickfix_comment(state, target)
	if not state_index then
		notify("Selected Diffview review comment is no longer available", vim.log.levels.WARN)
		open_comments_quickfix(ctx, state, index)
		return false
	end

	remove_comment_at_index(state, state_index)
	if save_state(ctx, state) then
		notify(("Deleted review comment at %s:%d"):format(target.path, target.line or 1))
		M.refresh_visible()
		open_comments_quickfix(ctx, load_state_with_guide(ctx), index)
		return true
	end
	return false
end

quickfix_comment_actions.resolve = function()
	local info = comments_quickfix_info()
	if not info then
		return false
	end

	local index = qf_cursor_index(info)
	local target = quickfix_target_at(info, index)
	if not target then
		return false
	end

	local ctx = active_quickfix_context(target, "resolving a review comment")
	if not ctx then
		return false
	end

	local state = load_state_with_guide(ctx)
	local _, state_index = find_quickfix_comment(state, target)
	if not state_index then
		notify("Selected Diffview review comment is no longer available", vim.log.levels.WARN)
		open_comments_quickfix(ctx, state, index)
		return false
	end

	local comment = state.comments[state_index]
	comment.resolved = true
	if review_format.is_imported_github_comment(comment) then
		comment.sync_status = "github-resolved-hidden"
	end
	comment.updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
	if save_state(ctx, state) then
		notify(("Resolved review comment at %s:%d"):format(target.path, target.line or 1))
		M.refresh_visible()
		open_comments_quickfix(ctx, load_state_with_guide(ctx), index)
		return true
	end
	return false
end

function M.navigate_comments_quickfix(direction)
	local info = comments_quickfix_info()
	if not info or #(info.items or {}) == 0 then
		return false
	end

	direction = direction == -1 and -1 or 1
	local next_index = ((qf_cursor_index(info) - 1 + direction) % #info.items) + 1
	local target = quickfix_target_at(info, next_index)
	if not target then
		return false
	end

	if not jump_to_quickfix_target(target) then
		return false
	end
	set_quickfix_index(info, next_index)
	set_quickfix_cursor(next_index)
	return true
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

	local start_index = current_index or last_index or 0
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

local function import_github_comments(ctx, pr, files)
	local raw_comments, fetch_error = fetch_github_comments(pr)
	if not raw_comments then
		notify(fetch_error, vim.log.levels.ERROR)
		return
	end

	local state = load_state_with_guide(ctx)
	local changed, stats = import_github_comments_into_state(state, raw_comments, files)
	if changed and not save_state(ctx, state) then
		return
	end

	notify(
		("GitHub import read-only for #%s: %d imported · %d updated · %d unchanged · %d skipped · %d dismissed · %d edited locally; no GitHub mutation performed"):format(
			pr.pull_number,
			stats.imported,
			stats.updated,
			stats.unchanged,
			stats.skipped,
			stats.dismissed,
			stats.edited_locally
		)
	)
	M.refresh_visible()
end

function M.import_github_comments()
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "importing GitHub review comments") then
		return
	end
	if not require_repo_context(ctx, "importing GitHub review comments") then
		return
	end

	local pr, pr_error = active_pr_context(ctx, "importing GitHub comments")
	if not pr then
		notify(pr_error, vim.log.levels.WARN)
		return
	end

	local files = diffview_file_set(ctx.view)
	if vim.tbl_isempty(files) then
		notify("No Diffview files available for GitHub comment import", vim.log.levels.WARN)
		return
	end

	import_github_comments(ctx, pr, files)
end

function M.auto_import_github_comments()
	local ctx = current_file_context()
	if not (ctx and ctx.view and ctx.state_path) then
		return
	end

	local pr = active_pr_context(ctx)
	if not pr then
		return
	end

	local key = github_import_context_key(ctx, pr)
	if auto_imported_github_contexts[key] or auto_import_scheduled_contexts[key] then
		return
	end
	auto_import_scheduled_contexts[key] = true

	vim.defer_fn(function()
		auto_import_scheduled_contexts[key] = nil
		if auto_imported_github_contexts[key] then
			return
		end

		local import_ctx = current_file_context()
		if not (import_ctx and import_ctx.view and import_ctx.state_path) then
			return
		end

		local import_pr = active_pr_context(import_ctx)
		if not import_pr or github_import_context_key(import_ctx, import_pr) ~= key then
			return
		end

		local files = diffview_file_set(import_ctx.view)
		if vim.tbl_isempty(files) then
			return
		end

		auto_imported_github_contexts[key] = true
		import_github_comments(import_ctx, import_pr, files)
	end, 150)
end

local truncate_display

local function increment_skipped(stats, reason)
	stats.skipped[reason] = (stats.skipped[reason] or 0) + 1
end

local function skipped_total(stats)
	local total = 0
	for _, count in pairs(stats.skipped or {}) do
		total = total + count
	end
	return total
end

local function posting_side(comment)
	local side = tostring(comment.side or "")
	if side == "" then
		return nil, "missing-side/legacy-anchor"
	end
	side = side:upper()
	if side == "LEFT" or side == "RIGHT" then
		return side, nil
	end
	return nil, "invalid-side"
end

local function github_post_candidates(state, files, pr)
	local candidates = {}
	local stats = { skipped = {} }
	for index, comment in ipairs(state.comments or {}) do
		if type(comment) ~= "table" then
			increment_skipped(stats, "invalid")
		else
			local source = json_value(comment.source)
			local body = vim.trim(tostring(comment.body or ""))
			local file = normalize_file(comment.file or comment.path)
			local line = positive_line(comment.line)
			local end_line = positive_line(comment.end_line) or line
			local side, side_error = posting_side(comment)
			local matches_pr, pr_skip_reason = comment_matches_pr(comment, pr)

			if source == "guide" then
				increment_skipped(stats, "guide/robot")
			elseif source == "github" then
				increment_skipped(stats, "github/imported")
			elseif source ~= nil and source ~= "manual" then
				increment_skipped(stats, "other-source")
			elseif body == "" then
				increment_skipped(stats, "empty-body")
			elseif review_format.is_file_level_comment(comment) then
				increment_skipped(stats, "file-level")
			elseif is_already_posted(comment) then
				increment_skipped(stats, "already-posted/exported")
			elseif not matches_pr then
				increment_skipped(stats, pr_skip_reason)
			elseif comment.stale == true or comment.outdated == true or comment.sync_status == "unmapped" or comment.sync_status == "stale-anchor" then
				increment_skipped(stats, "stale/unmapped")
			elseif not file or not line then
				increment_skipped(stats, "missing-anchor")
			elseif not files[file] then
				increment_skipped(stats, "not-in-current-diff")
			elseif not side then
				increment_skipped(stats, side_error)
			else
				local start_line = math.min(line, end_line)
				end_line = math.max(line, end_line)
				local start_side = tostring(comment.start_side or ""):upper()
				if start_side ~= "LEFT" and start_side ~= "RIGHT" then
					start_side = side
				end
				local payload = {
					body = body,
					line = end_line,
					path = file,
					side = side,
				}
				if start_line ~= end_line then
					payload.start_line = start_line
					payload.start_side = start_side
				end
				table.insert(candidates, {
					body = body,
					comment = comment,
					index = index,
					payload = payload,
				})
			end
		end
	end
	return candidates, stats
end

local function skipped_summary(stats)
	local reasons = vim.tbl_keys(stats.skipped or {})
	table.sort(reasons)
	local parts = {}
	for _, reason in ipairs(reasons) do
		table.insert(parts, ("%s=%d"):format(reason, stats.skipped[reason]))
	end
	return #parts > 0 and table.concat(parts, " · ") or "none"
end

local function create_github_review(pr, candidates)
	if vim.fn.executable("gh") ~= 1 then
		return nil, "gh CLI is unavailable; install gh and run gh auth login before posting GitHub comments"
	end
	if not pr.head_oid or pr.head_oid == "" then
		return nil, "missing pinned PR head SHA; reopen with :DiffviewPrOpen before posting GitHub comments"
	end

	local comments = {}
	for _, candidate in ipairs(candidates) do
		table.insert(comments, candidate.payload)
	end
	local payload = vim.fn.json_encode({
		body = "Diffview local review comments.",
		commit_id = pr.head_oid,
		event = "COMMENT",
		comments = comments,
	})
	local endpoint = ("repos/%s/%s/pulls/%s/reviews"):format(pr.owner, pr.repo, pr.pull_number)
	local output = vim.fn.systemlist({ "gh", "api", "--method", "POST", endpoint, "--input", "-" }, payload)
	if vim.v.shell_error ~= 0 then
		local details = vim.trim(table.concat(output or {}, "\n"))
		return nil, details ~= "" and details or "gh api review creation failed"
	end

	local ok, decoded = pcall(vim.fn.json_decode, table.concat(output or {}, "\n"))
	return ok and type(decoded) == "table" and decoded or {}
end

local function same_pr_head_context(left, right)
	if not (left and right) then
		return false
	end
	if tostring(left.pull_number or "") ~= tostring(right.pull_number or "") then
		return false
	end
	if tostring(left.owner or ""):lower() ~= tostring(right.owner or ""):lower() then
		return false
	end
	if tostring(left.repo or ""):lower() ~= tostring(right.repo or ""):lower() then
		return false
	end
	if tostring(left.head_oid or ""):lower() ~= tostring(right.head_oid or ""):lower() then
		return false
	end
	return tostring(left.head_oid or "") ~= ""
end

local function mark_candidates_posted(pr, candidates, response)
	local posted_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
	local review_id = string_id(json_value(response.id))
	local review_url = json_value(response.html_url) or json_value(response.url)
	for _, candidate in ipairs(candidates) do
		local comment = candidate.comment
		local payload = candidate.payload
		comment.source = "manual"
		comment.sync_status = "posted"
		comment.github_posted_at = posted_at
		comment.github_posted_pr = tostring(pr.pull_number)
		comment.github_body = payload.body
		comment.github_line = payload.line
		comment.github_path = payload.path
		comment.github_side = payload.side
		comment.github_start_line = payload.start_line
		comment.github_start_side = payload.start_side
		comment.github_review_id = review_id
		comment.github_review_url = review_url
		comment.updated_at = posted_at
	end
end

local function post_confirm_preview_lines(pr, candidates, stats)
	local lines = {
		("Post %d local Diffview comment(s) to PR #%s"):format(#candidates, pr.pull_number),
	}
	if pr.title and pr.title ~= "" then
		table.insert(lines, "Title: " .. pr.title)
	end
	if pr.url and pr.url ~= "" then
		table.insert(lines, "URL: " .. pr.url)
	end
	table.insert(lines, "Mode: one REST create-review call with event=COMMENT")
	table.insert(lines, "Skipped: " .. skipped_summary(stats))
	table.insert(lines, "")
	table.insert(lines, "Press p to post. Press q or Esc to cancel.")
	table.insert(lines, "")
	for _, candidate in ipairs(candidates) do
		local payload = candidate.payload
		local range = payload.start_line and line_range_label(payload.start_line, payload.line) or line_range_label(payload.line, payload.line)
		local preview = truncate_display(comment_preview({ body = candidate.body }), 80)
		table.insert(lines, ("- %s:%s %s — %s"):format(payload.path, range, payload.side, preview))
	end
	return lines
end

local function post_github_review(ctx, pr, state, candidates, stats)
	if github_post_in_progress then
		notify("A GitHub comment post is already in progress", vim.log.levels.WARN)
		return
	end

	local active_pr, active_error = active_pr_context(ctx, "posting GitHub comments")
	if not same_pr_head_context(active_pr, pr) then
		notify(active_error or "Active PR context no longer matches the pinned PR head; no GitHub post was made", vim.log.levels.ERROR)
		return
	end

	github_post_in_progress = true
	local ok, response, post_error = pcall(create_github_review, pr, candidates)
	github_post_in_progress = false
	if not ok then
		post_error = response
		response = nil
	end
	if not response then
		notify(
			("GitHub post failed for #%s: posted=0 · skipped=%d · failed=%d · %s"):format(
				pr.pull_number,
				skipped_total(stats),
				#candidates,
				post_error
			),
			vim.log.levels.ERROR
		)
		return
	end

	mark_candidates_posted(pr, candidates, response)
	if not save_state(ctx, state) then
		notify(
			("REMOTE POST SUCCEEDED for #%s, but local state was not marked. Rerunning may duplicate %d posted comment(s)."):format(
				pr.pull_number,
				#candidates
			),
			vim.log.levels.ERROR
		)
		return
	end

	notify(
		("Posted %d local Diffview comment(s) to #%s · skipped=%d · failed=0"):format(
			#candidates,
			pr.pull_number,
			skipped_total(stats)
		)
	)
	M.refresh_visible()
end

local function open_post_confirmation(ctx, pr, state, candidates, stats)
	post_confirmation_open = true

	local width = math.min(math.max(64, math.floor(vim.o.columns * 0.68)), math.max(64, vim.o.columns - 4))
	local lines = post_confirm_preview_lines(pr, candidates, stats)
	local height = math.min(math.max(8, #lines), math.max(8, vim.o.lines - 4))
	local bufnr = vim.api.nvim_create_buf(false, true)
	vim.api.nvim_buf_set_lines(bufnr, 0, -1, false, lines)
	vim.bo[bufnr].bufhidden = "wipe"
	vim.bo[bufnr].filetype = "markdown"
	vim.bo[bufnr].modifiable = false

	local winid = vim.api.nvim_open_win(bufnr, true, {
		border = "rounded",
		col = math.max(math.floor((vim.o.columns - width) / 2), 0),
		height = height,
		relative = "editor",
		row = math.max(math.floor((vim.o.lines - height) / 2), 0),
		style = "minimal",
		title = " Confirm GitHub Comment Post ",
		title_pos = "center",
		width = width,
	})
	vim.wo[winid].cursorline = true

	local function close_popup()
		post_confirmation_open = false
		if vim.api.nvim_win_is_valid(winid) then
			pcall(vim.api.nvim_win_close, winid, true)
		end
		if vim.api.nvim_buf_is_valid(bufnr) then
			pcall(vim.api.nvim_buf_delete, bufnr, { force = true })
		end
	end
	vim.api.nvim_create_autocmd({ "BufDelete", "BufWipeout" }, {
		buffer = bufnr,
		once = true,
		callback = function()
			post_confirmation_open = false
		end,
	})

	vim.keymap.set("n", "q", close_popup, { buffer = bufnr, nowait = true, silent = true })
	vim.keymap.set("n", "<Esc>", close_popup, { buffer = bufnr, nowait = true, silent = true })
	vim.keymap.set("n", "p", function()
		close_popup()
		post_github_review(ctx, pr, state, candidates, stats)
	end, { buffer = bufnr, nowait = true, silent = true })
end

function M.post_github_comments()
	if post_confirmation_open then
		notify("A GitHub comment post confirmation is already open", vim.log.levels.WARN)
		return
	end
	if github_post_in_progress then
		notify("A GitHub comment post is already in progress", vim.log.levels.WARN)
		return
	end

	local ctx = current_file_context()
	if not require_active_diffview(ctx, "posting GitHub review comments") then
		return
	end
	if not require_repo_context(ctx, "posting GitHub review comments") then
		return
	end

	local pr, pr_error = active_pr_context(ctx, "posting GitHub comments")
	if not pr then
		notify(pr_error, vim.log.levels.WARN)
		return
	end

	local files = diffview_file_set(ctx.view)
	if vim.tbl_isempty(files) then
		notify("No Diffview files available for GitHub comment posting", vim.log.levels.WARN)
		return
	end

	local state = load_state_with_guide(ctx)
	local candidates, stats = github_post_candidates(state, files, pr)
	if #candidates == 0 then
		notify(("No eligible local Diffview comments to post · skipped=%d (%s)"):format(skipped_total(stats), skipped_summary(stats)), vim.log.levels.WARN)
		return
	end

	open_post_confirmation(ctx, pr, state, candidates, stats)
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

local function guide_file_for_path(guide, path)
	path = normalize_file(path)
	if not (guide and path) then
		return nil
	end

	local by_path = type(guide.files_by_path) == "table" and guide.files_by_path[path] or nil
	if by_path then
		return by_path
	end

	for _, file in ipairs(guide.files or {}) do
		if normalize_file(file.path) == path then
			return file
		end
	end
end

local function append_guide_list_item(lines, prefix, text)
	local item_lines = split_comment_text(text)
	for index, line in ipairs(item_lines) do
		if index == 1 then
			table.insert(lines, prefix .. line)
		else
			table.insert(lines, "  " .. line)
		end
	end
end

local function guide_popup_lines(path, file)
	local lines = {
		"# Diffview review guide",
		"",
		("**File:** `%s`"):format(path),
		"",
	}
	local item_count = 0

	if #(file.notes or {}) > 0 then
		table.insert(lines, "## File notes")
		for _, note in ipairs(file.notes or {}) do
			append_guide_list_item(lines, "- ", note)
			item_count = item_count + 1
		end
		table.insert(lines, "")
	end

	local suggestion_header_added = false
	for _, suggestion in ipairs(file.suggestions or {}) do
		if not suggestion.line then
			if not suggestion_header_added then
				table.insert(lines, "## File-level suggestions")
				suggestion_header_added = true
			end

			local severity = review_format.severity_label(suggestion.severity)
			local marker = review_format.severity_emoji(severity)
			append_guide_list_item(lines, ("- %s **%s:** "):format(marker, severity), suggestion.body)
			if suggestion.why and vim.trim(tostring(suggestion.why)) ~= "" then
				append_guide_list_item(lines, "  - **Why:** ", suggestion.why)
			end
			item_count = item_count + 1
		end
	end

	return lines, item_count
end

function M.show_guide_popup()
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "showing review guide") or not require_repo_context(ctx, "showing review guide") then
		return
	end
	if not ctx.file then
		notify("Move to a Diffview file before showing the review guide", vim.log.levels.WARN)
		return
	end

	local _, guide = load_state_with_guide(ctx)
	if not guide then
		notify("No active Diffview review guide", vim.log.levels.WARN)
		return
	end

	local guide_file = guide_file_for_path(guide, ctx.file)
	if not guide_file then
		notify("No review guide context for " .. ctx.file, vim.log.levels.INFO)
		return
	end

	local lines, item_count = guide_popup_lines(ctx.file, guide_file)
	if item_count == 0 then
		notify("No file-level guide notes or suggestions for " .. ctx.file, vim.log.levels.INFO)
		return
	end

	local max_width = math.max(20, vim.o.columns - 4)
	local width = math.min(math.max(52, math.floor(vim.o.columns * 0.62)), max_width)
	local max_height = math.max(6, vim.o.lines - 4)
	local height = math.min(math.max(6, #lines), max_height)
	local bufnr = vim.api.nvim_create_buf(false, true)
	vim.api.nvim_buf_set_lines(bufnr, 0, -1, false, lines)
	vim.bo[bufnr].bufhidden = "wipe"
	vim.bo[bufnr].filetype = "markdown"
	vim.bo[bufnr].modifiable = false

	local winid = vim.api.nvim_open_win(bufnr, true, {
		border = "rounded",
		col = math.max(math.floor((vim.o.columns - width) / 2), 0),
		height = height,
		relative = "editor",
		row = math.max(math.floor((vim.o.lines - height) / 2), 0),
		style = "minimal",
		title = " Diffview Review Guide ",
		title_pos = "center",
		width = width,
	})
	vim.wo[winid].wrap = true

	local function close_popup()
		if vim.api.nvim_win_is_valid(winid) then
			pcall(vim.api.nvim_win_close, winid, true)
		end
		if vim.api.nvim_buf_is_valid(bufnr) then
			pcall(vim.api.nvim_buf_delete, bufnr, { force = true })
		end
	end

	vim.keymap.set("n", "q", close_popup, { buffer = bufnr, nowait = true, silent = true })
	vim.keymap.set("n", "<Esc>", close_popup, { buffer = bufnr, nowait = true, silent = true })
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

truncate_display = function(value, width)
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

local function status_markdown_continuation_prefix(line)
	return line:match("^(%s*[-*+]%s+%[[xX ]%]%s+)")
		or line:match("^(%s*[-*+]%s+)")
		or line:match("^(%s*%d+[.)]%s+)")
		or line:match("^(%s*>%s*)")
		or line:match("^%s*")
		or ""
end

local function wrap_status_body_line(value, width)
	local text = tostring(value or "")
	if vim.trim(text) == "" then
		return { "" }
	end

	width = math.max(width, 1)
	if review_format.display_width(text) <= width then
		return { text }
	end

	local first_prefix = text:match("^%s*") or ""
	local continuation_prefix = string.rep(" ", review_format.display_width(status_markdown_continuation_prefix(text)))
	local lines = {}
	local line = first_prefix
	local line_has_text = false

	for word in text:sub(#first_prefix + 1):gmatch("%S+") do
		local pending = word
		while pending ~= "" do
			local separator = line_has_text and " " or ""
			if review_format.display_width(line .. separator .. pending) <= width then
				line = line .. separator .. pending
				line_has_text = true
				pending = ""
			elseif line_has_text then
				table.insert(lines, line)
				line = continuation_prefix
				line_has_text = false
			else
				local piece_width = math.max(width - review_format.display_width(line), 1)
				local piece, rest = take_display_prefix(pending, piece_width)
				table.insert(lines, line .. piece)
				pending = rest
				line = continuation_prefix
				line_has_text = false
			end
		end
	end

	if line_has_text then
		table.insert(lines, line)
	end
	return lines
end

local function wrap_status_body(value, width)
	local text = tostring(value or ""):gsub("\r\n", "\n"):gsub("\r", "\n")
	local lines = {}
	for _, body_line in ipairs(vim.split(text, "\n", { plain = true })) do
		for _, wrapped_line in ipairs(wrap_status_body_line(body_line, width)) do
			table.insert(lines, wrapped_line)
		end
	end
	return lines
end

local function add_pr_description_status(rows, ctx, width)
	local context = active_guide_context
	if not context or not context.pr_number then
		return
	end
	if context.repo and ctx and ctx.root and normalize_dir(context.repo) ~= ctx.root then
		return
	end
	if not active_pr_context_matches_view(context, ctx) then
		return
	end

	local pr, pr_error = active_pr_context(ctx, "showing the PR description")
	local title = status_row()
	add_status_text(title, "PR:", "DiffviewReviewStatusHeader")
	if not pr then
		add_status_text(title, " " .. pr_error, "DiffviewReviewStatusMuted")
		table.insert(rows, title)
		table.insert(rows, status_row())
		return
	end

	local description = pr

	local heading = description.title and description.title ~= "" and description.title or "Untitled PR"
	add_status_text(title, (" #%s · "):format(pr.pull_number), "DiffviewReviewStatusMuted")
	add_status_text(title, truncate_display(heading, width - review_format.display_width(title.text)), "DiffviewReviewStatusFile")
	table.insert(rows, title)

	if description.url and description.url ~= "" then
		local url = status_row()
		add_status_text(url, "  ")
		add_status_text(url, truncate_display(description.url, width - 2), "DiffviewReviewStatusMuted")
		table.insert(rows, url)
	end

	local body = tostring(description.body or "")
	if vim.trim(body) == "" then
		local row = status_row()
		add_status_text(row, "  No PR description", "DiffviewReviewStatusMuted")
		table.insert(rows, row)
	else
		local header = status_row()
		add_status_text(header, "  PR Description:", "DiffviewReviewStatusMuted")
		table.insert(rows, header)

		local body_indent = "  "
		local body_lines = wrap_status_body(body, width - review_format.display_width(body_indent))
		for _, line in ipairs(body_lines) do
			local row = status_row()
			if line ~= "" then
				add_status_text(row, body_indent)
				add_status_text(row, line, "DiffviewReviewStatusMuted")
			end
			table.insert(rows, row)
		end
	end
	table.insert(rows, status_row())
end

local function add_review_summary(rows, counts)
	local row = status_row()
	add_status_text(row, "Review:", "DiffviewReviewStatusHeader")
	add_status_text(
		row,
		(" %d files · %d reviewed · %d unreviewed · %d comments · %s %d · %s %d"):format(
			counts.files,
			counts.reviewed,
			counts.unreviewed,
			counts.comments,
			GITHUB_MARKER,
			counts.github,
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

	if guide then
		local source = guide.source_path and vim.fn.fnamemodify(guide.source_path, ":~") or "unknown"
		local source_prefix = "  Source: "
		local source_width = width - review_format.display_width(source_prefix)
		if review_format.display_width(source) > source_width then
			source = vim.fn.pathshorten(source)
		end
		local source_row = status_row()
		add_status_text(source_row, source_prefix, "DiffviewReviewStatusMuted")
		add_status_text(
			source_row,
			truncate_display(source, source_width),
			"DiffviewReviewStatusGuideInfo"
		)
		table.insert(rows, source_row)

		local guide_counts = ("  Guide: schema %s · summary %s · change_map %d · high %d · validate %d · strategy %d · files %d"):format(
			guide.schema_version or "?",
			guide.summary and guide.summary ~= "" and "yes" or "no",
			#(guide.change_map or {}),
			#(guide.high_risk or {}),
			#(guide.validation_focus or {}),
			#(guide.review_strategy or {}),
			#(guide.files or {})
		)
		local counts_row = status_row()
		add_status_text(counts_row, truncate_display(guide_counts, width), "DiffviewReviewStatusMuted")
		table.insert(rows, counts_row)
	end

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
		{ hl = "DiffviewReviewStatusGuideInfo", items = guide and guide.review_strategy or {}, label = "Strategy" },
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
	local is_github = review_format.is_imported_github_comment(comment)
	local label
	if is_guide or is_github then
		label = review_format.is_file_level_comment(comment) and "File-level"
			or range_label(entry.start_line, entry.end_line)
	else
		label = line_range_label(entry.start_line, entry.end_line)
	end
	local row = status_row({ item = item, line = entry.start_line })
	local indent = "    "
	add_status_text(row, indent)

	if is_github then
		local author = comment.author and (" @" .. comment.author) or ""
		local status = github_status_label(comment)
		local status_text = status and (" [" .. status .. "]") or ""
		local prefix = GITHUB_MARKER .. " " .. label .. author .. status_text .. ": "
		add_status_text(row, GITHUB_MARKER, "DiffviewReviewStatusGithub")
		add_status_text(row, " " .. label .. author .. status_text .. ": ", "DiffviewReviewStatusMuted")
		add_status_text(
			row,
			truncate_display(comment_preview(comment), width - review_format.display_width(indent .. prefix)),
			"DiffviewReviewStatusMuted"
		)
		return row
	end

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
	local counts = { github = 0, guide = 0, manual = 0, total = #comments }
	for _, entry in ipairs(comments) do
		if review_format.is_guide_comment(entry.comment) then
			counts.guide = counts.guide + 1
		elseif review_format.is_imported_github_comment(entry.comment) then
			counts.github = counts.github + 1
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
	if counts.github > 0 then
		if suffix_width > 0 then
			suffix_width = suffix_width + 2
		end
		suffix_width = suffix_width + review_format.display_width(GITHUB_MARKER .. counts.github)
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
		if counts.github > 0 then
			if counts.guide > 0 then
				add_status_text(row, "  ")
			end
			add_status_text(row, GITHUB_MARKER .. counts.github, "DiffviewReviewStatusGithub")
		end
		if counts.manual > 0 then
			if counts.guide > 0 or counts.github > 0 then
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
	local markdown_lines = read_nonempty_file(active_guide_markdown_path(ctx))
	if markdown_lines then
		local width = math.max(48, math.floor(vim.o.columns * 0.62))
		width = math.min(width, math.max(48, vim.o.columns - 4))
		local height = math.max(10, math.floor(vim.o.lines * 0.82))
		height = math.min(height, math.max(10, #markdown_lines))
		local bufnr = vim.api.nvim_create_buf(false, true)
		vim.api.nvim_buf_set_lines(bufnr, 0, -1, false, markdown_lines)
		vim.bo[bufnr].bufhidden = "wipe"
		vim.bo[bufnr].filetype = "markdown"
		vim.bo[bufnr].modifiable = false

		local winid = vim.api.nvim_open_win(bufnr, true, {
			border = "rounded",
			col = math.max(math.floor((vim.o.columns - width) / 2), 0),
			height = height,
			relative = "editor",
			row = math.max(math.floor((vim.o.lines - height) / 2), 0),
			style = "minimal",
			title = " Diffview Review Guide ",
			title_pos = "center",
			width = width,
		})
		vim.wo[winid].wrap = true

		local function close_popup()
			if vim.api.nvim_win_is_valid(winid) then
				pcall(vim.api.nvim_win_close, winid, true)
			end
			if vim.api.nvim_buf_is_valid(bufnr) then
				pcall(vim.api.nvim_buf_delete, bufnr, { force = true })
			end
		end

		vim.keymap.set("n", "q", close_popup, { buffer = bufnr, nowait = true, silent = true })
		vim.keymap.set("n", "<Esc>", close_popup, { buffer = bufnr, nowait = true, silent = true })
		return
	end

	M.show_review_dashboard()
end

function M.show_review_dashboard()
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "showing review dashboard") or not require_repo_context(ctx, "showing review dashboard") then
		return
	end
	local state, guide = load_state_with_guide(ctx)
	local entries = order_review_entries_by_guide(review_entries(ctx.view, state), guide)
	local width = math.max(48, math.floor(vim.o.columns * 0.58))
	width = math.min(width, math.max(48, vim.o.columns - 4))
	local content_width = math.max(40, width - 2)
	local rows = {}
	local line_to_action = {}
	local comments_by_path = {}
	local counts = { comments = 0, files = #entries, github = 0, guide = 0, reviewed = 0, unreviewed = 0 }

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
		counts.github = counts.github + file_counts.github
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
	add_pr_description_status(rows, ctx, content_width)

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
	-- <leader>gda/gdd/<leader>gdr add/delete/resolve comments, <leader>gdv toggles reviewed,
	-- <leader>gdg opens file guide context,
	-- <leader>gds opens the review comment quickfix, <leader>gdS opens the detailed guide/status,
	-- <leader>gdU opens the reviewed/unreviewed dashboard,
	-- <leader>gdp posts after confirmation,
	-- <leader>gd[/] jump comments,
	-- and <Tab>/<S-Tab> move only through unreviewed files.
	return {
		view = {
			{ "n", "<leader>gda", M.add_comment, { desc = "[G]it [D]iffview [A]dd Review Comment" } },
			{ "x", "<leader>gda", M.add_comment_visual, { desc = "[G]it [D]iffview [A]dd Review Comment" } },
			{ "n", "<leader>gdd", M.delete_comment, { desc = "[G]it [D]iffview [D]elete Review Comment" } },
			{ "n", "<leader>gdr", M.resolve_comment, { desc = "[G]it [D]iffview [R]esolve/Hide Review Comment" } },
			{ "n", "<leader>gdg", M.show_guide_popup, { desc = "[G]it [D]iffview [G]uide" } },
			{ "n", "<leader>gdv", M.toggle_file_viewed, { desc = "[G]it [D]iffview Toggle File Reviewed" } },
			{ "n", "<leader>gds", M.show_comments_quickfix, { desc = "[G]it [D]iffview Review Comment Quickfix" } },
			{ "n", "<leader>gdS", M.show_status, { desc = "[G]it [D]iffview Detailed Review Status" } },
			{ "n", "<leader>gdU", M.show_review_dashboard, { desc = "[G]it [D]iffview Viewed/[U]nviewed Dashboard" } },
			{ "n", "<leader>gdp", M.post_github_comments, { desc = "[G]it [D]iffview [P]ost GitHub Comments" } },
			{ "n", "<leader>gd]", function() M.next_review_comment(1) end, { desc = "Next Diffview review comment" } },
			{ "n", "<leader>gd[", function() M.next_review_comment(-1) end, { desc = "Previous Diffview review comment" } },
			{ "n", "<Tab>", function() M.next_unviewed_file(1) end, { desc = "Next unreviewed Diffview file" } },
			{ "n", "<S-Tab>", function() M.next_unviewed_file(-1) end, { desc = "Previous unreviewed Diffview file" } },
		},
		file_panel = {
			{ "n", "<leader>gdg", M.show_guide_popup, { desc = "[G]it [D]iffview [G]uide" } },
			{ "n", "<leader>gdv", M.toggle_file_viewed, { desc = "[G]it [D]iffview Toggle File Reviewed" } },
			{ "n", "<leader>gds", M.show_comments_quickfix, { desc = "[G]it [D]iffview Review Comment Quickfix" } },
			{ "n", "<leader>gdS", M.show_status, { desc = "[G]it [D]iffview Detailed Review Status" } },
			{ "n", "<leader>gdU", M.show_review_dashboard, { desc = "[G]it [D]iffview Viewed/[U]nviewed Dashboard" } },
			{ "n", "<leader>gdp", M.post_github_comments, { desc = "[G]it [D]iffview [P]ost GitHub Comments" } },
			{ "n", "<leader>gd]", function() M.next_review_comment(1) end, { desc = "Next Diffview review comment" } },
			{ "n", "<leader>gd[", function() M.next_review_comment(-1) end, { desc = "Previous Diffview review comment" } },
			{ "n", "<Tab>", function() M.next_unviewed_file(1) end, { desc = "Next unreviewed Diffview file" } },
			{ "n", "<S-Tab>", function() M.next_unviewed_file(-1) end, { desc = "Previous unreviewed Diffview file" } },
		},
	}
end

function M.setup()
	vim.fn.sign_define("DiffviewReviewComment", { text = COMMENT_MARKER, texthl = "DiffviewReviewCommentSign" })
	vim.fn.sign_define("DiffviewReviewGithub", { text = GITHUB_MARKER, texthl = "DiffviewReviewGithub" })
	for _, sign_name in ipairs(review_format.GUIDE_SIGN_NAMES) do
		vim.fn.sign_define(sign_name, { text = GUIDE_MARKER, texthl = sign_name })
	end
	vim.fn.sign_define("DiffviewReviewFileReviewed", { text = "✓", texthl = "DiffviewReviewPanelViewed" })
	vim.fn.sign_define("DiffviewReviewFileUnreviewed", { text = "○", texthl = "DiffviewReviewPanelUnviewed" })

	local group = vim.api.nvim_create_augroup("DiffviewReview", { clear = true })
	vim.api.nvim_create_autocmd("User", {
		group = group,
		pattern = { "DiffviewViewPostLayout", "DiffviewDiffBufWinEnter" },
		callback = function(event)
			vim.defer_fn(function()
				M.apply_highlights()
				M.refresh_visible()
				if event.match == "DiffviewViewPostLayout" then
					M.jump_to_initial_guide_file()
					M.auto_import_github_comments()
				end
				for _, winid in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
					if vim.api.nvim_win_is_valid(winid) then
						apply_buffer_keymaps(vim.api.nvim_win_get_buf(winid))
					end
				end
			end, 100)
		end,
	})
	vim.api.nvim_create_autocmd("FileType", {
		group = group,
		pattern = "qf",
		callback = function(event)
			apply_comments_quickfix_keymaps(event.buf)
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
	vim.api.nvim_create_user_command("DiffviewReviewResolveComment", M.resolve_comment, {
		range = true,
		force = true,
		desc = "Resolve or hide a Diffview review comment at the current line",
	})
	vim.api.nvim_create_user_command("DiffviewReviewToggleViewed", M.toggle_file_viewed, {
		force = true,
		desc = "Toggle the current Diffview file reviewed state",
	})
	vim.api.nvim_create_user_command("DiffviewReviewStatus", M.show_status, {
		force = true,
		desc = "Show the detailed Diffview review guide, falling back to the review dashboard",
	})
	vim.api.nvim_create_user_command("DiffviewReviewDashboard", M.show_review_dashboard, {
		force = true,
		desc = "Show the Diffview viewed/unviewed review dashboard",
	})
	vim.api.nvim_create_user_command("DiffviewReviewCommentsQf", M.show_comments_quickfix, {
		force = true,
		desc = "Show Diffview review comments in quickfix",
	})
	vim.api.nvim_create_user_command("DiffviewReviewGuide", M.show_guide_popup, {
		force = true,
		desc = "Show current-file Diffview review guide context",
	})
	vim.api.nvim_create_user_command("DiffviewReviewImportGithubComments", M.import_github_comments, {
		force = true,
		desc = "Import GitHub PR review comments into local Diffview state",
	})
	vim.api.nvim_create_user_command("DiffviewReviewPostGithubComments", M.post_github_comments, {
		force = true,
		desc = "Post eligible local Diffview comments to the active GitHub PR",
	})
end

return M
