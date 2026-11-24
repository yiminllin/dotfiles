local M = {}

local review_format = require("utils.diffview_review_format")
local review_state = require("utils.diffview_review_state")
local guide_view = require("utils.diffview_review_guide")
local review_panel = require("utils.diffview_review_panel")
local ownership_scope = require("utils.diffview_review_scope")
local chunk_workspace = require("utils.diffview_review_chunk_workspace")

local NS = vim.api.nvim_create_namespace("diffview_review")
local SIGN_GROUP = "diffview_review"
local COMMENT_MARKER = review_format.COMMENT_MARKER
local GUIDE_MARKER = review_format.GUIDE_MARKER
local GITHUB_MARKER = review_format.GITHUB_MARKER
local active_guide_context = nil
local auto_imported_github_contexts = {}
local auto_import_scheduled_contexts = {}

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
		view = view,
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

local function focus_diffview_entry(view, entry, line, side)
	local winid = nil
	if side then
		for _, candidate in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
			local file = entry_file_for_buffer(entry, vim.api.nvim_win_get_buf(candidate))
			if file and (file.symbol == "a" and "LEFT" or "RIGHT") == side then
				winid = candidate
				break
			end
		end
	end
	winid = winid or diffview_entry_main_winid(view, entry)
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

local function current_file_context()
	local view = current_view()
	local ctx = repo_context(view)
	if not ctx then
		return { view = view }
	end

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

function M._anchor_git_identity(ctx, file, side)
	local commit_sha = nil
	if active_guide_context then
		commit_sha = side == "LEFT" and active_guide_context.base_oid or active_guide_context.head_oid
	end
	if not commit_sha or not ctx or not ctx.root or not file then
		return commit_sha, nil
	end

	local output = vim.fn.systemlist({ "git", "-C", ctx.root, "rev-parse", commit_sha .. ":" .. file })
	local blob_sha = vim.v.shell_error == 0 and vim.trim(output[1] or "") or nil
	return commit_sha, blob_sha ~= "" and blob_sha or nil
end

function M._capture_comment_anchor(ctx, file, side, line, end_line, bufnr)
	bufnr = bufnr or vim.api.nvim_get_current_buf()
	if not side or not vim.api.nvim_buf_is_valid(bufnr) then
		return nil
	end
	local lines = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)
	local commit_sha, blob_sha = M._anchor_git_identity(ctx, file, side)
	return require("utils.diffview_review_anchor").capture(lines, {
		blob_sha = blob_sha,
		commit_sha = commit_sha,
		end_line = end_line,
		line = line,
		path = file,
		side = side,
	})
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
	return guide_view.load(active_guide_path(ctx), active_guide_context)
end

local normalize_comment_text = review_format.normalize_comment_text
local comment_preview = review_format.comment_preview
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
		suggestion.side == "LEFT" and ("LEFT:" .. line_key) or line_key,
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
	for _, key in ipairs({ "line", "end_line", "guide_retired" }) do
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
				side = suggestion.side or "RIGHT",
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
				if comment.resolved or #(comment.replies or {}) > 0 or comment.agent_request_id then
					if not comment.guide_retired then
						comment.guide_retired = true
						changed = true
					end
				else
					table.remove(state.comments, index)
					changed = true
				end
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
	return table.concat({ ctx.root or "", pr.owner or "", pr.repo or "", pr.pull_number or "", pr.head_oid or "" }, "\n")
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

local function decode_github_comments(output)
	local text = table.concat(output or {}, "\n")
	local ok, decoded = pcall(vim.fn.json_decode, text)
	if ok and type(decoded) == "table" then
		return flatten_github_comment_pages(decoded)
	end
	return nil, "gh api returned invalid JSON"
end

local function fetch_github_comments(pr)
	if vim.fn.executable("gh") ~= 1 then
		return nil, "gh CLI is unavailable; install gh and run gh auth login before importing GitHub comments"
	end

	if pr.head_oid then
		local head = vim.fn.systemlist({ "gh", "api",
			("repos/%s/%s/pulls/%s"):format(pr.owner, pr.repo, pr.pull_number), "--jq", ".head.sha" })
		if vim.v.shell_error ~= 0 or vim.trim(head[1] or "") ~= pr.head_oid then
			return nil, "Cannot verify GitHub comments against this revision; reopen review to update the PR head"
		end
	end
	local endpoint = ("repos/%s/%s/pulls/%s/comments?per_page=100"):format(pr.owner, pr.repo, pr.pull_number)
	local output = vim.fn.systemlist({ "gh", "api", "--paginate", "--slurp", endpoint })
	if vim.v.shell_error ~= 0 then
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

local function normalize_github_comment(raw, files, head_oid)
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
		github_head_oid = head_oid,
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
		comment.line = start_line or current_line
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

local function import_github_comments_into_state(state, raw_comments, files, head_oid)
	state.comments = state.comments or {}
	state.dismissed_github_comments = state.dismissed_github_comments or {}
	local stats = { dismissed = 0, edited_locally = 0, imported = 0, skipped = 0, unchanged = 0, updated = 0 }
	local index_by_id = comment_index_by_github_id(state)
	local changed = false

	for _, raw in ipairs(raw_comments or {}) do
		local comment = normalize_github_comment(raw, files, head_oid)
		if comment then
			changed = apply_imported_github_comment(state, index_by_id, comment, stats) or changed
		else
			stats.skipped = stats.skipped + 1
		end
	end

	return changed, stats
end

local function is_hidden_comment(comment)
	return comment.resolved == true or comment.local_resolved == true or comment.sync_status == "github-resolved-hidden"
		or (comment.source == "guide" and guide_view.cache and comment.guide_path == guide_view.cache.path and not guide_view.cache.guide)
		or (comment.source == "github" and active_guide_context and active_guide_context.head_oid
			and comment.github_head_oid ~= active_guide_context.head_oid)
end

