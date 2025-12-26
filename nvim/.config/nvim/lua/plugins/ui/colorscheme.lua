return {
	-- Gruvbox color scheme
	"ellisonleao/gruvbox.nvim",
	lazy = false,
	priority = 1000,
	config = function()
		require("gruvbox").setup({
			contrast = "hard",
			overrides = {
				DiffDelete = { bg = "#f4c2a2" },
				DiffAdd = { bg = "#e6e9c1" },
				DiffChange = { bg = "#cecba1" },
				DiffText = { bg = "#c5e0dc", fg = "#323024", bold = true },
			},
		})
		vim.o.background = "light"
		vim.cmd.colorscheme("gruvbox")
	end,
}
