return {
	"folke/zen-mode.nvim",
	opts = {},
	config = function()
		vim.keymap.set("n", "<leader>z", require("zen-mode").toggle, { desc = "[Z]en Mode" })
	end,
}
