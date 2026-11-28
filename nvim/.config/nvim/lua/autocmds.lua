-- Automatically show native command-line completion on Neovim 0.12+.
if vim.fn.exists("*wildtrigger") == 1 then
	vim.opt.wildmode = "noselect:lastused,full"
	vim.opt.wildoptions = { "pum", "fuzzy" }
	local group = vim.api.nvim_create_augroup("cmdline_completion", { clear = true })
	local modes = { ":", "/", [[\?]] }
	local popup_options = {}
	vim.api.nvim_create_autocmd({ "CmdlineEnter", "CmdlineLeave" }, {
		group = group,
		pattern = modes,
		callback = function(event)
			local level = vim.v.event.cmdlevel
			local previous = popup_options[level]
			if event.event == "CmdlineEnter" then
				popup_options[level] = { height = vim.o.pumheight, border = vim.o.pumborder }
				vim.o.pumheight = 8
				vim.o.pumborder = "rounded"
			elseif previous then
				vim.o.pumheight = previous.height
				vim.o.pumborder = previous.border
				popup_options[level] = nil
			end
		end,
	})
	vim.api.nvim_create_autocmd("CmdlineChanged", {
		group = group,
		pattern = modes,
		callback = function()
			vim.fn.wildtrigger()
		end,
	})
end

-- Highlight when yanking (copying) text
vim.api.nvim_create_autocmd("TextYankPost", {
	desc = "Highlight when yanking (copying) text",
	group = vim.api.nvim_create_augroup("highlight_yank", { clear = true }),
	callback = function()
		vim.highlight.on_yank()
	end,
})

vim.api.nvim_create_autocmd("LspAttach", {
	group = vim.api.nvim_create_augroup("lsp-inspection", { clear = true }),
	callback = function(event)
		local client = vim.lsp.get_client_by_id(event.data.client_id)
		if not client then
			return
		end

		local filetype = vim.bo[event.buf].filetype
		local buffer_name = vim.api.nvim_buf_get_name(event.buf)
		if
			client.name == "rust_analyzer"
			and (
				vim.startswith(buffer_name, "diffview://")
				or filetype == "DiffviewFiles"
				or filetype == "DiffviewFileHistory"
			)
		then
			-- Neovim records the attachment after LspAttach returns.
			vim.schedule(function()
				if vim.lsp.buf_is_attached(event.buf, client.id) then
					vim.lsp.buf_detach_client(event.buf, client.id)
				end
			end)
			return
		end

		if client:supports_method("textDocument/documentHighlight", event.buf) then
			vim.api.nvim_create_autocmd({ "CursorHold", "CursorHoldI" }, {
				buffer = event.buf,
				callback = vim.lsp.buf.document_highlight,
			})
			vim.api.nvim_create_autocmd({ "CursorMoved", "CursorMovedI" }, {
				buffer = event.buf,
				callback = vim.lsp.buf.clear_references,
			})
		end
	end,
})
