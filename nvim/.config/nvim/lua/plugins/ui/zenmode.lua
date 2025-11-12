return {
	"folke/zen-mode.nvim",
	opts = {},
	config = function()
		vim.keymap.set("n", "<leader>z<space>", require("zen-mode").toggle, { desc = "[Z]en Mode" })
	end,
}
