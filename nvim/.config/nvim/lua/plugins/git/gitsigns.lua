return {
	-- Adds git related signs
	"lewis6991/gitsigns.nvim",
	config = function()
		require("gitsigns").setup({
			-- Cannot correctly display line wrapping https://github.com/lewis6991/gitsigns.nvim/discussions/1403
			signcolumn = true,
			numhl = true,
			current_line_blame_opts = {
				virt_text = true,
				virt_text_pos = "right_align",
				delay = 500,
			},
			on_attach = function(bufnr)
				local gitsigns = require("gitsigns")

				local function map(mode, l, r, opts)
					opts = opts or {}
					opts.buffer = bufnr
					vim.keymap.set(mode, l, r, opts)
				end

				-- Navigation
				map("n", "]c", function()
					if vim.wo.diff then
						vim.cmd.normal({ "]c", bang = true })
					else
						gitsigns.nav_hunk("next")
					end
				end, { desc = "Git [H]unk Next ]" })

				map("n", "[c", function()
					if vim.wo.diff then
						vim.cmd.normal({ "[c", bang = true })
					else
						gitsigns.nav_hunk("prev")
					end
				end, { desc = "Git [H]unk Previous [" })

				-- Actions
				map("n", "<leader>hs", gitsigns.stage_hunk, { desc = "Git [H]unk [S]tage" })
				map("n", "<leader>hr", gitsigns.reset_hunk, { desc = "Git [H]unk [R]eset" })

				map("v", "<leader>hs", function()
					gitsigns.stage_hunk({ vim.fn.line("."), vim.fn.line("v") })
				end, { desc = "Git [H]unk [S]tage" })

				map("v", "<leader>hr", function()
					gitsigns.reset_hunk({ vim.fn.line("."), vim.fn.line("v") })
				end, { desc = "Git [H]unk [R]eset" })

				map("n", "<leader>hS", gitsigns.stage_buffer, { desc = "Git [H]unk [S]tage all" })
				map("n", "<leader>hR", gitsigns.reset_buffer, { desc = "Git [H]unk [R]eset all" })
				map("n", "<leader>hp", gitsigns.preview_hunk, { desc = "Git [H]unk [P]review" })
				map("n", "<leader>hi", gitsigns.preview_hunk_inline, { desc = "Git [H]unk Preview [I]nline" })
				map("n", "<leader>gb", gitsigns.blame_line, { desc = "[G]it [B]lame Line" })
				map("n", "<leader>gB", gitsigns.blame_line, { desc = "[G]it [B]lame All" })

				-- Text object
				map({ "o", "x" }, "ih", gitsigns.select_hunk)
			end,
		})
	end,
}
