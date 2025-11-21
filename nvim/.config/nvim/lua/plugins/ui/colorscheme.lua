return {
	-- -- Solarized color scheme
	-- "lifepillar/vim-solarized8",
	-- lazy = false,
	-- priority = 1000,
	-- config = function()
	-- 	vim.o.background = "light"
	-- 	vim.cmd.colorscheme("solarized8_flat")
	-- end,
	-- Gruvbox color scheme
	"ellisonleao/gruvbox.nvim",
	lazy = false,
	priority = 1000,
	config = function()
		require("gruvbox").setup({
			contrast = "hard",
			overrides = {
				DiffDelete = { bg = "#f9a89d" },
				DiffAdd = { bg = "#cecb94" },
				DiffChange = { bg = "#e6e9c1" },
				DiffText = { bg = "#a9c4b5", fg = "#323024", bold = true },
			},
		})
		vim.o.background = "light"
		vim.cmd.colorscheme("gruvbox")
	end,
}
