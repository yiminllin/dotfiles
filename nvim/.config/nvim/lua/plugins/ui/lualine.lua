return {
	"nvim-lualine/lualine.nvim",
	dependencies = { "nvim-tree/nvim-web-devicons" },
	config = function()
		local function venn_mode()
			if vim.b.venn_enabled then
				return "VENN"
			else
				return ""
			end
		end

		local function lsp_servers()
			local names = vim.tbl_map(function(client)
				local status = client.rust_analyzer_status
				if status then
					if status.health == "ok" then
						return client.name .. " ✓"
					elseif status.health == "warning" or status.health == "error" then
						return client.name .. " !"
					end
				end
				return client.name
			end, vim.lsp.get_clients({ bufnr = 0 }))
			if #names > 0 then
				return table.concat(names, ", ")
			end
			return vim.bo.buftype == "" and vim.bo.filetype ~= "" and "No LSP" or ""
		end

		local lualine = require("lualine")
		vim.api.nvim_create_autocmd({ "LspAttach", "LspDetach", "LspRequest" }, {
			group = vim.api.nvim_create_augroup("lualine-lsp", { clear = true }),
			callback = function(event)
				if event.event == "LspRequest" then
					local method = event.data.request.method
					if method ~= "textDocument/hover" and method ~= "textDocument/implementation" then
						return
					end
				end
				lualine.refresh({ place = { "statusline" } })
			end,
		})

		lualine.setup({
			options = { theme = "gruvbox" },
			sections = {
				lualine_a = {
					"mode",
					venn_mode,
				},
				lualine_c = {
					{ "filename", path = 1 },
				},
				lualine_x = { lsp_servers, require("utils.rust_hover").status, "filetype" },
				lualine_y = { "progress" },
				lualine_z = {},
			},
		})
	end,
}
