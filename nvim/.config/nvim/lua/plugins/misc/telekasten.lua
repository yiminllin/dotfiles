return {
	"renerocksai/telekasten.nvim",
	dependencies = { "nvim-telescope/telescope.nvim" },
	config = function()
		require("telekasten").setup({
			home = vim.fn.expand("~/notes/main"),
			templates = vim.fn.expand("~/notes/template"),
			image_subdir = vim.fn.expand("~/notes/figures"),
			extra_dirs = {
				pdfs = vim.fn.expand("~/notes/pdf"),
			},
			dailies = "", -- Disable daily notes
			new_note_filename = "title",
			filename_space_subst = true,
			filename_small_case = true,
			subdirs_in_links = true, -- Allow linking to notes in subdirectories
			template_new_note = vim.fn.expand("~/notes/template/source_template.md"),
		})
		-- Keymaps
		local telekasten = require("telekasten")
		vim.keymap.set("n", "<leader>zn", telekasten.new_note, { desc = "[Z]ettelkasten [N]ew note" })
		vim.keymap.set("n", "<leader>zf", telekasten.find_notes, { desc = "[Z]ettelkasten [F]ind note" })
		vim.keymap.set("n", "<leader>zg", telekasten.search_notes, { desc = "[Z]ettelkasten [G]rep note" })
		vim.keymap.set("n", "<leader>zb", telekasten.show_backlinks, { desc = "[Z]ettelkasten Show [B]acklinks" })
		vim.keymap.set("n", "<leader>zt", telekasten.show_tags, { desc = "[Z]ettelkasten Show [T]ags" })
		vim.keymap.set("n", "<leader>zl", telekasten.follow_link, { desc = "[Z]ettelkasten Follow [L]ink" })
	end,
}
