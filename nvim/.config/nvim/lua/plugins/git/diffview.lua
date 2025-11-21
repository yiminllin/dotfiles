return {
	"sindrets/diffview.nvim",
	config = function()
		require("diffview").setup({
			enhanced_diff_hl = true,
		})
	end,
	keys = {
		{
			"<leader>gdc",
			"<cmd>DiffviewOpen<cr>",
			mode = { "n", "v" },
			desc = "[G]it [D]iffview Open [C]urrent Changes",
		},
		{
			"<leader>gdm",
			"<cmd>DiffviewOpen origin/main...HEAD<cr>",
			mode = { "n", "v" },
			desc = "[G]it [D]iffview Open [M]ain branch",
		},
		{
			"<leader>gdx",
			"<cmd>DiffviewClose<cr>",
			mode = { "n", "v" },
			desc = "[G]it [D]iffview [X]Close",
		},
		{
			"<leader>gde",
			"<cmd>DiffviewToggleFiles<cr>",
			mode = { "n", "v" },
			desc = "[G]it [D]iffview Toggle File [E]xplorer",
		},
		{
			"<leader>gdr",
			"<cmd>DiffviewRefresh<cr>",
			mode = { "n", "v" },
			desc = "[G]it [D]iffview [R]efresh",
		},
		{ "<leader>gf", "<cmd>DiffviewFileHistory<cr>", mode = { "n", "v" }, desc = "[G]it Diffview [F]ile History" },
	},
}
