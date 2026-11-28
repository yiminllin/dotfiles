local M = {}
local api = vim.api
local util = vim.lsp.util

local function parse_file(uri)
	if not vim.startswith(uri, "file://") then
		return
	end
	local path = vim.uri_to_fname(uri)
	local buf = vim.fn.bufnr(path)
	local lines = api.nvim_buf_is_loaded(buf) and api.nvim_buf_get_lines(buf, 0, -1, false) or vim.fn.readfile(path)
	local source = table.concat(lines, "\n")
	local tree = vim.treesitter.get_string_parser(source, "rust"):parse()[1]
	return { root = tree:root(), lines = lines, source = source }
end

local function before_body(node, body, source)
	local _, _, start_byte = node:start()
	local _, _, end_byte = body:start()
	return vim.trim(source:sub(start_byte + 1, end_byte))
end

local function find_impl(file, pos, encoding)
	local line = file.lines[pos.line + 1]
	if not line then
		return
	end
	local col = vim.str_byteindex(line, encoding, pos.character, false)
	local node = file.root:named_descendant_for_range(pos.line, col, pos.line, col)
	while node and node:type() ~= "impl_item" do
		node = node:parent()
	end
	return node
end

local function signatures(node, source)
	local body = node:field("body")[1]
	if not body then
		return
	end
	local methods = {}
	for item in body:iter_children() do
		local method_body = item:type() == "function_item" and item:field("body")[1]
		if method_body then
			methods[#methods + 1] = "  " .. before_body(item, method_body, source)
		end
	end
	if #methods > 0 then
		return table.concat({ before_body(node, body, source), unpack(methods) }, "\n")
	end
end

local function impl_type(node)
	local target = node:field("type")[1]
	if target and target:type() == "generic_type" then
		target = target:field("type")[1]
	end
	if target and target:type() == "scoped_type_identifier" then
		target = target:field("name")[1]
	end
	return target
end

local function append_methods(lines, locations, encoding, name)
	local files, seen, blocks = {}, {}, {}
	for _, location in ipairs(locations) do
		local uri = location.targetUri or location.uri
		local range = location.targetSelectionRange or location.range
		if files[uri] == nil then
			local ok, file = pcall(parse_file, uri)
			files[uri] = ok and file or false
		end
		local file = files[uri]
		local node = file and find_impl(file, range.start, encoding)
		local target = node and impl_type(node)
		if target and vim.treesitter.get_node_text(target, file.source) == name then
			local _, _, start = node:start()
			local key = uri .. ":" .. start
			if not seen[key] then
				seen[key] = true
				blocks[#blocks + 1] = signatures(node, file.source)
			end
		end
	end
	if #blocks > 0 then
		vim.list_extend(lines, { "", "### Methods", "", "```rust" })
		vim.list_extend(lines, vim.split(table.concat(blocks, "\n\n"), "\n", { plain = true }))
		lines[#lines + 1] = "```"
	end
end

function M.status()
	local buf = api.nvim_get_current_buf()
	local methods = vim.b[buf].rust_hover_methods_request
	for _, client in ipairs(vim.lsp.get_clients({ bufnr = buf })) do
		for id, request in pairs(client.requests) do
			local hover = request.method == "textDocument/hover"
			local hover_methods = methods and methods.client_id == client.id and methods.id == id
			if request.bufnr == buf and request.type == "pending" and (hover or hover_methods) then
				return "Hover…"
			end
		end
	end
	return ""
end

function M.hover(opts)
	local buf, win = api.nvim_get_current_buf(), api.nvim_get_current_win()
	local client =
		vim.lsp.get_clients({ bufnr = buf, name = "rust_analyzer", method = "textDocument/implementation" })[1]
	if not client then
		return vim.lsp.buf.hover(opts)
	end
	local ok, node = pcall(function()
		vim.treesitter.get_parser(buf, "rust"):parse()
		local name = vim.treesitter.get_node({ lang = "rust" })
		if not name then
			return
		end
		if name:type() == "type_identifier" then
			return name
		end
		-- Rust parses the type in `Type::method()` as an expression path.
		local parent = name:parent()
		if
			name:type() == "identifier"
			and parent
			and parent:type() == "scoped_identifier"
			and name == parent:field("path")[1]
		then
			return name
		end
	end)
	if not ok or not node then
		return vim.lsp.buf.hover(opts)
	end

	local name = vim.treesitter.get_node_text(node, buf)
	local cursor, tick = api.nvim_win_get_cursor(win), api.nvim_buf_get_changedtick(buf)
	local params = util.make_position_params(win, client.offset_encoding)
	local function still_here()
		return api.nvim_get_current_win() == win
			and api.nvim_get_current_buf() == buf
			and api.nvim_buf_get_changedtick(buf) == tick
			and vim.deep_equal(api.nvim_win_get_cursor(win), cursor)
	end

	local function show(lines)
		if still_here() then
			util.open_floating_preview(
				lines,
				"markdown",
				vim.tbl_extend("force", opts, { focus_id = "textDocument/hover" })
			)
		end
	end

	local requested = client:request("textDocument/hover", params, function(err, result)
		if not still_here() then
			return
		end
		if err or not result or not result.contents then
			return vim.lsp.buf.hover(opts)
		end
		local lines = util.convert_input_to_markdown_lines(result.contents)
		local pending, id = client:request("textDocument/implementation", params, function(impl_err, locations)
			if not still_here() then
				return
			end
			if not impl_err and type(locations) == "table" then
				append_methods(lines, locations.uri and { locations } or locations, client.offset_encoding, name)
			end
			show(lines)
		end, buf)
		if pending and id then
			vim.b[buf].rust_hover_methods_request = { client_id = client.id, id = id }
		end
		if not pending then
			show(lines)
		end
	end, buf)
	if not requested then
		vim.lsp.buf.hover(opts)
	end
end

return M
