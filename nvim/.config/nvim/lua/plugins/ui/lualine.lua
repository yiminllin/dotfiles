return {
	"nvim-lualine/lualine.nvim",
	dependencies = { "nvim-tree/nvim-web-devicons" },
	config = function()
		require("lualine").setup({
			options = { theme = "gruvbox" },
			sections = {
				lualine_c = {
					{ "filename", path = 1 },
				},
				lualine_x = { "filetype" },
				lualine_y = { "progress" },
				lualine_z = {},
			},
		})
	end,
}
