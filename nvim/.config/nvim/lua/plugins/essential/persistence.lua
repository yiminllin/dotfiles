return {
	"folke/persistence.nvim",
	config = function()
		require("persistence").setup({
			dir = vim.fn.stdpath("state") .. "/sessions/",
		})
		vim.api.nvim_create_autocmd("VimEnter", {
			desc = "Restore nvim session in the workspace",
			group = vim.api.nvim_create_augroup("restore_session", { clear = true }),
			callback = function()
				if vim.fn.argc() == 0 then
					require("persistence").load()
				end
			end,
			nested = true,
		})
		vim.keymap.set("n", "<leader>ls", function()
			require("persistence").load()
		end, { desc = "[L]oad [S]ession" })
	end,
}
