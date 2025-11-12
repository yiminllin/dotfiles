return {
	"jbyuki/venn.nvim",
	config = function()
		function toggle_venn()
			local venn_enabled = vim.b.venn_enabled
			if not venn_enabled then
				vim.b.venn_enabled = true
				vim.cmd("setlocal virtualedit=all")

				-- Set keymaps when venn is enabled
				vim.keymap.set("n", "J", "<C-v>j:VBox<CR>", { buffer = true })
				vim.keymap.set("n", "K", "<C-v>k:VBox<CR>", { buffer = true })
				vim.keymap.set("n", "L", "<C-v>l:VBox<CR>", { buffer = true })
				vim.keymap.set("n", "H", "<C-v>h:VBox<CR>", { buffer = true })

				vim.keymap.set("v", "f", ":VBox<CR>", { buffer = true })

				vim.notify("Venn Mode ON")
			else
				vim.b.venn_enabled = false
				vim.cmd('setlocal virtualedit=""')

				-- Remove the keymaps
				vim.keymap.del("n", "J", { buffer = true })
				vim.keymap.del("n", "K", { buffer = true })
				vim.keymap.del("n", "L", { buffer = true })
				vim.keymap.del("n", "H", { buffer = true })

				vim.keymap.del("v", "f", { buffer = true })

				vim.notify("Venn Mode OFF")
			end
		end

		vim.keymap.set(
			"n",
			"<leader>v<space>",
			":lua toggle_venn()<CR>",
			{ noremap = true, silent = true, desc = "Go to [V]enn (Box diagram) mode" }
		)
	end,
}
