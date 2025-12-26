return { -- Highlight, edit, and navigate code
	"nvim-treesitter/nvim-treesitter",
	branch = "main",
	build = ":TSUpdate",
	lazy = false, -- Treesitter doesn't support lazy-loading
	config = function()
		local ts = require("nvim-treesitter")

		-- Setup treesitter (optional, uses defaults if not called)
		ts.setup({
			-- Directory to install parsers and queries to
			install_dir = vim.fn.stdpath("data") .. "/site",
		})

		-- Install parsers
		local parsers = {
			"bash",
			"c",
			"cpp",
			"html",
			"julia",
			"lua",
			"markdown",
			"markdown_inline",
			"python",
			"rust",
			"vim",
			"vimdoc",
			"diff",
			"git_config",
		}
		ts.install(parsers)

		-- Enable treesitter highlighting for filetypes with parsers
		vim.api.nvim_create_autocmd("FileType", {
			pattern = {
				"bash",
				"sh",
				"zsh",
				"c",
				"cpp",
				"cc",
				"cxx",
				"html",
				"htm",
				"julia",
				"lua",
				"markdown",
				"python",
				"rust",
				"vim",
				"diff",
				"gitconfig",
			},
			callback = function()
				vim.treesitter.start()
			end,
		})

		-- Enable treesitter-based indentation for supported filetypes
		vim.api.nvim_create_autocmd("FileType", {
			pattern = {
				"bash",
				"sh",
				"zsh",
				"c",
				"cpp",
				"cc",
				"cxx",
				"html",
				"htm",
				"julia",
				"lua",
				"markdown",
				"python",
				"rust",
				"vim",
			},
			callback = function()
				vim.bo.indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
			end,
		})
	end,
}
