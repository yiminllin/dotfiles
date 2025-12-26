return {
	"sindrets/diffview.nvim",
	dependencies = {
		{ "lifepillar/vim-solarized8", branch = "neovim" }, -- Pin to master branch
	},
	config = function()
		require("diffview").setup({
			enhanced_diff_hl = true,
		})

		local refresh_ibl = function()
			vim.api.nvim_set_hl(0, "Base2", { fg = "#eee8d5" })
			require("ibl").setup({
				indent = { highlight = "Base2", repeat_linebreak = true },
				scope = { show_start = false, show_end = false },
			})
		end

		vim.api.nvim_create_autocmd("User", {
			pattern = "DiffviewViewOpened",
			callback = function()
				vim.cmd("DiffviewToggleFiles")
				vim.o.background = "light"
				vim.cmd.colorscheme("solarized8_flat")
				vim.api.nvim_set_hl(0, "DiffAdd", { bg = "#e6e9c1" })
				vim.api.nvim_set_hl(0, "DiffChange", { bg = "#cecba1" })
				vim.api.nvim_set_hl(0, "DiffText", { bg = "#c5e0dc", fg = "#323024", bold = true })
				vim.api.nvim_set_hl(0, "DiffDelete", { bg = "#f4c2a2" })
				refresh_ibl()
			end,
		})
		vim.api.nvim_create_autocmd("User", {
			pattern = "DiffviewViewClosed",
			callback = function()
				require("gruvbox").setup({
					contrast = "hard",
					overrides = {
						DiffDelete = { bg = "#f4c2a2" },
						DiffAdd = { bg = "#e6e9c1" },
						DiffChange = { bg = "#cecba1" },
						DiffText = { bg = "#c5e0dc", fg = "#323024", bold = true },
					},
				})
				vim.o.background = "light"
				vim.cmd.colorscheme("gruvbox")
				refresh_ibl()
			end,
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
