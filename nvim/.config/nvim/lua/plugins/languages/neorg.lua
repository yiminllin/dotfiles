return {
	"nvim-neorg/neorg",
	dependencies = { "pysan3/pathlib.nvim", "luarocks.nvim" },
	lazy = false, -- Disable lazy loading as some `lazy.nvim` distributions set `lazy = true` by default
	version = "*", -- Pin Neorg to the latest stable release
	config = function()
		require("neorg").setup({
			load = {
				["core.defaults"] = {},
				["core.completion"] = { config = { engine = "nvim-cmp", name = "[Norg]" } },
				["core.integrations.nvim-cmp"] = {},
				["core.concealer"] = {},
				["core.keybinds"] = {
					-- https://github.com/nvim-neorg/neorg/blob/main/lua/neorg/modules/core/keybinds/keybinds.lua
					config = {
						default_keybinds = true,
						neorg_leader = "<Leader><Leader>",
					},
				},
			},
		})
	end,
}
