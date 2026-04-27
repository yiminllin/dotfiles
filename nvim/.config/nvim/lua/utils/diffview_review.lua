local M = {}

local NS = vim.api.nvim_create_namespace("diffview_review")
local SIGN_GROUP = "diffview_review"
local STATE_VERSION = 1

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

local function file_from_entry_buffer(entry, bufnr)
	if not entry or not entry.layout then
		return nil
	end

	local files_ok, files = pcall(function()
		return entry.layout:files()
	end)
	if not files_ok or type(files) ~= "table" then
		return nil
	end

	for _, file in ipairs(files) do
		if file.bufnr == bufnr then
			return normalize_file(file.path or entry.path)
		end
	end

	return nil
end

local function file_for_buffer(bufnr, ctx, view)
	if vim.bo[bufnr].filetype == "DiffviewFiles" or vim.bo[bufnr].filetype == "DiffviewFileHistory" then
		return nil
	end

	local from_entry = file_from_entry_buffer(view and view.cur_entry, bufnr)
	if from_entry then
		return from_entry
	end

	return file_from_buffer_name(bufnr, ctx)
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

local function new_state(ctx)
	return {
		version = STATE_VERSION,
		repo = ctx.root,
		viewed = {},
		comments = {},
	}
end

local function ensure_state(state, ctx)
	return {
		version = STATE_VERSION,
		repo = ctx.root,
		updated_at = type(state) == "table" and state.updated_at or nil,
		viewed = type(state) == "table" and type(state.viewed) == "table" and state.viewed or {},
		comments = type(state) == "table" and type(state.comments) == "table" and state.comments or {},
	}
end

local function merge_nested_reviews(document, ctx)
	local state = new_state(ctx)
	if type(document) ~= "table" or type(document.reviews) ~= "table" then
		return state
	end

	for _, review in pairs(document.reviews) do
		if type(review) == "table" then
			for file, viewed in pairs(review.viewed or {}) do
				if viewed then
					state.viewed[file] = true
				end
			end
			for _, comment in ipairs(review.comments or {}) do
				table.insert(state.comments, comment)
			end
		end
	end
	return state
end

local function load_state(ctx)
	if vim.fn.filereadable(ctx.state_path) ~= 1 then
		return new_state(ctx)
	end

	local read_ok, lines = pcall(vim.fn.readfile, ctx.state_path)
	if not read_ok then
		notify("Could not read review state: " .. ctx.state_path, vim.log.levels.WARN)
		return new_state(ctx)
	end

	local decode_ok, decoded = pcall(vim.fn.json_decode, table.concat(lines, "\n"))
	if not decode_ok or type(decoded) ~= "table" then
		notify("Ignoring invalid review state: " .. ctx.state_path, vim.log.levels.WARN)
		return new_state(ctx)
	end

	if type(decoded.reviews) == "table" then
		return merge_nested_reviews(decoded, ctx)
	end
	return ensure_state(decoded, ctx)
end

local function save_state(ctx, state)
	local document = ensure_state(state, ctx)
	document.version = STATE_VERSION
	document.repo = ctx.root
	document.updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")

	local encode_ok, encoded = pcall(vim.fn.json_encode, document)
	if not encode_ok then
		notify("Could not encode review state", vim.log.levels.ERROR)
		return false
	end

	vim.fn.mkdir(vim.fn.fnamemodify(ctx.state_path, ":h"), "p")
	local write_ok, result = pcall(vim.fn.writefile, { encoded }, ctx.state_path)
	if not write_ok or result ~= 0 then
		notify("Could not write review state: " .. ctx.state_path, vim.log.levels.ERROR)
		return false
	end

	return true
end

local function normalize_comment_text(value)
	return vim.trim(tostring(value or ""):gsub("[%r\n]+", " "):gsub("%s+", " "))
end

local function wrap_comment_preview(value, width)
	local text = normalize_comment_text(value)
	width = width or 88
	if #text <= width then
		return { text }
	end

	local lines = {}
	local line = ""
	for word in text:gmatch("%S+") do
		if line == "" then
			line = word
		elseif #line + #word + 1 <= width then
			line = line .. " " .. word
		else
			table.insert(lines, line)
			line = word
		end
	end

	if line ~= "" then
		table.insert(lines, line)
	end
	return lines
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

local function range_label(start_line, end_line)
	if start_line == end_line then
		return tostring(start_line)
	end
	return ("%d-%d"):format(start_line, end_line)
end

