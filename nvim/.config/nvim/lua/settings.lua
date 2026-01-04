-- Leader key
vim.g.mapleader = " "
vim.g.maplocalleader = " "

-- Settings
vim.opt.mouse = "a" -- Enable mouse mode
vim.opt.clipboard = "unnamedplus" -- Sync clipboard between OS and Neovim
vim.diagnostic.enable(false) -- Disable diagnostic by default

-- Use OSC 52 for clipboard when in SSH session (allows yank to work over SSH)
-- Only use OSC52 for copy operations; paste uses system clipboard to avoid "waiting for OSC52" issues
if os.getenv("SSH_TTY") then
	local osc52 = require("vim.ui.clipboard.osc52")
	vim.g.clipboard = {
		name = "OSC 52",
		copy = {
			["+"] = osc52.copy("+"),
			["*"] = osc52.copy("*"),
		},
		-- Use system clipboard registers directly for paste to avoid OSC52 hanging
		paste = {
			["+"] = function()
				return vim.fn.getreg("+")
			end,
			["*"] = function()
				return vim.fn.getreg("*")
			end,
		},
	}
end
vim.opt.undofile = true -- Save undo history
vim.opt.splitright = true -- Configure new splits orientation
vim.opt.splitbelow = true
vim.opt.updatetime = 250 -- Update time from swap file to disk
vim.opt.timeoutlen = 300 -- Which-key delay
vim.opt.belloff = "all" -- Turn off bell
vim.g.loaded_netrw = 1 -- Disable netrw for nvim-tree
vim.g.loaded_netrwPlugin = 1

-- Appearance
vim.opt.number = true -- Make line numbers default
vim.opt.showmode = false -- Don't show the mode
vim.opt.breakindent = true -- Indent when line wrapped
vim.opt.cursorline = true -- Highlight cursor line number
vim.opt.signcolumn = "yes" -- Keep signcolumn on
vim.opt.scrolloff = 10 -- Minimal number of screen lines to keep above and below the cursor
vim.opt.termguicolors = true -- Enable 24 bit colors
vim.g.gitblame_display_virtual_text = 0 -- Disable gitblame virtual text
vim.opt.showbreak = "↪ " -- Showbreak symbol

-- Indentation
vim.opt.autoindent = true
vim.opt.expandtab = true
vim.opt.tabstop = 4
vim.opt.softtabstop = 4
vim.opt.shiftwidth = 4

-- Search & Substitute
vim.opt.hlsearch = true -- Use highlight on search
vim.opt.incsearch = true -- Preview search live
vim.opt.inccommand = "split" -- Preview substitutions live
vim.opt.ignorecase = true -- Case-insensitive searching UNLESS \C or capital in search
vim.opt.smartcase = true

-- Disable copilot autocomplete
vim.g.copilot_enabled = false

-- Language
vim.g.python3_host_prog = "~/.venv/neovim/bin/python3"
