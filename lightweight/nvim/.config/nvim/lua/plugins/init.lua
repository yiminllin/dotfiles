-- Lightweight plugins: Snacks (picker, explorer, input, notifier), sleuth, comment, autopairs, colorscheme.
return {
	-- Picker, explorer, input, notifier
	{
		"folke/snacks.nvim",
		priority = 1000,
		lazy = false,
		opts = {
			picker = { enabled = true },
			explorer = { enabled = true },
			input = { enabled = true },
			notifier = { enabled = true, timeout = 3000 },
			styles = { notification = { wo = { wrap = true } } },
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
				"<leader>sg",
				function()
					Snacks.picker.grep()
				end,
				desc = "[S]earch by [G]rep",
			},
			{
				"<leader>sb",
				function()
					Snacks.picker.buffers()
				end,
				desc = "[S]earch [B]uffers",
			},
			{
				"<leader>s.",
				function()
					Snacks.picker.recent()
				end,
				desc = "[S]earch recent files",
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
				"<leader>e",
				function()
					Snacks.explorer()
				end,
				desc = "File [E]xplorer",
			},
		},
	},
	-- Detect tabstop/shiftwidth
	"tpope/vim-sleuth",
	-- Comment toggling
	{ "numToStr/Comment.nvim", opts = {} },
	-- Auto pairs
	{ "windwp/nvim-autopairs", event = "InsertEnter", config = true },
	-- Colorscheme
	{
		"ellisonleao/gruvbox.nvim",
		lazy = false,
		priority = 1000,
		config = function()
			require("gruvbox").setup({})
			vim.o.background = "light"
			vim.cmd.colorscheme("gruvbox")
		end,
	},
}