local function refresh_buffer(bufnr, file, state)
	if not file or not vim.api.nvim_buf_is_valid(bufnr) then
		return
	end

	vim.api.nvim_buf_clear_namespace(bufnr, NS, 0, -1)
	vim.fn.sign_unplace(SIGN_GROUP, { buffer = bufnr })

	local line_count = vim.api.nvim_buf_line_count(bufnr)
	if line_count == 0 then
		return
	end

	if state.viewed[file] then
		vim.fn.sign_place(0, SIGN_GROUP, "DiffviewReviewViewed", bufnr, { lnum = 1, priority = 25 })
		vim.api.nvim_buf_set_extmark(bufnr, NS, 0, 0, {
			virt_lines = { { { " ✓ VIEWED FILE ", "DiffviewReviewViewedBanner" } } },
			virt_lines_above = true,
			line_hl_group = "DiffviewReviewViewedLine",
			virt_text = { { "✓ viewed", "DiffviewReviewViewedVirt" } },
			virt_text_pos = "right_align",
			priority = 40,
		})
	end

	for _, comment in ipairs(state.comments) do
		if comment.file == file then
			local start_line = tonumber(comment.line)
			local end_line = tonumber(comment.end_line) or start_line
			local display_line = end_line
			if display_line and display_line >= 1 and display_line <= line_count then
				vim.fn.sign_place(0, SIGN_GROUP, "DiffviewReviewComment", bufnr, { lnum = display_line, priority = 30 })
				local virt_lines = {}
				local comment_range = range_label(start_line, end_line)
				for index, text in ipairs(wrap_comment_preview(comment.body)) do
					local prefix = index == 1 and (" 💬 " .. comment_range .. ": ") or "    "
					table.insert(virt_lines, { { prefix .. text, "DiffviewReviewCommentVirt" } })
				end
				vim.api.nvim_buf_set_extmark(bufnr, NS, display_line - 1, 0, {
					virt_lines = virt_lines,
					priority = 30,
				})
			end
		end
	end

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
	set(0, "DiffviewReviewCommentVirt", { fg = "#0969da", italic = true })
	set(0, "DiffviewReviewViewedBanner", { bg = "#1a7f37", fg = "#ffffff", bold = true })
	set(0, "DiffviewReviewViewedLine", { bg = "#e6ffec" })
	set(0, "DiffviewReviewViewedSign", { fg = "#1a7f37", bold = true })
	set(0, "DiffviewReviewViewedVirt", { bg = "#e6ffec", fg = "#1a7f37", bold = true })
end

function M.refresh_visible()
	local view = current_view()
	local ctx = repo_context(view)
	if not ctx then
		return
	end

	local state = load_state(ctx)

	for _, winid in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
		local bufnr = vim.api.nvim_win_get_buf(winid)
		local file = file_for_buffer(bufnr, ctx, view)
		if file then
			refresh_buffer(bufnr, file, state)
		end
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

	refresh_buffer(0, ctx.file, load_state(ctx))
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

	vim.ui.input({
		prompt = ("Review comment %s:%s: "):format(ctx.file, range_label(line, end_line)),
		default = existing and existing.body or "",
	}, save_comment)
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
	if not require_active_diffview(ctx, "toggling viewed state") then
		return
	end
	if not require_repo_context(ctx, "toggling viewed state") then
		return
	end
	if not ctx.file then
		notify("Open a Diffview file before toggling viewed state", vim.log.levels.WARN)
		return
	end

	local state = load_state(ctx)
	state.viewed[ctx.file] = not state.viewed[ctx.file] or nil

	if save_state(ctx, state) then
		local status = state.viewed[ctx.file] and "viewed" or "unviewed"
		notify(("Marked %s as %s"):format(ctx.file, status))
		M.refresh_visible()
	end
end

function M.diffview_keymaps()
	return {
		view = {
			{ "n", "<leader>gda", M.add_comment, { desc = "[G]it [D]iffview [A]dd Review Comment" } },
			{ "x", "<leader>gda", M.add_comment_visual, { desc = "[G]it [D]iffview [A]dd Review Comment" } },
			{ "n", "<leader>gdd", M.delete_comment, { desc = "[G]it [D]iffview [D]elete Review Comment" } },
			{ "n", "<leader>gdv", M.toggle_file_viewed, { desc = "[G]it [D]iffview Toggle File [V]iewed" } },
		},
		file_panel = {
			{ "n", "<leader>gdv", M.toggle_file_viewed, { desc = "[G]it [D]iffview Toggle File [V]iewed" } },
		},
	}
end

function M.setup()
	vim.fn.sign_define("DiffviewReviewComment", { text = "C", texthl = "DiffviewReviewCommentSign" })
	vim.fn.sign_define("DiffviewReviewViewed", { text = "✓", texthl = "DiffviewReviewViewedSign" })

	local group = vim.api.nvim_create_augroup("DiffviewReview", { clear = true })
	vim.api.nvim_create_autocmd("User", {
		group = group,
		pattern = { "DiffviewViewOpened", "DiffviewViewPostLayout", "DiffviewDiffBufWinEnter" },
		callback = function()
			vim.schedule(function()
				M.apply_highlights()
				M.refresh_visible()
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
		desc = "Toggle the current Diffview file viewed state",
	})
end

return M
