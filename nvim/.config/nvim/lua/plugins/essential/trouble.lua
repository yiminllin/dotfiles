return {
	"folke/trouble.nvim",
	opts = {}, -- for default options, refer to the configuration section for custom setup.
	cmd = "Trouble",
	keys = {
		{
			"<leader>tg",
			"<cmd>Trouble diagnostics toggle<cr>",
			desc = "[T]rouble Diagnostics [G]lobal",
		},
		{
			"<leader>tb",
			"<cmd>Trouble diagnostics toggle filter.buf=0<cr>",
			desc = "[T]rouble Diagnostics [B]uffer",
		},
		{
			"<leader>tl",
			"<cmd>Trouble loclist toggle<cr>",
			desc = "[T]rouble [L]oclist",
		},
		{
			"<leader>tq",
			"<cmd>Trouble qflist toggle<cr>",
			desc = "[T]rouble [Q]flist",
		},
	},
}
