local M = {}

local STATE_VERSION = 1

local function new_state(ctx)
	return {
		version = STATE_VERSION,
		repo = ctx.root,
		viewed = {},
		comments = {},
		dismissed_guide_comments = {},
		dismissed_github_comments = {},
	}
end

local function ensure_state(state, ctx)
	local dismissed_guide_comments = {}
	if type(state) == "table" and type(state.dismissed_guide_comments) == "table" then
		dismissed_guide_comments = state.dismissed_guide_comments
	end
	local dismissed_github_comments = {}
	if type(state) == "table" and type(state.dismissed_github_comments) == "table" then
		dismissed_github_comments = state.dismissed_github_comments
	end

	return {
		version = STATE_VERSION,
		repo = ctx.root,
		updated_at = type(state) == "table" and state.updated_at or nil,
		viewed = type(state) == "table" and type(state.viewed) == "table" and state.viewed or {},
		comments = type(state) == "table" and type(state.comments) == "table" and state.comments or {},
		dismissed_guide_comments = dismissed_guide_comments,
		dismissed_github_comments = dismissed_github_comments,
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

function M.load(ctx, notify)
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

function M.save(ctx, state, notify)
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

return M
