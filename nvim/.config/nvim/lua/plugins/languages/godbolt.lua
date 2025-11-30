return {
	"p00f/godbolt.nvim",
	config = function()
		require("godbolt").setup({
			languages = {
				cpp = { compiler = "g122", options = {} },
				c = { compiler = "cg122", options = {} },
				rust = { compiler = "r1650", options = {} },
			},
			auto_cleanup = true,
			highlight = {
				cursor = "Visual",
				static = { "#FF6B6B", "#FFB366", "#FFEB99", "#90EE90", "#80EDED", "#6BA3D9", "#D8A5D9" },
			},
			url = "https://godbolt.org",
		})

		vim.keymap.set("n", "<leader>ge", "<cmd>Godbolt<CR>", { desc = "[G]odbolt [E]xplorer" })
	end,
}
