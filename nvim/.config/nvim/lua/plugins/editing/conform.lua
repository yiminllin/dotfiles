return {
	-- Autoformat
	"stevearc/conform.nvim",
	opts = {
		notify_on_error = true,
		format_on_save = {
			timeout_ms = 500,
			lsp_fallback = true,
		},
		formatters_by_ft = {
			lua = { "stylua" },
			cpp = { "clang_format" },
			python = { "isort", "black" },
			rust = { "rustfmt", lsp_format = "fallback" },
			markdown = { "prettier" },
		},
	},
}
