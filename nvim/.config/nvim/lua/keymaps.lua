-- [[ Basic Keymaps ]]
-- Set highlight on search, but clear on pressing <Esc> in normal mode
vim.keymap.set("n", "<Esc>", "<cmd>nohlsearch<CR>")

-- Diagnostic keymaps
vim.keymap.set("n", "[d", vim.diagnostic.goto_prev, { desc = "Go to previous [D]iagnostic message" })
vim.keymap.set("n", "]d", vim.diagnostic.goto_next, { desc = "Go to next [D]iagnostic message" })
vim.keymap.set("n", "<leader>e", vim.diagnostic.open_float, { desc = "Show diagnostic [E]rror messages" })
vim.keymap.set("n", "<leader>q", vim.diagnostic.setloclist, { desc = "Open diagnostic [Q]uickfix list" })
local diagnostics_active = true
vim.keymap.set("n", "<leader>d<Tab>", function()
	if diagnostics_active then
		vim.diagnostic.enable(false)
	else
		vim.diagnostic.enable()
	end
	diagnostics_active = not diagnostics_active
end, { desc = "[D]iagnostic [T]oggle" })

vim.keymap.set("t", "<Esc><Esc>", "<C-\\><C-n>", { desc = "Exit terminal mode" })

-- Use Ctrl+Shift+<arrow> to set size of splits
vim.keymap.set("n", "<C-S-left>", "<c-w>5<")
vim.keymap.set("n", "<C-S-right>", "<c-w>5>")
vim.keymap.set("n", "<C-S-up>", "<C-W>+")
vim.keymap.set("n", "<C-S-down>", "<C-W>-")

-- Use Alt+<jk> to go through quickfix list
vim.keymap.set("n", "<M-j>", "<cmd>cnext<CR>")
vim.keymap.set("n", "<M-k>", "<cmd>cprev<CR>")