local function load_state_with_guide(ctx)
	local state = load_state(ctx)
	local guide = load_active_guide(ctx)
	local workspace
	local can_sync = ctx.view and not (ctx.view.closing and ctx.view.closing:check())
	if can_sync then
		workspace = chunk_workspace.sync(
			ctx,
			guide,
			active_guide_context and active_pr_context_matches_view(active_guide_context, ctx) and active_guide_context or nil
		)
	end
	local discussion_guide = workspace and workspace.plan and workspace.error and workspace.guide or guide
	local can_import = can_sync or not (guide and guide.chunks and #guide.chunks > 0)
	if can_import and import_guide_comments(state, discussion_guide) then
		save_state(ctx, state)
	end
	if can_sync then
		ownership_scope.apply_order(ctx.view, discussion_guide)
	end
	return state, discussion_guide
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
	if start_line < 1 or end_line > line_count then
		return nil, nil
	end
	return start_line, end_line
end

local function sorted_file_comments(state, file, line_count)
	local comments = {}
	file = normalize_file(file)
	for index, comment in ipairs(state.comments or {}) do
		if normalize_file(comment.file) == file and not is_hidden_comment(comment) then
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
			and (not opts or not opts.side or review_format.is_file_level_comment(comment)
				or (comment.side or "RIGHT") == opts.side)
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

local function ensure_review_scope(ctx, state)
	local view = ctx.view
	if view.review_scope then
		return view.review_scope
	end
	local head = active_guide_context
			and active_pr_context_matches_view(active_guide_context, ctx)
			and active_guide_context.head_oid
		or nil
	local scope = ownership_scope.attach(view, ctx.root, head)
	if state.ownership_filter == "phoenix" then
		local ok, err = ownership_scope.set(scope, true)
		if ok then
			view:update_files(function()
				vim.schedule(M.refresh_visible)
			end)
		else
			state.ownership_filter = "all"
			save_state(ctx, state)
			notify(err, vim.log.levels.WARN)
		end
	end
	return scope
end

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

local function jump_to_entry(view, item, line, side)
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

	local focus_ok = focus_diffview_entry(view, item.entry, line, side)
	if not focus_ok then
		notify("Could not focus " .. item.path, vim.log.levels.WARN)
		return false
	end
	if line then
		vim.defer_fn(function()
			focus_diffview_entry(view, item.entry, line, side)
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

local function refresh_buffer(bufnr, file, state, winid, side, include_file_level, catalog)
	if not file or not vim.api.nvim_buf_is_valid(bufnr) then
		return
	end
	vim.api.nvim_buf_clear_namespace(bufnr, NS, 0, -1)
	vim.fn.sign_unplace(SIGN_GROUP, { buffer = bufnr })
	local count = vim.api.nvim_buf_line_count(bufnr)
	if catalog and side then
		vim.wo[winid].signcolumn = "yes:2"
		local left = side == "LEFT"
		local checked = vim.fn.strdisplaywidth("▎✓") <= 2 and "▎✓" or "✓"
		for _, hunk in ipairs(catalog.hunks) do
			if hunk.kind == "hunk" and file == (left and (hunk.oldpath or hunk.path) or hunk.path) then
				local first = left and hunk.left_start or hunk.right_start
				local size = left and hunk.left_count or hunk.right_count
				local viewed = state.read_hunks[hunk.id]
				for line = first, math.min(count, first + size - 1) do
					vim.api.nvim_buf_set_extmark(bufnr, NS, line - 1, 0, {
						sign_text = viewed and line == first and checked or "▎",
						sign_hl_group = viewed and "DiffviewReviewWinbarViewed" or "DiffviewReviewWinbarUnviewed",
						priority = 60,
					})
				end
			end
		end
	end
	local width = vim.api.nvim_win_get_width(winid) - vim.fn.getwininfo(winid)[1].textoff
	for _, thread in ipairs(comment_threads_for_file(state, file, count, side)) do
		if not thread.file_level or include_file_level then
			local comment = thread.entries[1].comment
			local line = thread.file_level and file_level_display_line(bufnr, winid, count) or thread.start_line
			vim.fn.sign_place(0, SIGN_GROUP, review_format.comment_sign(comment), bufnr, { lnum = line, priority = 30 })
			if width >= 8 then
				vim.api.nvim_buf_set_extmark(bufnr, NS, line - 1, 0, {
					virt_lines = review_format.comment_card(
						comment,
						thread.start_line,
						thread.end_line,
						width,
						#thread.entries > 1 or #(comment.replies or {}) > 0
					),
				})
			end
		end
	end
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

local function refresh_winbar(winid, file, state, progress)
	local width = vim.api.nvim_win_get_width(winid)
	vim.w[winid].diffview_review_width = width
	local status = review_status(file, state)
	local status_text = status.winbar_text
	if width < vim.fn.strdisplaywidth(status_text) + 4 then
		status_text = status.winbar_short_text
	end

	local separator = " · "
	local route = progress and (progress .. separator) or ""
	local file_width = width - vim.fn.strdisplaywidth(route) - vim.fn.strdisplaywidth(status_text) - vim.fn.strdisplaywidth(separator) - 1
	local file_label = winbar_file_label(file, file_width)
	local file_part = ""
	if file_label ~= "" then
		file_part = "%#DiffviewReviewWinbarFile#" .. separator .. file_label:gsub("%%", "%%%%")
	end

	vim.wo[winid].winbar = "%#DiffviewReviewWinbarFile#" .. route
		.. "%#" .. status.winbar_hl .. "#" .. status_text .. file_part
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


local function open_comment_editor(ctx, line, end_line, initial, on_save, title_prefix)
	local height = math.min(8, math.max(5, math.floor(vim.o.lines * 0.18)))
	title_prefix = title_prefix or "Private note"
	local title = (" %s · %s:%s "):format(title_prefix, ctx.file, range_label(line, end_line))
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
	local verb = (title_prefix == "Ask Pi" or title_prefix == "Reply") and "send" or "save"
	vim.wo[winid].winbar = title:gsub("%%", "%%%%") .. " | Ctrl-s " .. verb .. " · :q! discard"
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
			vim.cmd.stopinsert()
			close()
		end
	end

	vim.api.nvim_create_autocmd("BufWriteCmd", {
		buffer = bufnr,
		callback = function()
			save(false)
		end,
	})
	vim.keymap.set({ "n", "i" }, "<C-s>", function()
		save(true)
	end, { buffer = bufnr })
	vim.api.nvim_create_autocmd("WinClosed", {
		pattern = tostring(winid),
		callback = function()
			vim.schedule(restore_source)
		end,
	})
	vim.bo[bufnr].modified = false
	vim.schedule(function()
		if vim.api.nvim_get_current_win() == winid and vim.api.nvim_get_current_buf() == bufnr then
			vim.cmd.startinsert()
		end
	end)
end

function M.set_active_guide_context(context)
	if M.stop_agent_reply_polling then
		M.stop_agent_reply_polling()
	end
	if context then
		context = vim.deepcopy(context)
		for key, value in pairs(context) do
			if value == vim.NIL then
				context[key] = nil
			end
		end
	end
	active_guide_context = context
			and {
				assistant_name = context.assistant_name,
				review_label = context.review_label,
				base_oid = context.base_oid,
				context_kind = context.context_kind,
				diffview_rev_arg = context.diffview_rev_arg,
				head_oid = context.head_oid or context.pr_head_oid,
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
			}
		or nil
	guide_view.cache = nil
end

function M.clear_active_guide_context()
	if M.stop_agent_reply_polling then
		M.stop_agent_reply_polling()
	end
	active_guide_context = nil
	guide_view.cache = nil
end

function M.review_foldtext()
	local count = math.max(vim.v.foldend - vim.v.foldstart + 1, 0)
	local noun = count == 1 and "line" or "lines"
	local label = (" %d unchanged %s "):format(count, noun)
	local width = vim.api.nvim_win_get_width(0)
	local remaining = math.max(width - vim.fn.strdisplaywidth(label), 0)
	return string.rep("─", math.floor(remaining / 2)) .. label .. string.rep("─", math.ceil(remaining / 2))
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
	set(0, "LineNr", { bg = "#ffffff", fg = "#8c959f" })
	set(0, "CursorLine", { bg = "#f6f8fa" })
	set(0, "CursorLineNr", { bg = "#f6f8fa", fg = "#57606a", bold = true })
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
	-- Keep counterpart/empty filler lines neutral; make folded context quiet.
	set(0, "DiffviewDiffDeleteDim", { bg = "#f6f8fa", fg = "#8c959f" })
	set(0, "DiffviewDiffFiller", { bg = "#f6f8fa", fg = "#8c959f" })
	set(0, "DiffviewDiffText", { bg = "#aceebb", fg = "#24292f", bold = true })
	set(0, "Folded", { bg = "#eef3f6", fg = "#8c959f", italic = true })

	-- These are applied only through per-diff-window winhl mappings.
	set(0, "DiffviewReviewSyntaxComment", { fg = "#839496", italic = true })
	set(0, "DiffviewReviewSyntaxConstant", { fg = "#b58900" })
	set(0, "DiffviewReviewSyntaxDelimiter", { fg = "#657b83" })
	set(0, "DiffviewReviewSyntaxFunction", { fg = "#268bd2" })
	set(0, "DiffviewReviewSyntaxIdentifier", { fg = "#586e75" })
	set(0, "DiffviewReviewSyntaxOperator", { fg = "#657b83" })
	set(0, "DiffviewReviewSyntaxPreProc", { fg = "#cb4b16" })
	set(0, "DiffviewReviewSyntaxSpecial", { fg = "#2aa198" })
	set(0, "DiffviewReviewSyntaxStatement", { fg = "#859900" })
	set(0, "DiffviewReviewSyntaxString", { fg = "#2aa198" })
	set(0, "DiffviewReviewSyntaxType", { fg = "#b58900" })

	set(0, "DiffviewLeftDiffText", { bg = "#ffcecb", fg = "#24292f", bold = true })
	set(0, "DiffviewRightDiffText", { bg = "#aceebb", fg = "#24292f", bold = true })
	set(0, "DiffviewFilePanelInsertions", { fg = "#1a7f37", bold = true })
	set(0, "DiffviewFilePanelDeletions", { fg = "#cf222e", bold = true })
	set(0, "DiffviewFilePanelTitle", { fg = "#0969da", bold = true })
	set(0, "DiffviewFolderSign", { fg = "#0969da" })
	set(0, "DiffviewNonText", { fg = "#57606a" })
	-- Normal comments stay quiet; stronger accents remain reserved for guide/GitHub state.
	set(0, "DiffviewReviewCommentSign", { fg = "#8c959f" })
	set(0, "DiffviewReviewCommentPreview", { fg = "#425466", bg = "#e4ebef" })
	set(0, "DiffviewReviewCommentBorder", { fg = "#5b7388", bg = "#e4ebef" })
	set(0, "DiffviewReviewThreadQuestion", { fg = "#23476a", bold = true })
	set(0, "DiffviewReviewThreadResponse", { fg = "#245b50", bold = true })
	set(0, "DiffviewReviewGithub", { fg = "#8250df", bold = true })
	set(0, "DiffviewReviewGuideHigh", { fg = "#cf222e", bold = true })
	set(0, "DiffviewReviewGuideMedium", { fg = "#9a6700", bold = true })
	set(0, "DiffviewReviewGuideLow", { fg = "#57606a", bold = true })
	set(0, "DiffviewReviewGuideInfo", { fg = "#57606a", bold = true })
	set(0, "DiffviewReviewGuideHeading", { fg = "#23476a", bg = "#dce5e9", bold = true })
	set(0, "DiffviewReviewGuideSubheading", { fg = "#245b50", bold = true })
	set(0, "DiffviewReviewProseLabel", { fg = "#23476a", bold = true })
	local code_bg = "#dce5e9"
	set(0, "DiffviewReviewGuideCode", { fg = "#263b49", bg = code_bg })
	set(0, "DiffviewReviewPseudoKeyword", { fg = "#5b3c85", bg = code_bg, bold = true })
	set(0, "DiffviewReviewPseudoString", { fg = "#18634d", bg = code_bg })
	set(0, "DiffviewReviewPseudoCall", { fg = "#124c83", bg = code_bg, bold = true })
	set(0, "DiffviewReviewPseudoComment", { fg = "#4f5f69", bg = code_bg, italic = true })
	set(0, "DiffviewReviewCodeText", { fg = "#263b49" })
	set(0, "DiffviewReviewGuideLink", { fg = "#23476a", underline = true })
	set(0, "DiffviewReviewPanelUnviewed", { fg = "#9a6700", bold = true })
	set(0, "DiffviewReviewPanelViewed", { fg = "#6e7781" })
	set(0, "DiffviewReviewStatusFile", { fg = "#57606a", bold = true })
	set(0, "DiffviewReviewStatusMuted", { fg = "#6e7781" })
	set(0, "DiffviewReviewWinbarFile", { bg = "#f6f8fa", fg = "#57606a" })
	set(0, "DiffviewReviewWinbarUnviewed", { bg = "#fff8c5", fg = "#9a6700", bold = true })
	set(0, "DiffviewReviewWinbarViewed", { bg = "#dafbe1", fg = "#1a7f37", bold = true })
end

function M._resolve_visible_comment_anchors(ctx, state, visible)
	local review_anchor = require("utils.diffview_review_anchor")
	local snapshots = {}
	for _, item in ipairs(visible or {}) do
		if item.file and item.side and vim.api.nvim_buf_is_valid(item.bufnr) then
			local key = item.file .. "\0" .. item.side
			snapshots[key] = snapshots[key] or vim.api.nvim_buf_get_lines(item.bufnr, 0, -1, false)
		end
	end

	local changed = false
	for _, comment in ipairs(state.comments or {}) do
		if is_local_manual_comment(comment) and not review_format.is_file_level_comment(comment) then
			if type(comment.anchor) ~= "table" then
				if comment.anchor_status ~= "legacy_unverified" then
					comment.anchor_status = "legacy_unverified"
					changed = true
				end
			else
				local side = tostring(comment.anchor.side or comment.side or ""):upper()
				local file = normalize_file(comment.anchor.path or comment.file)
				local lines = snapshots[(file or "") .. "\0" .. side]
				if lines then
					local before = vim.deepcopy(comment.anchor.resolved)
					local old_line, old_end_line, old_status = comment.line, comment.end_line, comment.anchor_status
					local resolution = review_anchor.resolve(comment.anchor, lines)
					review_anchor.apply_resolution(comment, resolution)
					if
						not vim.deep_equal(before, comment.anchor.resolved)
						or old_line ~= comment.line
						or old_end_line ~= comment.end_line
						or old_status ~= comment.anchor_status
					then
						changed = true
					end
				end
			end
		end
	end

	if changed then
		save_state(ctx, state)
	end
	return changed
end

local function review_label(ctx)
	local context = active_guide_context
	if not context or not active_pr_context_matches_view(context, ctx) then
		return vim.fn.fnamemodify(ctx.root, ":t")
	end
	if context.pr_number then
		return "PR #" .. context.pr_number
	end
	return "Branch " .. tostring(context.review_label or context.assistant_name or "HEAD"):gsub("^review%-", "")
end

function M.refresh_visible()
	local view = current_view()
	local ctx = repo_context(view)
	if not ctx or not view or (view.closing and view.closing:check()) then
		return
	end

	local state, guide = load_state_with_guide(ctx)
	local scope = ensure_review_scope(ctx, state)
	ownership_scope.apply_order(view, guide)
	local workspace = view.review_chunks
	if workspace and workspace.plan and not workspace.started and view.cur_entry and view.cur_entry.opened then
		local first = chunk_workspace.next(ctx, 1, "chunk")
		if first then
			workspace.started = true
			local source_win = vim.api.nvim_get_current_win()
			vim.schedule(function()
				if current_view() == view and not view.closing:check() and not workspace.active
					and vim.api.nvim_get_current_win() == source_win
					and (is_file_panel_buffer(vim.api.nvim_get_current_buf())
						or file_for_buffer(vim.api.nvim_get_current_buf(), ctx, view))
				then
					chunk_workspace.activate(ctx, first.chunk_id, nil, state)
					M.refresh_visible()
				end
			end)
		end
	end
	local entries = review_entries(view, state)
	local function progress(winid)
		local workspace = view.review_chunks
		local width = vim.api.nvim_win_get_width(winid)
		local chunks = require("utils.diffview_review_chunks")
		local prefix = ""
		if workspace and workspace.catalog then
			local done, total = chunks.read_count(workspace.catalog.hunks, state)
			local wide = width >= 62
			local hunks = wide and chunks.progress_bar(done, total, 5) or ("%d/%d"):format(done, total)
			prefix = "Hunks " .. hunks .. " · "
			if workspace.plan then
				local complete, sections = chunks.section_count(workspace.plan, state)
				local bar = wide and chunks.progress_bar(complete, sections, 5) or ("%d/%d"):format(complete, sections)
				prefix = (width < 32 and "Sec " or "Sections ") .. bar .. " · " .. prefix
			end
		end
		if workspace and workspace.active then
			local chunk = workspace.plan.by_id[workspace.active]
			local current = chunk_workspace.current(ctx)
			local index = 1
			for number, hunk in ipairs(chunk.hunks) do
				if hunk.id == (current and current.id or workspace.hunk) then
					index = number
				end
			end
			local route = width < 55 and "S %d/%d · H %d/%d" or "Section %d/%d · Hunk %d/%d"
			route = route:format(chunk.number, #workspace.plan.chunks, index, #chunk.hunks)
			return vim.fn.strdisplaywidth(prefix .. route) + 10 <= width and prefix .. route or prefix:gsub(" · $", "")
		end
		return prefix .. guide_view.progress(entries, normalize_file(view.cur_entry and view.cur_entry.path), scope.enabled, width)
	end

	local visible = {}
	for _, winid in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
		local bufnr = vim.api.nvim_win_get_buf(winid)
		if is_file_panel_buffer(bufnr) then
			pcall(function()
				vim.wo[winid].signcolumn = "yes:1"
			end)
			refresh_file_panel(bufnr, view, state)
			vim.wo[winid].winbar = (scope.enabled and "Phoenix · " or "All · ")
				.. review_panel.status(state, entries, vim.api.nvim_win_get_width(winid), view.review_chunks).winbar
		else
			local file = file_for_buffer(bufnr, ctx, view)
			if file then
				local entry_file = entry_file_for_buffer(view and view.cur_entry, bufnr)
				require("utils.diffview_review_navigation").attach_reload(bufnr, ctx.root, entry_file)
				local side = entry_file and (entry_file.symbol == "a" and "LEFT" or "RIGHT") or nil
				table.insert(visible, {
					bufnr = bufnr,
					file = file,
					side = side,
					winid = winid,
				})
			elseif #entries == 0 and not vim.b[bufnr].diffview_review_panel then
				vim.wo[winid].winbar = progress(winid)
			end
		end
	end

	M._resolve_visible_comment_anchors(ctx, state, visible)
	local file_level_item, file_level_file = review_file_level_comment_item(visible, view)
	for _, item in ipairs(visible) do
		local file = item == file_level_item and file_level_file or item.file
		refresh_buffer(
			item.bufnr,
			file,
			state,
			item.winid,
			item.side,
			item == file_level_item,
			view.review_chunks and view.review_chunks.catalog
		)
		refresh_winbar(item.winid, item.file, state, progress(item.winid))
	end
	chunk_workspace.apply(ctx)
	review_panel.refresh({
		ctx = ctx,
		state = state,
		guide = guide,
		entries = entries,
		label = review_label(ctx),
		current = normalize_file(view.cur_entry and view.cur_entry.path),
		phoenix = scope.enabled,
	})
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
	if view.review_chunks and view.review_chunks.plan then
		return
	end
	local entries = review_entries(view, state)
	if #entries == 0 then
		return
	end

	context.initial_guide_jump_done = true
	for _, item in ipairs(entries) do
		if guide and guide.files_by_path[item.path] then
			if normalize_file(view.cur_entry and view.cur_entry.path) ~= item.path then
				jump_to_entry(view, item)
			end
			break
		end
	end
end

function M.stop_agent_reply_polling()
	if M.agent_reply_poll_timer then
		pcall(vim.fn.timer_stop, M.agent_reply_poll_timer)
		M.agent_reply_poll_timer = nil
	end
end

function M.process_agent_reply_artifacts()
	if M.agent_reply_processing then
		return
	end
	local view = current_view()
	local ctx = repo_context(view)
	if not (ctx and active_guide_context and active_guide_context.assistant_name) then
		return
	end

	M.agent_reply_processing = true
	local ok, process_error = pcall(function()
		local workspace = view and view.review_chunks
		local previous_guide = workspace and workspace.guide or (guide_view.cache and guide_view.cache.guide)
		local previous_error = workspace and workspace.error
		local state, guide = load_state_with_guide(ctx)
		local review_agent = require("utils.diffview_review_agent")
		local guide_status = review_agent.guide_status(ctx.state_path)
		if
			guide ~= previous_guide
			or not vim.deep_equal(M.last_guide_status, guide_status)
			or previous_error ~= (view and view.review_chunks and view.review_chunks.error)
		then
			M.last_guide_status = guide_status
			M.refresh_visible()
		end
		local changed, stats = review_agent.ingest(state, ctx.state_path)

		-- A missing service is different from a worker waiting for human input.
		local service_path = vim.fs.joinpath(vim.fn.fnamemodify(ctx.state_path, ":h"), "review-service.json")
		local service_ok, service = pcall(function()
			return vim.json.decode(table.concat(vim.fn.readfile(service_path), "\n"))
		end)
		local service_alive = service_ok
			and type(service) == "table"
			and vim.fn.localtime() * 1000 - (tonumber(service.updated_at) or 0) < 10000
		if not service_alive then
			for _, comment in ipairs(state.comments or {}) do
				if
					comment.agent_status == "running"
					or comment.agent_status == "pending"
					or comment.agent_status == "blocked"
				then
					comment.agent_status = "failed"
					comment.agent_error = "Main review service stopped; reopen review and retry this thread"
					changed = true
					stats.failed = stats.failed + 1
				end
			end
		end

		if changed and save_state(ctx, state) then
			M.refresh_visible()
			if stats.failed > 0 then
				notify(
					("Pi failed %d review request%s"):format(stats.failed, stats.failed == 1 and "" or "s"),
					vim.log.levels.WARN
				)
			end
		end
	end)
	M.agent_reply_processing = false
	if not ok then
		notify("Could not process Pi review replies: " .. tostring(process_error), vim.log.levels.ERROR)
	end
end

function M.start_agent_reply_polling(ctx)
	if not (ctx and ctx.state_path and active_guide_context and active_guide_context.assistant_name) then
		return
	end
	local review_agent = require("utils.diffview_review_agent")
	vim.fn.mkdir(review_agent.reply_dir(ctx.state_path), "p")
	M.process_agent_reply_artifacts()
	if M.agent_reply_poll_timer then
		return
	end
	M.agent_reply_poll_timer = vim.fn.timer_start(1000, M.process_agent_reply_artifacts, { ["repeat"] = -1 })
end

function M.dispatch_agent_reply(ctx, state, comment, request_body)
	local review_agent = require("utils.diffview_review_agent")
	comment.local_id = comment.local_id or review_agent.new_id("local")
	comment.agent_requests = comment.agent_requests or {}
	if comment.agent_request_id and not vim.tbl_contains(comment.agent_requests, comment.agent_request_id) then
		table.insert(comment.agent_requests, comment.agent_request_id)
	end
	comment.agent_request_id = review_agent.new_id("request")
	table.insert(comment.agent_requests, comment.agent_request_id)
	comment.agent_status = "pending"
	comment.agent_error = nil
	comment.agent_partial = nil
	comment.agent_input = nil
	comment.agent_activity = nil
	comment.agent_updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")

	if not save_state(ctx, state) then
		return false
	end
	M.refresh_visible()

	local assistant_name = active_guide_context and active_guide_context.assistant_name or nil
	if not assistant_name then
		comment.agent_status = "unavailable"
		comment.agent_error = "This Diffview was not opened by the review workflow"
		comment.agent_updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
		save_state(ctx, state)
		M.refresh_visible()
		notify("Comment saved, but no persistent review assistant is active; start with `review ...`", vim.log.levels.WARN)
		return false
	end

	vim.fn.mkdir(review_agent.reply_dir(ctx.state_path), "p")
	local prompt = review_agent.build_prompt({
		body = request_body or comment.body,
		comment_id = comment.local_id,
		end_line = comment.end_line,
		file = comment.file,
		line = comment.line,
		side = comment.side,
		request_id = comment.agent_request_id,
		state_path = ctx.state_path,
		base_oid = active_guide_context.base_oid,
		head_oid = active_guide_context.head_oid,
	})
	local sent, send_error = review_agent.enqueue(ctx.state_path, {
		root = ctx.root,
		comment_id = comment.local_id,
		request_id = comment.agent_request_id,
		prompt = prompt,
		base_oid = active_guide_context.base_oid,
		head_oid = active_guide_context.head_oid,
	})

	if sent then
		comment.agent_status = "pending"
		comment.agent_error = nil
	else
		comment.agent_status = "unavailable"
		comment.agent_error = send_error or "Review service is unavailable"
	end
	comment.agent_updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
	save_state(ctx, state)
	M.refresh_visible()
	M.start_agent_reply_polling(ctx)

	if not sent then
		notify(("Comment saved, but Pi request is unavailable: %s"):format(comment.agent_error), vim.log.levels.WARN)
		return false
	end
	return true
end

local function find_comment_by_identity(state, original)
	for index, comment in ipairs(state.comments or {}) do
		local matches = original.local_id and comment.local_id == original.local_id
			or original.guide_id and comment.guide_id == original.guide_id
			or original.github_id and comment.github_id == original.github_id
		if
			matches
			or (
				not original.local_id
				and not original.guide_id
				and not original.github_id
				and comment.file == original.file
				and comment.side == original.side
				and comment.line == original.line
				and comment.end_line == original.end_line
				and comment.source == original.source
				and comment.created_at == original.created_at
				and comment.body == original.body
			)
		then
			return comment, index
		end
	end
end

local function select_current_comment(ctx, state, opts, on_select)
	local line = line_from_opts(opts)
	local side = side_from_current_buffer(ctx.view)
	local candidates = {}
	local in_panel = is_file_panel_buffer(vim.api.nvim_get_current_buf())
	for index, comment in ipairs(state.comments or {}) do
		local first, last = clamp_comment_range(comment, math.huge)
		local file_level = review_format.is_file_level_comment(comment)
		if
			comment.file == ctx.file
			and not is_hidden_comment(comment)
			and (
				file_level
				or (
					not in_panel
					and first
					and first <= line
					and line <= last
					and (not side or (comment.side or "RIGHT") == side)
				)
			)
		then
			table.insert(candidates, { comment = comment, index = index })
		end
	end
	local function apply_selection(item)
		local comment, index = item.comment, item.index
		if ctx.state_path then
			local latest = load_state_with_guide(ctx)
			comment, index = find_comment_by_identity(latest, comment)
			if not comment then
				notify("Selected comment is no longer available", vim.log.levels.WARN)
				return
			end
			for key in pairs(state) do
				state[key] = nil
			end
			for key, value in pairs(latest) do
				state[key] = value
			end
		end
		on_select(comment, index)
	end
	if #candidates == 0 then
		notify("No review comment at this location or file level", vim.log.levels.WARN)
	elseif #candidates == 1 then
		apply_selection(candidates[1])
	else
		vim.ui.select(candidates, {
			prompt = "Select review comment:",
			format_item = function(item)
				return ("[%s %s] %s"):format(
					item.comment.guide_retired and "earlier guide" or item.comment.source or "local",
					item.comment.file_level and "file" or (item.comment.side or "RIGHT"),
					comment_preview(item.comment)
				)
			end,
		}, function(item)
			if item then
				apply_selection(item)
			end
		end)
	end
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
	local existing = find_comment(state, ctx.file, line, { manual_only = true, side = side_from_current_buffer(ctx.view) })
	local provided = opts and opts.args and opts.args ~= "" and opts.args or nil
	local side = side_from_current_buffer(ctx.view)
	local pr = active_pr_context(ctx)
	local anchor = M._capture_comment_anchor(ctx, ctx.file, side, line, end_line)

	local function save_comment(input)
		if not input then
			return
		end
		input = vim.trim(input)
		if input == "" then
			notify("Empty review comment skipped", vim.log.levels.WARN)
			return
		end

		state = load_state_with_guide(ctx)
		local comment = existing and find_comment_by_identity(state, existing) or nil
		if comment then
			comment.body = input
			if side then
				comment.side = side
			end
			if pr and is_local_manual_comment(comment) then
				set_comment_pr_context(comment, pr)
			end
			comment.updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
		else
			comment = {
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

		comment.local_id = comment.local_id or require("utils.diffview_review_agent").new_id("local")
		comment.anchor = anchor
		comment.anchor_status = comment.anchor and "anchored" or "legacy_unverified"
		if opts and opts.ask then
			M.dispatch_agent_reply(ctx, state, comment)
		elseif save_state(ctx, state) then
			M.refresh_visible()
			notify("Saved local review comment")
		end
	end

	if provided then
		save_comment(provided)
		return
	end

	local title = opts and opts.ask and "Ask Pi" or (existing and "Edit private note" or "Private note")
	open_comment_editor(ctx, line, end_line, existing and existing.body or "", save_comment, title)
end

function M.add_comment_visual(ask)
	local start_line = vim.fn.line("v")
	local end_line = vim.fn.line(".")
	M.add_comment({ line = math.min(start_line, end_line), end_line = math.max(start_line, end_line), ask = ask == true })
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

local function mark_resolved(comment)
	if review_format.is_imported_github_comment(comment) then
		comment.local_resolved = true
	else
		comment.resolved = true
	end
	comment.updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
end

local function change_panel_comment(ctx, original, action)
	if current_view() ~= ctx.view or ctx.view.left.commit ~= ctx.base_oid or ctx.view.right.commit ~= ctx.head_oid then
		notify("Review changed; reopen Threads before changing a comment", vim.log.levels.WARN)
		return
	end
	local state = load_state_with_guide(ctx)
	local comment, index = find_comment_by_identity(state, original)
	if not comment then
		notify("This comment is no longer available")
		return
	end
	if action == "delete" then
		remove_comment_at_index(state, index)
	else
		mark_resolved(comment)
	end
	if save_state(ctx, state) then
		M.refresh_visible()
		notify(
			action == "delete" and "Deleted/dismissed locally; GitHub was not changed"
				or "Resolved locally; GitHub was not changed"
		)
	end
end

local function open_review_panel(opts)
	local ctx = current_file_context()
	if
		not require_active_diffview(ctx, "opening the review panel")
		or not require_repo_context(ctx, "opening the review panel")
	then
		return
	end
	local state, guide = load_state_with_guide(ctx)
	local scope = ensure_review_scope(ctx, state)
	ownership_scope.apply_order(ctx.view, guide)
	ctx.base_oid, ctx.head_oid = ctx.view.left and ctx.view.left.commit, ctx.view.right and ctx.view.right.commit
	if opts.mode == "threads" and not opts.filter and not opts.attention then
		local threads = require("utils.diffview_review_threads")
		local preferred = {}
		for _, comment in ipairs(threads.list(state)) do
			if comment.source ~= "guide" or comment.agent_request_id or #(comment.replies or {}) > 0 then
				table.insert(preferred, comment)
			end
		end
		local location = { side = side_from_current_buffer(ctx.view), file_level_line = 1 }
		local line = vim.api.nvim_win_get_cursor(0)[1]
		local target = find_comment({ comments = preferred }, ctx.file, line, location)
			or find_comment(state, ctx.file, line, location)
		if target then
			opts.selected = threads.identity(target)
		end
	end
	return review_panel.open({
		ctx = ctx,
		state = state,
		guide = guide,
		entries = review_entries(ctx.view, state),
		current = ctx.file,
		label = review_label(ctx),
		phoenix = scope.enabled,
		callbacks = {
			chunk = M.chunk_action,
			step_chunk = M.chunk_step,
			delete = function(comment)
				change_panel_comment(ctx, comment, "delete")
			end,
			resolve = function(comment)
				change_panel_comment(ctx, comment, "resolve")
			end,
			generate = M.generate_guide,
			refine = M.refine_guide,
			status = function()
				local status = require("utils.diffview_review_agent").guide_status(ctx.state_path)
				if status and status.base_oid == ctx.base_oid and status.head_oid == ctx.head_oid then
					return status
				end
			end,
			jump = function(target, opts)
				opts = opts or {}
				if target.chunk_id then
					M.chunk_action("open", target)
					return
				end
				local line, last = target.line, target.end_line
				local is_comment = target.body ~= nil
				if target.file_level or (is_comment and review_format.is_file_level_comment(target)) then
					line, last = nil, nil
				elseif is_comment and target.line then
					line, last = clamp_comment_range(target, math.huge)
					if not line then
						notify("The comment has an invalid source range", vim.log.levels.WARN)
						return
					end
				end
				local source = {
					path = target.path or target.file,
					line = line,
					end_line = last,
					revision = target.revision,
					side = target.side or (target.entry and target.entry.status == "D" and "LEFT" or "RIGHT"),
					anchor_status = target.anchor_status,
				}
				local latest = load_state_with_guide(ctx)
				local workspace = ctx.view.review_chunks
				if workspace and workspace.active and workspace.plan
					and source.anchor_status ~= "stale" and source.anchor_status ~= "ambiguous"
					and (not source.revision or source.revision == (source.side == "LEFT" and ctx.base_oid or ctx.head_oid))
				then
					local choice
					local chunks = require("utils.diffview_review_chunks")
					local matches = chunks.comment_hunks(workspace.plan, source)
					if #matches == 0 then
						matches = chunks.comment_hunks(workspace.plan, { path = source.path, side = source.side })
					end
					for _, match in ipairs(matches) do
						if (not opts.keep_section or match.section.id == workspace.active)
							and vim.tbl_contains(chunk_workspace.visible(ctx, match.section), match.hunk)
						then
							choice = choice or match
							if match.section.id == workspace.active then
								choice = match
								break
							end
						end
					end
					if choice then
						chunk_workspace.activate(ctx, choice.section.id, choice.hunk.id, latest, source, opts)
						M.refresh_visible()
						return
					end
				end
				require("utils.diffview_review_navigation").open({
					root = ctx.root,
					view = ctx.view,
					base = ctx.base_oid,
					head = ctx.head_oid,
					entries = review_entries(ctx.view, latest),
					on_open = opts.on_open,
					on_return = opts.on_return,
				}, source)
			end,
			read = function(comment)
				if not comment.agent_unread then
					return
				end
				comment.agent_unread = nil
				local latest = load_state_with_guide(ctx)
				local current = find_comment_by_identity(latest, comment)
				if current then
					current.agent_unread = nil
					save_state(ctx, latest)
					M.refresh_visible()
				end
			end,
			retry = function(comment)
				local latest = load_state_with_guide(ctx)
				local current = find_comment_by_identity(latest, comment)
				if current then
					M.dispatch_agent_reply(ctx, latest, current)
				end
			end,
			reply = function(comment, body)
				local latest = load_state_with_guide(ctx)
				local current = find_comment_by_identity(latest, comment)
				if not current then
					return
				end
				current.replies = current.replies or {}
				table.insert(
					current.replies,
					{ author = vim.env.USER or "you", body = body, created_at = os.date("!%Y-%m-%dT%H:%M:%SZ") }
				)
				M.dispatch_agent_reply(ctx, latest, current, body)
			end,
		},
	}, opts)
end

local function open_review_hunk(ctx, target, state)
	local ok, err = chunk_workspace.activate(ctx, target.chunk_id, target.hunk_id, state)
	if not ok then
		notify(err, vim.log.levels.WARN)
	end
	M.refresh_visible()
	return ok
end

function M.chunk_action(action, target)
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "reviewing sections") then
		return
	end
	local previous_plan = ctx.view.review_chunks and ctx.view.review_chunks.plan
	local state = load_state_with_guide(ctx)
	local workspace = ctx.view.review_chunks
	if action == "all" then
		chunk_workspace.leave(ctx)
		M.refresh_visible()
		return
	end
	if action == "viewed" or action == "toggle_viewed" then
		local chunk_id = target and target.chunk_id or (workspace and workspace.active)
		local chunk = workspace and workspace.plan and workspace.plan.by_id[chunk_id]
		if not chunk then
			notify("Select a review section before marking it viewed", vim.log.levels.WARN)
			return
		end
		local previous_chunk = previous_plan and previous_plan.by_id[chunk_id]
		if previous_chunk and not vim.deep_equal(previous_chunk.hunks, chunk.hunks) then
			notify("Section changed; review its updated hunks before marking it viewed", vim.log.levels.WARN)
			M.refresh_visible()
			return
		end
		local path = target and target.file_group
		local id = target and not path and target.hunk_id
		local function matches(hunk)
			return (not path or hunk.path == path) and (not id or hunk.id == id)
		end
		local hunks = vim.tbl_filter(matches, chunk.hunks)
		if #vim.tbl_filter(matches, chunk_workspace.visible(ctx, chunk)) ~= #hunks then
			notify("Switch ownership scope to All before changing viewed state for this group", vim.log.levels.WARN)
			return
		end
		local read, total = require("utils.diffview_review_chunks").read_count(hunks, state)
		local viewed = (action == "viewed" or read ~= total) or nil
		local changed = false
		for _, hunk in ipairs(hunks) do
			if state.read_hunks[hunk.id] ~= viewed then
				state.read_hunks[hunk.id] = viewed
				changed = true
			end
		end
		if changed then
			save_state(ctx, state)
			M.refresh_visible()
		end
		return
	end
	if action == "read" then
		local hunk = target
				and target.hunk_id
				and workspace
				and workspace.catalog
				and workspace.catalog.by_id[target.hunk_id]
			or chunk_workspace.current(ctx)
		if not chunk_workspace.can_read(ctx, hunk) then
			notify("Place the cursor in an active hunk before marking it read", vim.log.levels.WARN)
			return
		end
		state.read_hunks[hunk.id] = not state.read_hunks[hunk.id] or nil
		save_state(ctx, state)
		M.refresh_visible()
		return
	end
	open_review_panel({ mode = "guide", focused = true })
	if not (workspace and workspace.plan and target) then
		return
	end
	open_review_hunk(ctx, target, state)
end

function M.chunk_step(direction, kind)
	local ctx = current_file_context()
	if not ctx or not ctx.view then
		return false
	end
	local state = load_state_with_guide(ctx)
	local workspace = ctx.view.review_chunks
	if not (workspace and workspace.plan and (workspace.active or kind == "chunk")) then
		return false
	end
	local target = chunk_workspace.next(ctx, direction, kind)
	if target and open_review_hunk(ctx, target, state) and kind == "chunk" then
		review_panel.show_section_list(ctx)
	end
	return true
end

function M.show_threads(opts)
	opts = opts or {}
	opts.mode = "threads"
	return open_review_panel(opts)
end

function M.next_attention()
	return M.show_threads({ attention = true })
end

function M.status_click(index, _, button)
	if button ~= "l" then
		return
	end
	local clicked = vim.fn.getmousepos().winid
	if valid_tab_winid(clicked) then
		vim.api.nvim_set_current_win(clicked)
	end
	if index == 1 then
		M.show_guide_popup()
	else
		local filter = ({ [2] = "running", [3] = "blocked", [4] = "unread", [5] = "pending" })[index]
		if filter then
			M.show_threads({ filter = filter })
		end
	end
end

function M.reply_comment()
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "replying to a review thread") then
		return
	end
	if not require_repo_context(ctx, "replying to a review thread") then
		return
	end
	if not ctx.file then
		notify("Open a Diffview file before replying to a review thread", vim.log.levels.WARN)
		return
	end

	local line = vim.api.nvim_win_get_cursor(0)[1]
	local state = load_state_with_guide(ctx)
	select_current_comment(ctx, state, { line = line }, function(comment)
		local reply_line = tonumber(comment.line) or line
		local reply_end_line = tonumber(comment.end_line) or reply_line
		open_comment_editor(ctx, reply_line, reply_end_line, "", function(input)
			local body = vim.trim(input or "")
			if body == "" then
				notify("Empty thread reply skipped", vim.log.levels.WARN)
				return
			end

			state = load_state_with_guide(ctx)
			comment = find_comment_by_identity(state, comment)
			if not comment then
				notify("Thread was removed while editing the reply", vim.log.levels.WARN)
				return
			end
			comment.replies = type(comment.replies) == "table" and comment.replies or {}
			table.insert(comment.replies, {
				author = vim.env.USER or "you",
				body = body,
				created_at = os.date("!%Y-%m-%dT%H:%M:%SZ"),
			})
			comment.updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
			if save_state(ctx, state) then
				M.refresh_visible()
				local follow_up = ("Continue the existing review thread.\nOriginal comment: %s\nNew local reply: %s"):format(
					tostring(comment.body or ""),
					body
				)
				if M.dispatch_agent_reply(ctx, state, comment, follow_up) then
					notify(
						("Added reply and sent a Pi follow-up for %s:%s"):format(
							ctx.file,
							range_label(reply_line, reply_end_line)
						)
					)
				else
					notify(("Added local reply to %s:%s"):format(ctx.file, range_label(reply_line, reply_end_line)))
				end
			end
		end, "Reply")
	end)
end

function M.reanchor_comment(opts)
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "re-anchoring a review comment") then
		return
	end
	if not require_repo_context(ctx, "re-anchoring a review comment") then
		return
	end
	if not ctx.file then
		notify("Open a Diffview file before re-anchoring a comment", vim.log.levels.WARN)
		return
	end

	local line, end_line = range_from_opts(opts)
	local state = load_state_with_guide(ctx)
	local comment = find_comment(state, ctx.file, line, { manual_only = true })
	if not comment then
		local unresolved = {}
		for _, candidate in ipairs(state.comments or {}) do
			if
				is_local_manual_comment(candidate)
				and candidate.file == ctx.file
				and (
					candidate.anchor_status == "stale"
					or candidate.anchor_status == "ambiguous"
					or candidate.anchor_status == "legacy_unverified"
				)
			then
				table.insert(unresolved, candidate)
			end
		end
		if #unresolved == 1 then
			comment = unresolved[1]
		elseif #unresolved > 1 then
			notify(("%d unresolved comments exist in %s; jump to the intended comment first"):format(#unresolved, ctx.file), vim.log.levels.WARN)
			return
		else
			notify(("No local review comment at %s:%d"):format(ctx.file, line), vim.log.levels.WARN)
			return
		end
	end

	local side = side_from_current_buffer(ctx.view)
	local previous_anchor = type(comment.anchor) == "table" and vim.deepcopy(comment.anchor) or nil
	local anchor = M._capture_comment_anchor(ctx, ctx.file, side, line, end_line)
	if not anchor then
		notify("Could not capture a content anchor in this Diffview pane", vim.log.levels.ERROR)
		return
	end
	comment.anchor_history = type(comment.anchor_history) == "table" and comment.anchor_history or {}
	if previous_anchor then
		table.insert(comment.anchor_history, previous_anchor)
	end
	comment.anchor = anchor
	comment.anchor_status = "anchored"
	comment.line = line
	comment.end_line = end_line ~= line and end_line or nil
	comment.side = side
	comment.updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
	if save_state(ctx, state) then
		M.refresh_visible()
		notify(("Re-anchored review comment at %s:%s"):format(ctx.file, range_label(line, end_line)))
	end
end

function M.reanchor_comment_visual()
	local start_line = vim.fn.line("v")
	local end_line = vim.fn.line(".")
	M.reanchor_comment({ line = math.min(start_line, end_line), end_line = math.max(start_line, end_line) })
end

function M.retry_agent_reply(opts)
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "retrying a Pi review reply") then
		return
	end
	if not require_repo_context(ctx, "retrying a Pi review reply") then
		return
	end
	if not ctx.file then
		notify("Open a Diffview file before retrying a Pi review reply", vim.log.levels.WARN)
		return
	end

	local line = line_from_opts(opts)
	local state = load_state_with_guide(ctx)
	local comment = find_comment(state, ctx.file, line, { manual_only = true })
	if not comment then
		notify(("No local review comment at %s:%d"):format(ctx.file, line), vim.log.levels.WARN)
		return
	end
	if M.dispatch_agent_reply(ctx, state, comment) then
		notify(("Retried Pi review for %s:%d"):format(ctx.file, line))
	end
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

	local state = load_state_with_guide(ctx)
	select_current_comment(ctx, state, opts, function(_, index)
		remove_comment_at_index(state, index)
		if save_state(ctx, state) then
			notify("Deleted/dismissed local review comment")
			M.refresh_visible()
		end
	end)
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

	local state = load_state_with_guide(ctx)
	select_current_comment(ctx, state, opts, function(comment)
		mark_resolved(comment)
		if save_state(ctx, state) then
			notify("Resolved locally; GitHub was not changed")
			M.refresh_visible()
		end
	end)
end

function M.toggle_ownership_filter()
	local ctx = current_file_context()
	if
		not require_active_diffview(ctx, "filtering review files")
		or not require_repo_context(ctx, "filtering review files")
	then
		return
	end
	local state = load_state_with_guide(ctx)
	local scope = ensure_review_scope(ctx, state)
	local previous = scope.enabled
	local ok, err = ownership_scope.set(scope, not previous)
	if not ok then
		notify(err, vim.log.levels.WARN)
		return
	end
	state.ownership_filter = scope.enabled and "phoenix" or "all"
	if not save_state(ctx, state) then
		scope.enabled = previous
		return
	end
	ctx.view:update_files(function(update_error)
		vim.schedule(function()
			if update_error then
				notify("Diffview filter refresh failed", vim.log.levels.ERROR)
			end
			M.refresh_visible()
		end)
	end)
end

local function comment_targets(view, state)
	local targets = {}
	for _, item in ipairs(review_entries(view, state)) do
		for _, comment in ipairs(comments_for_file(state, item.path)) do
			table.insert(targets, {
				item = item,
				line = comment.start_line,
				side = comment.comment.side or "RIGHT",
			})
		end
	end
	return targets
end

local function current_comment_target_index(targets, file, line, side)
	local fallback = nil
	for index, target in ipairs(targets) do
		if target.item.path == file and (not side or target.side == side) then
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
	local current_index = current_comment_target_index(targets, ctx.file, cursor_line, side_from_current_buffer(ctx.view))
	local target_index
	if current_index then
		target_index = ((current_index - 1 + direction) % #targets) + 1
	else
		target_index = direction == -1 and #targets or 1
	end

	local target = targets[target_index]
	jump_to_entry(ctx.view, target.item, target.line, target.side)
end

local function import_github_comments(ctx, pr, files)
	local raw_comments, fetch_error = fetch_github_comments(pr)
	if not raw_comments then
		notify(fetch_error, vim.log.levels.ERROR)
		return
	end

	local state = load_state_with_guide(ctx)
	local changed, stats = import_github_comments_into_state(state, raw_comments, files, pr.head_oid)
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

function M.refresh_review()
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "refreshing review") then
		return
	end
	guide_view.cache = nil
	require("diffview").emit("refresh_files")
	M.process_agent_reply_artifacts()
	M.refresh_visible()
	if active_pr_context(ctx) then
		M.import_github_comments()
	end
	notify("Reloaded local review; the diff boundary was not changed")
end

local function refresh_diffview()
	local ctx = current_file_context()
	local workspace = ctx.view and ctx.view.review_chunks
	if
		(workspace and workspace.plan)
		or (ctx.view and active_guide_path(ctx) and active_pr_context_matches_view(active_guide_context, ctx))
	then
		M.refresh_review()
	else
		vim.cmd.DiffviewRefresh()
	end
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

function M.open_review_source()
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "code navigation") or not ctx.file then
		return
	end
	local entry_file = entry_file_for_buffer(ctx.view and ctx.view.cur_entry, vim.api.nvim_get_current_buf())
	local side = side_from_current_buffer(ctx.view) or "RIGHT"
	local file = entry_file and entry_file.path or ctx.file
	local commit_sha, blob_sha = M._anchor_git_identity(ctx, file, side)
	if not commit_sha or not blob_sha then
		notify("Cannot identify this revision for LSP navigation", vim.log.levels.WARN)
		return
	end
	local head = vim.fn.systemlist({ "git", "-C", ctx.root, "rev-parse", "HEAD" })[1]
	vim.fn.system({ "git", "-C", ctx.root, "diff", "--quiet", "HEAD", "--" })
	if head ~= commit_sha or vim.v.shell_error ~= 0 then
		notify("LSP needs a clean checkout of the selected revision; the pinned diff is unchanged", vim.log.levels.WARN)
		return
	end
	for _, buffer in ipairs(vim.api.nvim_list_bufs()) do
		if vim.bo[buffer].modified and vim.startswith(vim.api.nvim_buf_get_name(buffer), ctx.root .. "/") then
			notify("Save or discard modified source buffers before revision-matched LSP navigation", vim.log.levels.WARN)
			return
		end
	end
	local source_path = vim.fs.joinpath(ctx.root, file)
	if vim.fn.filereadable(source_path) ~= 1 then
		notify("The selected source file is not available in this checkout", vim.log.levels.WARN)
		return
	end
	local line = entry_file and vim.api.nvim_win_get_cursor(0)[1] or 1
	vim.cmd("tabnew " .. vim.fn.fnameescape(source_path))
	vim.api.nvim_win_set_cursor(0, { line, 0 })
end

function M.request_guide(action, body)
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "updating the human review guide") then
		return false
	end
	if not (active_guide_context and active_guide_context.assistant_name and active_guide_context.path) then
		notify("Open this review with `review ...` to generate a guide in the main Pi session", vim.log.levels.WARN)
		return false
	end
	if
		not active_guide_path(ctx)
		or not active_pr_context_matches_view(active_guide_context, ctx)
		or not ctx.view.left
		or ctx.view.left.commit ~= active_guide_context.base_oid
		or not ctx.view.right
		or ctx.view.right.commit ~= active_guide_context.head_oid
	then
		notify(
			"Guide context does not match this pinned Diffview; reopen review before generating a guide",
			vim.log.levels.WARN
		)
		return false
	end
	load_state_with_guide(ctx)
	local workspace = ctx.view.review_chunks
	if workspace and workspace.error then
		body = (body or "") .. "\nSection-plan validation: " .. workspace.error
	end
	local review_agent = require("utils.diffview_review_agent")
	local ok, error_message = review_agent.enqueue(ctx.state_path, {
		request_id = review_agent.new_id("guide"),
		action = action or "generate",
		body = body,
		root = ctx.root,
		base_oid = active_guide_context.base_oid,
		head_oid = active_guide_context.head_oid,
	}, "guide-requests")
	if not ok then
		notify("Guide request unavailable: " .. tostring(error_message), vim.log.levels.WARN)
		return false
	end
	M.start_agent_reply_polling(ctx)
	notify("Guide update queued in the main Pi session; continue reviewing")
	return true
