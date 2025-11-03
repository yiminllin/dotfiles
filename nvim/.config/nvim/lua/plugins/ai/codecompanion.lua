return {
	"olimorris/codecompanion.nvim",
	dependencies = {
		"nvim-lua/plenary.nvim",
		"nvim-treesitter/nvim-treesitter",
	},
	config = function()
		require("codecompanion").setup({
			strategies = {
				chat = {
					adapter = "copilot",
					model = "default",
				},
			},
			display = {
				chat = {
					show_settings = true,
					width = 0.3,
				},
			},
			opts = {
				log_level = "DEBUG",
			},
		})
		vim.keymap.set(
			{ "n", "v" },
			"<leader>a",
			"<cmd>CodeCompanionChat Toggle<cr>",
			{ noremap = true, silent = true, desc = "[A]I Code Companion Toggle" }
		)
		vim.keymap.set(
			"v",
			"ga",
			"<cmd>CodeCompanionChat Add<cr>",
			{ noremap = true, silent = true, desc = "(Visual mode) [G]: [A]dd to AI Code Companion" }
		)
	end,
}
