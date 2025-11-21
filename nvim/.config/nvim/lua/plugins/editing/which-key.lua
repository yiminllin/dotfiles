return {
	-- Show pending keybinds.
	"folke/which-key.nvim",
	event = "VimEnter",
	config = function()
		require("which-key").setup()

		-- Document existing key chains
		require("which-key").register({
			["<leader>s"] = { name = "[S]earch", _ = "which_key_ignore" },
			["<leader>g"] = { name = "[G]it", _ = "which_key_ignore" },
			["<leader>gy"] = { name = "[G]itlink [Y]ank", _ = "which_key_ignore" },
		})
	end,
}
