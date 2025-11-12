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
					layout = "float",
					width = 0.75,
					height = 0.75,
					border = "rounded",
					title = "CopilotChat",
				},
				prompts = {
					ConciseBot = {
						system_prompt = "Please keep the following answers short, concise, and accurate. Unless followed up by me afterwards, do not need to provide code or example. If possible, make sure the anwser is easy to ready and well-organized, and use bullet points or table if there is a chance. To reiterate, keep the answers short so the reader can digest the main points quickly. The details can be left for follow ups.",
					},
				},
			})
		end,
		vim.keymap.set(
			{ "n", "v" },
			"<leader>c<space>",
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
