return {
	"folke/snacks.nvim",
	priority = 1000,
	lazy = false,
	---@type snacks.Config
	opts = {
		---------------
		-- Essential --
		---------------
		-- Picker
		picker = { enabled = true },
		-- File explorer, picker
		explorer = { enabled = true },
		-----------------
		-- Performance --
		-----------------
		-- Prevent LSP and treesitter attaching to big files
		bigfile = { enabled = true },

		-- Render file before loading plugins
		quickfile = { enabled = true },

		--------
		-- UI --
		--------
		-- Better vim.ui.input
		input = { enabled = true },
		-- Better vim.notify
		notifier = {
			enabled = true,
			timeout = 3000,
		},
		styles = {
			notification = {
				wo = { wrap = true }, -- Wrap notifications
			},
		},
	},
	keys = {
		{
			"<leader>sh",
			function()
				Snacks.picker.help()
			end,
			desc = "[S]earch [H]elp",
		},
		{
			"<leader>sk",
			function()
				Snacks.picker.keymaps()
			end,
			desc = "[S]earch [K]eymaps",
		},
		{
			"<leader>sf",
			function()
				Snacks.picker.files()
			end,
			desc = "[S]earch [F]iles",
		},
		{
			"<leader>sw",
			function()
				Snacks.picker.grep_word()
			end,
			desc = "[S]earch current [W]ord",
			mode = { "n", "x" },
		},
		{
			"<leader>sb",
			function()
				Snacks.picker.buffers()
			end,
			desc = "[S]earch Open [B]uffers",
		},
		{
			"<leader>sg",
			function()
				Snacks.picker.grep()
			end,
			desc = "[S]earch by [G]rep",
		},
		{
			"<leader>e",
			function()
				Snacks.explorer()
			end,
			desc = "File [E]xplorer",
		},
		{
			"<leader>/",
			function()
				Snacks.picker.lines()
			end,
			desc = "[/] Fuzzily search in current buffer",
		},
		{
			"<leader>sn",
			function()
				Snacks.picker.files({ cwd = vim.fn.stdpath("config") })
			end,
			desc = "[S]earch [N]eovim Config File",
		},
		{
			"<leader><leader>",
			function()
				Snacks.picker.git_status()
			end,
			desc = "Git Status",
		},
		{
			"<leader>sm",
			function()
				Snacks.picker.marks()
			end,
			desc = "[S]earch [M]arks",
		},
		-- LSP
		{
			"<leader>ss",
			function()
				Snacks.picker.lsp_symbols()
			end,
			desc = "[S]earch LSP [S]ymbols",
		},
		{
			"<leader>sS",
			function()
				Snacks.picker.lsp_workspace_symbols()
			end,
			desc = "[S]earch LSP Workspace [S]ymbols",
		},
		{
			"gd",
			function()
				Snacks.picker.lsp_definitions()
			end,
			desc = "[G]oto [D]efinition",
		},
		{
			"gD",
			function()
				Snacks.picker.lsp_declarations()
			end,
			desc = "[G]oto [D]eclaration",
		},
		{
			"gr",
			function()
				Snacks.picker.lsp_references()
			end,
			nowait = true,
			desc = "[G]oto [R]eferences",
		},
		{
			"gI",
			function()
				Snacks.picker.lsp_implementations()
			end,
			desc = "[G]oto [I]mplementation",
		},
		{
			"gt",
			function()
				Snacks.picker.lsp_type_definitions()
			end,
			desc = "[G]oto [T]ype Definition",
		},
		{
			"gai",
			function()
				Snacks.picker.lsp_incoming_calls()
			end,
			desc = "[G]oto C[a]lls [I]ncoming",
		},
		{
			"gao",
			function()
				Snacks.picker.lsp_outgoing_calls()
			end,
			desc = "[G]oto C[a]lls [O]utgoing",
		},
	},
}
