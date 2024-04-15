return {
	"ryanmsnyder/toggleterm-manager.nvim",
	dependencies = {
		"akinsho/nvim-toggleterm.lua",
		"nvim-telescope/telescope.nvim",
		"nvim-lua/plenary.nvim", -- only needed because it's a dependency of telescope
	},
	config = function()
		local actions = require("toggleterm-manager").actions
		require("toggleterm-manager").setup({
			mappings = {
				i = {
					["<C-i>"] = { action = actions.create_term, exit_on_action = false },
					["<CR>"] = { action = actions.open_term, exit_on_action = true },
				},
				n = {
					["<C-i>"] = { action = actions.create_term, exit_on_action = false },
					["<C-d>"] = { action = actions.delete_term, exit_on_action = false },
				},
			},
		})

		vim.keymap.set("n", "<leader>st", ":Telescope toggleterm_manager<Cr>", { desc = "[S]earch [T]erminal" })
	end,
}
