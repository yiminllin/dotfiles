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
			local opts
			if vim.bo.filetype == "markdown" then
				local bufnr = vim.api.nvim_get_current_buf()
				opts = {
					-- Preview the same buffer that provides the heading ranges, including unsaved edits.
					transform = function(item)
						item.buf = bufnr
					end,
				}
			end
			require("aerial").snacks_picker(opts)
		end, { desc = "[S]earch Sk[i]m" })
	end,
}
