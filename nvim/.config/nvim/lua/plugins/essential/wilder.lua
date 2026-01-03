return {
	"gelguy/wilder.nvim",
	config = function()
		local wilder = require("wilder")
		wilder.setup({ modes = { ":", "/", "?" } })
		wilder.set_option("pipeline", {
			wilder.branch(
				wilder.cmdline_pipeline({ language = "vim", fuzzy = 1, fuzzy_filter = wilder.vim_fuzzy_filter() })
			),
		})
		wilder.set_option(
			"renderer",
			wilder.popupmenu_renderer(wilder.popupmenu_border_theme({
				pumblend = 20,
				highlighter = wilder.basic_highlighter(),
				highlights = { border = "Normal" },
				border = "rounded",
				left = { " ", wilder.popupmenu_devicons() },
			}))
		)
	end,
}
