local output = vim.fn.system({ "bash", vim.env.TMUX_CONTEXT_SCRIPT, "--render" })
local terminal = vim.api.nvim_open_term(0, {})
vim.api.nvim_chan_send(terminal, (output:gsub("\n", "\r\n")))
vim.cmd("normal! gg")
