return { -- Highlight, edit, and navigate code
	"nvim-treesitter/nvim-treesitter",
	build = ":TSUpdate",
	opts = {
		ensure_installed = {
			"bash",
			"c",
			"cpp",
			"html",
			"lua",
			"markdown",
			"markdown_inline",
			"vim",
			"vimdoc",
			"diff",
			"git_config",
		},
		auto_install = true,
		highlight = { enable = true },
		indent = { enable = true },
	},
}
