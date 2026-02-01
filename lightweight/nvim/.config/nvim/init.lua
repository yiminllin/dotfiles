-- Lightweight Neovim: basic editing + searching only (no LSP, no tmux/kitty/cursor).
require("settings")
require("keymaps")
require("autocmds")

local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.loop.fs_stat(lazypath) then
  vim.fn.system({
    "git",
    "clone",
    "--filter=blob:none",
    "https://github.com/folke/lazy.nvim.git",
    "--branch=stable",
    lazypath,
  })
  if not vim.loop.fs_stat(lazypath) then
    vim.notify("Failed to clone lazy.nvim. Check network and git.", vim.log.levels.ERROR)
    return
  end
end
vim.opt.rtp:prepend(lazypath)

require("lazy").setup("plugins")
