return {
	"nvim-lualine/lualine.nvim",
	dependencies = { "nvim-tree/nvim-web-devicons" },
	config = function()
		local function venn_mode()
			if vim.b.venn_enabled then
				return "VENN"
			else
				return ""
			end
		end
		require("lualine").setup({
			options = { theme = "gruvbox" },
			sections = {
				lualine_a = {
					"mode",
					venn_mode,
				},
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
