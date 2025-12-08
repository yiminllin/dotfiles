return {
	"OXY2DEV/markview.nvim",
	lazy = false,
	dependencies = {
		"3rd/image.nvim",
	},
	config = function()
		vim.keymap.set("n", "<leader>m<leader>", "<cmd>Markview Toggle<CR>", { desc = "[M]arkview Toggle" })
	end,
}
