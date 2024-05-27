return {
	"nvim-tree/nvim-tree.lua",
	dependencies = {
		"nvim-tree/nvim-web-devicons",
	},
	config = function()
		require("nvim-tree").setup({
			view = {
				number = true,
				width = {
					min = 30,
					max = -1,
					padding = 5,
				},
				float = {
					enable = true,
				},
			},
		})
		local api = require("nvim-tree.api")
		local nvimtree_toggle_findfile = function(opt)
			api.tree.toggle({ path = opt and opt.path, update_root = false, find_file = true, focus = true })
		end
		vim.keymap.set("n", "<leader>se", nvimtree_toggle_findfile, { desc = "[S]earch Nvim-Tree [E]xplorer" })
	end,
}
