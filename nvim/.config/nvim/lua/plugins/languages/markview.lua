return {
	"OXY2DEV/markview.nvim",
	lazy = false,
	config = function()
		local markview = require("markview")
		vim.keymap.set("n", "<leader>m<leader>", "<cmd>Markview Toggle<CR>", { desc = "[M]arkview Toggle" })
	end,
}
