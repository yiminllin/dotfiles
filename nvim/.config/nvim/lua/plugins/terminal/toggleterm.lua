return {
	"akinsho/toggleterm.nvim",
	version = "*",
	config = function()
		require("toggleterm").setup({ shade_terminals = false, direction = "float" })
		vim.keymap.set("t", "<Esc>", "<cmd>q<cr>")
	end,
}
