return {
	"neovim/nvim-lspconfig",
	dependencies = { "mason-org/mason.nvim" },
	config = function()
		require("mason").setup()

		vim.lsp.config("clangd", {
			cmd = { "clangd", "--offset-encoding=utf-16" },
		})
		vim.lsp.config("lua_ls", {
			settings = {
				Lua = {
					runtime = { version = "LuaJIT" },
					workspace = {
						checkThirdParty = false,
						library = {
							"${3rd}/luv/library",
							unpack(vim.api.nvim_get_runtime_file("", true)),
						},
					},
				},
			},
		})

		vim.lsp.config("rust_analyzer", {
			settings = { ["rust-analyzer"] = { hover = { show = { fields = 25 } } } },
			handlers = {
				["experimental/serverStatus"] = function(err, status, ctx)
					local client = vim.lsp.get_client_by_id(ctx.client_id)
					if not err and client and type(status) == "table" then
						client.rust_analyzer_status = status
					end
				end,
			},
		})

		vim.api.nvim_create_user_command("RustAnalyzerStatus", function()
			local clients = vim.lsp.get_clients({ bufnr = 0, name = "rust_analyzer" })
			if #clients == 0 then
				vim.notify("Rust Analyzer is not attached to this buffer")
			end
			for _, client in ipairs(clients) do
				local status = client.rust_analyzer_status
				local text = status and status.health or "no health report received"
				if status and type(status.message) == "string" and status.message ~= "" then
					text = text .. ": " .. status.message
				end
				vim.notify("Rust Analyzer: " .. text)
			end
		end, { desc = "Show Rust Analyzer health and details" })

		vim.lsp.enable({ "clangd", "lua_ls", "julials", "rust_analyzer", "pyright", "marksman" })
	end,
}
