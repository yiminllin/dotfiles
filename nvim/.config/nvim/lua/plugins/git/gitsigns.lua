return {
	-- Adds git related signs
	"lewis6991/gitsigns.nvim",
	config = function()
		require("gitsigns").setup({
			signcolumn = true,
			numhl = true,
			current_line_blame = true,
			current_line_blame_opts = {
				virt_text = true,
				virt_text_pos = "right_align",
				delay = 500,
			},
			on_attach = function(bufnr)
				local gs = package.loaded.gitsigns

				local function map(mode, l, r, opts)
					opts = opts or {}
					opts.buffer = bufnr
					vim.keymap.set(mode, l, r, opts)
				end

				-- Navigation
				map("n", "]h", function()
					if vim.wo.diff then
						return "]h"
					end
					vim.schedule(function()
						gs.next_hunk()
					end)
					return "<Ignore>"
				end, { expr = true, desc = "Next [H]unk" })

				map("n", "[h", function()
					if vim.wo.diff then
						return "[h"
					end
					vim.schedule(function()
						gs.prev_hunk()
					end)
					return "<Ignore>"
				end, { expr = true, desc = "Prev [H]unk" })

				-- Actions
				map("n", "<leader>gs", gs.stage_buffer, { desc = "[G]it [S]tage buffer" })
				map("n", "<leader>gr", gs.reset_buffer, { desc = "[G]it [R]eset buffer" })
				map("n", "<leader>gd", gs.diffthis, { desc = "[G]it [D]iff buffer" })
				map("n", "<leader>gD", function()
					gs.diffthis("~")
				end, { desc = "[G]it [D]iff All" })
			end,
		})
	end,
}
