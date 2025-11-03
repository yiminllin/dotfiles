return {
	{
		"CopilotC-Nvim/CopilotChat.nvim",
		dependencies = {
			{ "nvim-lua/plenary.nvim", branch = "master" },
		},
		build = "make tiktoken",
		config = function()
			require("CopilotChat").setup({
				opts = {
					model = "claude-sonnet-4",
					temperature = 0.8,
					auto_insert_mode = true,
				},
				window = {
					layout = "vertical",
					width = 0.3,
					border = "rounded",
					title = "CopilotChat",
				},
			})
		end,
		vim.keymap.set(
			{ "n", "v" },
			"<leader>c",
			"<cmd>CopilotChatToggle<cr>",
			{ noremap = true, silent = true, desc = "[C]opilotChat Toggle" }
		),
		vim.keymap.set(
			"v",
			"cr",
			"<cmd>CopilotChatReview<cr>",
			{ noremap = true, silent = true, desc = "(Visual mode) [C]opilotChat [R]eview" }
		),
		vim.keymap.set(
			"v",
			"ce",
			"<cmd>CopilotChatExplain<cr>",
			{ noremap = true, silent = true, desc = "(Visual mode) [C]opilotChat [E]xplain" }
		),
		vim.keymap.set(
			"v",
			"cd",
			"<cmd>CopilotChatDocs<cr>",
			{ noremap = true, silent = true, desc = "(Visual mode) [C]opilotChat [D]ocs" }
		),
		vim.keymap.set(
			"v",
			"ct",
			"<cmd>CopilotChatTests<cr>",
			{ noremap = true, silent = true, desc = "(Visual mode) [C]opilotChat [T]ests" }
		),
	},
}
