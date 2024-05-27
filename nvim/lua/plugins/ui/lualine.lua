return {
	"nvim-lualine/lualine.nvim",
	dependencies = { "nvim-tree/nvim-web-devicons" },
	config = function()
		require("lualine").setup({
			options = { theme = "gruvbox" },
			sections = {
				lualine_c = {
					"filename",
					{ require("gitblame").get_current_blame_text, cond = require("gitblame").is_blame_text_available },
				},
				lualine_x = { "filetype" },
				lualine_y = { "progress" },
				lualine_z = {},
			},
		})
	end,
}
