return {
	"lukas-reineke/indent-blankline.nvim",
	main = "ibl",
	config = function()
		local hooks = require("ibl.hooks")
		hooks.register(hooks.type.HIGHLIGHT_SETUP, function()
			vim.api.nvim_set_hl(0, "Base2", { fg = "#eee8d5" })
		end)
		require("ibl").setup({
			indent = { highlight = "Base2", repeat_linebreak = true },
			scope = { show_start = false, show_end = false },
		})
	end,
}
