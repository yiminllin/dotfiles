return {
	{
		"quarto-dev/quarto-nvim",
		dependencies = {
			"GCBallesteros/jupytext.nvim",
			"benlubas/molten-nvim",
			"jmbuhr/otter.nvim",
			"hrsh7th/nvim-cmp",
			"neovim/nvim-lspconfig",
			"nvim-treesitter/nvim-treesitter",
		},
		config = function()
			require("quarto").setup({
				lspFeatures = {
					languages = { "python", "julia", "bash", "lua", "rust" },
					chunks = "all",
					diagnostics = {
						enable = true,
						triggers = { "BufWritePost" },
					},
					completion = { enabled = true },
				},
				keymap = {
					hover = "H",
					definition = "gd",
					references = "gr",
					format = "<leader>gf",
				},
				codeRunner = {
					enabled = true,
					default_method = "molten",
				},
			})
			local runner = require("quarto.runner")
			vim.keymap.set("n", "<leader>qr", runner.run_cell, { desc = "[Q]uarto [R]un Cell", silent = true })
			vim.keymap.set("n", "<leader>qa", function()
				runner.run_all(true)
			end, { desc = "[Q]uarto Run [A]ll Cells of All Languages", silent = true })
		end,
	},

	{
		"GCBallesteros/jupytext.nvim",
		config = function()
			require("jupytext").setup({
				style = "markdown",
				output_extension = "md",
				force_ft = "markdown",
				custom_language_formatting = {
					python = {
						extension = "qmd",
						style = "quarto",
						force_ft = "quarto",
					},
					julia = {
						extension = "qmd",
						style = "quarto",
						force_ft = "quarto",
					},
				},
			})
		end,
	},

	{
		"benlubas/molten-nvim",
		version = "^1.0.0", -- use version <2.0.0 to avoid breaking changes
		dependencies = { "3rd/image.nvim" },
		build = ":UpdateRemotePlugins",
		init = function()
			-- Settings
			vim.g.molten_image_provider = "image.nvim"
			vim.g.molten_virt_text_output = true
			vim.g.molten_output_win_max_height = 200
			vim.g.molten_virt_lines_off_by_1 = true
			vim.g.molten_output_show_exec_time = true

			-- Key maps
			vim.keymap.set("n", "<leader>mi", ":MoltenInit<CR>", { desc = "[M]olten [I]nit", silent = true })
			vim.keymap.set(
				"n",
				"<leader>ms",
				":MoltenInterrupt<CR>",
				{ desc = "[M]olten [S]top (Interrupt)", silent = true }
			)
		end,
	},

	{
		"3rd/image.nvim",
		opts = {
			backend = "kitty",
			max_width = 100,
			max_height = 12,
			max_height_window_percentage = math.huge,
			max_width_window_percentage = math.huge,
			window_overlap_clear_enabled = true,
			window_overlap_clear_ft_ignore = { "cmp_menu", "cmp_docs", "" },
		},
	},
}
