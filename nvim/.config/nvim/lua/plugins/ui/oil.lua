return {
	"stevearc/oil.nvim",
	dependencies = { "nvim-tree/nvim-web-devicons" },
	config = function()
		require("oil").setup({
			columns = { "icon" },
			view_options = { show_hidden = true },
			float = {
				border = "rounded",
			},
			confirmation = {
				border = "rounded",
			},
		})
		vim.keymap.set("n", "<leader>o", require("oil").toggle_float, { desc = "[O]pen Parent Directory" })
	end,
}