end

function M.generate_guide()
	return M.request_guide("generate")
end

function M.refine_guide()
	local ctx = current_file_context()
	if not require_active_diffview(ctx, "refining the human review guide") then
		return
	end
	ctx.file = "human review guide"
	local context = active_guide_context
	open_comment_editor(ctx, 1, 1, "", function(input)
		if current_view() ~= ctx.view or active_guide_context ~= context then
			notify(
				"Review changed while editing feedback; reopen guide refinement in the intended review",
				vim.log.levels.WARN
			)
			return
		end
		local body = vim.trim(input or "")
		if body ~= "" then
			M.request_guide("refine", body)
		end
	end, "Refine")
end

function M.show_guide_popup()
	return open_review_panel({ mode = "guide" })
end

function M.diffview_keymaps()
	local shared = {
		{ "n", "<leader>gdf", M.toggle_ownership_filter, { desc = "Toggle All/Phoenix CODEOWNERS scope" } },
		{ "n", "<leader>gdr", refresh_diffview, { desc = "Refresh Diffview and review state" } },
		{ "x", "<leader>gdr", refresh_diffview, { desc = "Refresh Diffview and review state" } },
		{
			"n",
			"<leader>gdg",
			function()
				open_review_panel({})
			end,
			{ desc = "Open review panel (Guide / Threads)" },
		},
		{
			"n",
			"]r",
			function()
				M.chunk_step(1, "chunk")
			end,
			{ desc = "Next review section" },
		},
		{
			"n",
			"[r",
			function()
				M.chunk_step(-1, "chunk")
			end,
			{ desc = "Previous review section" },
		},
		{
			"n",
			"<tab>",
			function()
				if not M.chunk_step(1, "hunk") then
					require("diffview.actions").select_next_entry()
				end
			end,
			{ desc = "Next hunk / file" },
		},
		{
			"n",
			"<s-tab>",
			function()
				if not M.chunk_step(-1, "hunk") then
					require("diffview.actions").select_prev_entry()
				end
			end,
			{ desc = "Previous hunk / file" },
		},
		{
			"n",
			"<leader>gdv",
			function()
				M.chunk_action("read")
			end,
			{ desc = "Toggle current Git hunk read" },
		},
		{
			"n",
			"<leader>gdt",
			function()
				M.show_threads({ at_cursor = true })
			end,
			{ desc = "Open thread under cursor" },
		},
		{ "n", "<leader>gdO", M.open_review_source, { desc = "Open revision-matched source for LSP" } },
		{
			"n",
			"<leader>gd]",
			function()
				M.next_review_comment(1)
			end,
			{ desc = "Next review comment" },
		},
		{
			"n",
			"<leader>gd[",
			function()
				M.next_review_comment(-1)
			end,
			{ desc = "Previous review comment" },
		},
	}
	local view = vim.deepcopy(shared)
	table.insert(view, {
		"n",
		"<Esc>",
		function()
			if not review_panel.return_to_thread(current_file_context()) then
				vim.cmd.nohlsearch()
			end
		end,
		{ desc = "Return to Threads or clear search highlight" },
	})
	vim.list_extend(view, {
		{
			"n",
			"]c",
			function()
				if not M.chunk_step(1, "hunk") then
					vim.cmd("normal! ]c")
				end
			end,
			{ desc = "Next review hunk / change" },
		},
		{
			"n",
			"[c",
			function()
				if not M.chunk_step(-1, "hunk") then
					vim.cmd("normal! [c")
				end
			end,
			{ desc = "Previous review hunk / change" },
		},
		{ "n", "<leader>gda", M.add_comment, { desc = "Add review comment" } },
		{ "x", "<leader>gda", M.add_comment_visual, { desc = "Add range review comment" } },
		{
			"n",
			"<leader>gdA",
			function()
				M.add_comment({ ask = true })
			end,
			{ desc = "Ask Pi about this location" },
		},
		{
			"x",
			"<leader>gdA",
			function()
				M.add_comment_visual(true)
			end,
			{ desc = "Ask Pi about this range" },
		},
		{ "n", "<leader>gdl", M.reanchor_comment, { desc = "Relocate comment anchor" } },
		{ "x", "<leader>gdl", M.reanchor_comment_visual, { desc = "Relocate range comment anchor" } },
	})
	return { view = view, file_panel = shared }
