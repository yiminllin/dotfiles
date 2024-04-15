return {
	-- Solarized color scheme
	"lifepillar/vim-solarized8",
	lazy = false,
	priority = 1000,
	config = function()
		vim.o.background = "light"
		vim.cmd.colorscheme("solarized8_flat")
	end,
}
