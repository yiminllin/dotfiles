return {
	"ggandor/leap.nvim",
	config = function()
		vim.keymap.set("n", "s", "<Plug>(leap)")
		require("leap").opts.special_keys.prev_target = "<backspace>"
		require("leap").opts.special_keys.prev_group = "<backspace>"
		require("leap.user").set_repeat_keys("<enter>", "<backspace>")
	end,
}
