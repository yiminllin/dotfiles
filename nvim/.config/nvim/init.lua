-- kitty-scrollback.nvim: minimal config (kitten sets KITTY_SCROLLBACK_NVIM=true)
if vim.env.KITTY_SCROLLBACK_NVIM == "true" then
	require("settings")
	-- Apply gruvbox + visual highlight when scrollback buffer is ready (FileType fires then)
	vim.api.nvim_create_autocmd("FileType", {
		pattern = "kitty-scrollback",
		callback = function()
			vim.opt.rtp:prepend(vim.fn.stdpath("data") .. "/lazy/gruvbox.nvim")
			vim.cmd.colorscheme("gruvbox")
			vim.api.nvim_set_hl(0, "KittyScrollbackNvimVisual", { link = "Visual" })
			vim.api.nvim_set_hl(0, "KittyScrollbackNvimNormal", { link = "Normal" })
		end,
	})
	return
end

require("settings")
require("keymaps")
require("autocmds")

-- Install plugin manager
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.loop.fs_stat(lazypath) then
	vim.fn.system({
		"git",
		"clone",
		"--filter=blob:none",
		"https://github.com/folke/lazy.nvim.git",
		"--branch=stable", -- latest stable release
		lazypath,
	})
end
vim.opt.rtp:prepend(lazypath)

-- Install & configure plugins
require("lazy").setup("plugins", {
	rocks = {
		hererocks = true,
	},
})