end

function M.setup()
	vim.api.nvim_create_user_command("DiffviewReviewAllChanges", function()
		M.chunk_action("all")
	end, { force = true })
	_G.DiffviewReviewStatusClick = M.status_click
	vim.api.nvim_create_user_command("DiffviewReviewAttention", M.next_attention, {
		force = true,
		desc = "Next unread answer or review input request",
	})
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
			if event.match == "DiffviewViewPostLayout" then
				local ctx = repo_context(current_view())
				if ctx then ensure_review_scope(ctx, load_state(ctx)) end
			end
			vim.defer_fn(function()
				M.apply_highlights()
				M.refresh_visible()
				if event.match == "DiffviewViewPostLayout" then
					M.jump_to_initial_guide_file()
					M.auto_import_github_comments()
					M.start_agent_reply_polling(repo_context(current_view()))
				end
			end, 100)
		end,
	})

	vim.api.nvim_create_autocmd("WinResized", {
		group = group,
		callback = function()
			for _, win in ipairs(vim.v.event.windows) do
				if
					vim.api.nvim_win_is_valid(win)
					and vim.wo[win].diff
					and vim.w[win].diffview_review_width ~= vim.api.nvim_win_get_width(win)
				then
					local tab = vim.api.nvim_win_get_tabpage(win)
					vim.schedule(function()
						if vim.api.nvim_get_current_tabpage() == tab then
							M.refresh_visible()
						end
					end)
					break
				end
			end
		end,
	})

	vim.api.nvim_create_user_command("DiffviewReviewComment", M.add_comment, {
		nargs = "*",
		range = true,
		force = true,
		desc = "Add or update a local Diffview review comment",
	})
	vim.api.nvim_create_user_command("DiffviewReviewRefresh", M.refresh_review, {
		force = true,
		desc = "Reload review state and GitHub comments without regenerating guidance",
	})
	vim.api.nvim_create_user_command("DiffviewReviewAsk", function(opts)
		opts.ask = true
		M.add_comment(opts)
	end, { nargs = "*", range = true, force = true, desc = "Save a question and start a parallel Pi review thread" })
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
	vim.api.nvim_create_user_command("DiffviewReviewRetryAgent", M.retry_agent_reply, {
		range = true,
		force = true,
		desc = "Retry the Pi thread for the current review comment",
	})
	vim.api.nvim_create_user_command("DiffviewReviewThreads", M.show_threads, {
		force = true,
		desc = "Open parallel Pi review conversations",
	})
	vim.api.nvim_create_user_command("DiffviewReviewReply", M.reply_comment, {
		force = true,
		desc = "Add a local reply to the review thread at the current line",
	})
	vim.api.nvim_create_user_command("DiffviewReviewReanchor", M.reanchor_comment, {
		range = true,
		force = true,
		desc = "Re-anchor the local review comment at the current line",
	})
	vim.api.nvim_create_user_command("DiffviewReviewTogglePhoenix", M.toggle_ownership_filter, {
		force = true,
		desc = "Toggle All/Phoenix CODEOWNERS-owned changed files",
	})
	vim.api.nvim_create_user_command("DiffviewReviewGuide", M.show_guide_popup, {
		force = true,
		desc = "Show the code-centered human review guide",
	})
	vim.api.nvim_create_user_command("DiffviewReviewGenerateGuide", M.generate_guide, {
		force = true,
		desc = "Generate/update the human guide in the main Pi session",
	})
	vim.api.nvim_create_user_command("DiffviewReviewRefineGuide", M.refine_guide, {
		force = true,
		desc = "Ask the main Pi session to refine the human guide",
	})
	vim.api.nvim_create_user_command("DiffviewReviewImportGithubComments", M.import_github_comments, {
		force = true,
		desc = "Import GitHub PR review comments into local Diffview state",
	})
end

return M
