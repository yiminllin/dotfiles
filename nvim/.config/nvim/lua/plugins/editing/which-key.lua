return {
	-- Show pending keybinds.
	"folke/which-key.nvim",
	event = "VimEnter",
	config = function()
		require("which-key").setup()

		local wk = require("which-key")
		-- Document existing key chains
		wk.add({
			{ "<leader>c", group = "Open[C]ode AI assistant" },
			{ "<leader>d", group = "[D]ebugPrint" },
			{ "<leader>ds", group = "[D]ebugPrint [S]urround" },
			{ "<leader>g", group = "[G]it" },
			{ "<leader>gy", group = "[G]it [Y]ank" },
			{ "<leader>gd", group = "[G]it [D]iff" },
			{ "<leader>gl", group = "[G]it [L]ink" },
			{ "<leader>h", group = "Git [H]unk" },
			{ "<leader>l", group = "[L]oad" },
			{ "<leader>m", group = "[M]arkview" },
			{ "<leader>o", group = "[O]il / [O]pen" },
			{ "<leader>s", group = "[S]earch" },
			{ "<leader>t", group = "[T]rouble" },
			{ "<leader>v", group = "[V]enn / Diagram" },
			{ "<leader>z", group = "[Z]ettlekasten / [Z]en" },
		})
	end,
}
