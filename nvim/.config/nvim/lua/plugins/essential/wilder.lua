return {
	"gelguy/wilder.nvim",
	config = function()
		local wilder = require("wilder")
		wilder.setup({ modes = { ":", "/", "?" } })
		wilder.set_option("pipeline", {
			wilder.branch(
				wilder.cmdline_pipeline({ language = "python", fuzzy = 1 }),
				wilder.python_search_pipeline({
					pattern = wilder.python_fuzzy_pattern(),
					sorter = wilder.python_difflib_sorter(),
					engine = "re",
				}),
				wilder.python_file_finder_pipeline({
					file_command = { "find", ".", "-type", "f", "-printf", "%P\n" },
					dir_command = { "find", ".", "-type", "d", "-printf", "%P\n" },
					filters = { "fuzzy_filter", "difflib_sorter" },
				})
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
