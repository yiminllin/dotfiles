return {
	"NickvanDyke/opencode.nvim",
	cond = vim.fn.executable("codex") == 0, -- Prefer Codex CLI when available.
	dependencies = {
		{ "folke/snacks.nvim", opts = { input = {}, picker = {}, terminal = {} } },
	},
	config = function()
		vim.g.opencode_opts = {
			provider = {
				enabled = "tmux",
				tmux = {
					options = "-h", -- options to pass to `tmux split-window`, horizontal split
				},
			},
		}

		vim.o.autoread = true

		-- Recommended/example keymaps.
		local opencode = require("opencode")
		vim.keymap.set({ "n" }, "<leader>c<leader>", function()
			opencode.select()
		end, { desc = "Open[C]ode Toggle" })
		vim.keymap.set({ "n", "x" }, "<leader>cp", function()
			opencode.ask(" ", { submit = true })
		end, { desc = "Open[C]ode [P]rompt" })
		vim.keymap.set({ "x" }, "<leader>ca", function()
			opencode.prompt("@this")
		end, { desc = "Open[C]ode [A]dd Context" })
		vim.keymap.set({ "n", "x" }, "<leader>cb", function()
			opencode.prompt("@buffers")
		end, { desc = "Open[C]ode Add [B]uffers" })
		vim.keymap.set({ "n", "x" }, "<leader>cg", function()
			opencode.prompt("@diff")
		end, { desc = "Open[C]ode Add [G]it Diff" })
		vim.keymap.set({ "n", "x" }, "<leader>c<tab>", function()
			opencode.command("agent.cycle")
		end, { desc = "Open[C]ode Agent Switch" })
		vim.keymap.set("n", "<M-u>", function()
			require("opencode").command("session.half.page.up")
		end, { desc = "OpenCode Half PageUp" })
		vim.keymap.set("n", "<M-d>", function()
			require("opencode").command("session.half.page.down")
		end, { desc = "OpenCode Half PageDown" })
	end,
}
