return {
	"alexander-born/bazel.nvim",
	dependencies = { "nvim-treesitter/nvim-treesitter" },
	config = function()
		vim.api.nvim_create_autocmd("FileType", {
			pattern = "bzl",
			callback = function()
				vim.keymap.set("n", "gd", vim.fn.GoToBazelDefinition, { buffer = true, desc = "[G]oto [D]efinition" })
			end,
		})
		vim.keymap.set("n", "<Leader>b", vim.fn.GoToBazelTarget, { desc = "[G]oto [B]azel Build File" })
	end,
}
