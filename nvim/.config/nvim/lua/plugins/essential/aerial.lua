return {
	"stevearc/aerial.nvim",
	dependencies = {
		"nvim-treesitter/nvim-treesitter",
		"nvim-tree/nvim-web-devicons",
		"folke/snacks.nvim",
	},
	config = function()
		require("aerial").setup({
			on_attach = function(bufnr)
				vim.keymap.set("n", "(", "<cmd>AerialPrev<CR>", { buffer = bufnr, desc = "Aerial (Skim) Prev" })
				vim.keymap.set("n", ")", "<cmd>AerialNext<CR>", { buffer = bufnr, desc = "Aerial (Skim) Next" })
			end,
		})

		vim.keymap.set("n", "<leader>si", function()
			require("aerial").snacks_picker()
		end, { desc = "[S]earch Sk[i]m" })
	end,
}
