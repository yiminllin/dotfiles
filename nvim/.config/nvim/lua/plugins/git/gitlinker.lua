return {
	"linrongbin16/gitlinker.nvim",
	dependencies = { "nvim-lua/plenary.nvim" },
	cmd = "GitLink",
	opts = {},
	keys = {
		{ "<leader>gyl", "<cmd>GitLink<cr>", mode = { "n", "v" }, desc = "[G]itLink [Y]ank [L]ink" },
		{ "<leader>gyb", "<cmd>GitLink blame<cr>", mode = { "n", "v" }, desc = "[G]itLink [Y]ank [B]lame" },
	},
}
