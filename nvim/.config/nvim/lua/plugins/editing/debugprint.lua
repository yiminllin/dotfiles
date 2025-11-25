return {
	"andrewferrier/debugprint.nvim",
	dependencies = {
		"folke/snacks.nvim",
	},
	lazy = false, -- Required to make line highlighting work before debugprint is first used
	opts = {
		keymaps = {
			normal = {
				plain_below = "<leader>dp",
				plain_above = "<leader>dP",
				variable_below = "<leader>dv",
				variable_above = "<leader>dV",
				surround_plain = "<leader>dsp",
				surround_variable = "<leader>dsv",
				toggle_comment_debug_prints = "<leader>dc",
				delete_debug_prints = "<leader>dd",
			},
			visual = {
				variable_below = "<leader>dv",
				variable_above = "<leader>dV",
			},
		},
	},
}
