return {
	"folke/snacks.nvim",
	priority = 1000,
	lazy = false,
	---@type snacks.Config
	opts = {
		---------------
		-- Essential --
		---------------
		-- Picker
		picker = {
			enabled = true,
			win = { input = { keys = { ["<a-c>"] = { "cycle_preview", mode = { "i", "n" } } } } },
			-- From https://github.com/folke/snacks.nvim/discussions/458
			actions = {
				cycle_preview = function(picker)
					local layout_config = vim.deepcopy(picker.resolved_layout)

					if layout_config.preview == "main" or not picker.preview.win:valid() then
						return
					end

					local function find_preview(root) ---@param root snacks.layout.Box|snacks.layout.Win
						if root.win == "preview" then
							return root
						end
						if #root then
							for _, w in ipairs(root) do
								local preview = find_preview(w)
								if preview then
									return preview
								end
							end
						end
						return nil
					end

					local preview = find_preview(layout_config.layout)

					if not preview then
						return
					end

					local eval = function(s)
						return type(s) == "function" and s(preview.win) or s
					end
					--- @type number?, number?
					local width, height = eval(preview.width), eval(preview.height)

					if not width and not height then
						return
					end

					local cycle_sizes = { 0.1, 0.9 }
					local size_prop, size

					if height then
						size_prop, size = "height", height
					else
						size_prop, size = "width", width
					end

					picker.init_size = picker.init_size or size ---@diagnostic disable-line: inject-field
					table.insert(cycle_sizes, picker.init_size)
					table.sort(cycle_sizes)

					for i, s in ipairs(cycle_sizes) do
						if size == s then
							local smaller = cycle_sizes[i - 1] or cycle_sizes[#cycle_sizes]
							preview[size_prop] = smaller
							break
						end
					end

					for i, h in ipairs(layout_config.hidden) do
						if h == "preview" then
							table.remove(layout_config.hidden, i)
						end
					end

					picker:set_layout(layout_config)
				end,
			},
		},
		-- File explorer, picker
		explorer = { enabled = true },
		-----------------
		-- Performance --
		-----------------
		-- Prevent LSP and treesitter attaching to big files
		bigfile = { enabled = true },

		-- Render file before loading plugins
		quickfile = { enabled = true },

		--------
		-- UI --
		--------
		-- Better vim.ui.input
		input = { enabled = true },
		-- Better vim.notify
		notifier = {
			enabled = true,
			timeout = 3000,
		},
		styles = {
			notification = {
				wo = { wrap = true }, -- Wrap notifications
			},
		},
	},
	keys = {
		{
			"<leader>sh",
			function()
				Snacks.picker.help()
			end,
			desc = "[S]earch [H]elp",
		},
		{
			"<leader>sk",
			function()
				Snacks.picker.keymaps()
			end,
			desc = "[S]earch [K]eymaps",
		},
		{
			"<leader>sf",
			function()
				local curr_dir_name = vim.fn.fnamemodify(vim.fn.getcwd(), ":t")
				Snacks.picker.files({ hidden = (curr_dir_name == "dotfiles") })
			end,
			desc = "[S]earch [F]iles",
		},
		{
			"<leader>sw",
			function()
				local curr_dir_name = vim.fn.fnamemodify(vim.fn.getcwd(), ":t")
				Snacks.picker.grep_word({ hidden = (curr_dir_name == "dotfiles") })
			end,
			desc = "[S]earch current [W]ord",
			mode = { "n", "x" },
		},
		{
			"<leader>sb",
			function()
				Snacks.picker.buffers()
			end,
			desc = "[S]earch Open [B]uffers",
		},
		{
			"<leader>sg",
			function()
				local curr_dir_name = vim.fn.fnamemodify(vim.fn.getcwd(), ":t")
				Snacks.picker.grep({ hidden = (curr_dir_name == "dotfiles") })
			end,
			desc = "[S]earch by [G]rep",
		},
		{
			"<leader>e",
			function()
				local curr_dir_name = vim.fn.fnamemodify(vim.fn.getcwd(), ":t")
				Snacks.picker.explorer({ hidden = (curr_dir_name == "dotfiles") })
			end,
			desc = "File [E]xplorer",
		},
		{
			"<leader>/",
			function()
				Snacks.picker.lines()
			end,
			desc = "[/] Fuzzily search in current buffer",
		},
		{
			"<leader>sn",
			function()
				Snacks.picker.files({ cwd = vim.fn.stdpath("config") })
			end,
			desc = "[S]earch [N]eovim Config File",
		},
		{
			"<leader>st",
			function()
				Snacks.picker.todo_comments({ keywords = { "TODO" } })
			end,
			desc = "[S]earch [T]ODO Comments",
		},
		{
			"<leader><leader>",
			function()
				Snacks.picker.git_status()
			end,
			desc = "Git Status",
		},
		{
			"<leader>gp",
			function()
				Snacks.picker.gh_pr()
			end,
			desc = "[G]it [P]R",
		},
		{
			"<leader>sm",
			function()
				Snacks.picker.marks()
			end,
			desc = "[S]earch [M]arks",
		},
		{
			"<leader>sp",
			function()
				Snacks.picker.projects()
			end,
			desc = "[S]earch [P]rojects",
		},
		{
			"<leader>sd",
			"<cmd>Debugprint search<CR>",
			desc = "[S]earch [D]ebugprint",
		},
		-- LSP
		{
			"<leader>ss",
			function()
				Snacks.picker.lsp_symbols()
			end,
			desc = "[S]earch LSP [S]ymbols",
		},
		{
			"<leader>sS",
			function()
				Snacks.picker.lsp_workspace_symbols()
			end,
			desc = "[S]earch LSP Workspace [S]ymbols",
		},
		{
			"gd",
			function()
				Snacks.picker.lsp_definitions()
			end,
			desc = "[G]oto [D]efinition",
		},
		{
			"gD",
			function()
				Snacks.picker.lsp_declarations()
			end,
			desc = "[G]oto [D]eclaration",
		},
		{
			"gr",
			function()
				Snacks.picker.lsp_references()
			end,
			nowait = true,
			desc = "[G]oto [R]eferences",
		},
		{
			"gI",
			function()
				Snacks.picker.lsp_implementations()
			end,
			desc = "[G]oto [I]mplementation",
		},
		{
			"gt",
			function()
				Snacks.picker.lsp_type_definitions()
			end,
			desc = "[G]oto [T]ype Definition",
		},
		{
			"gai",
			function()
				Snacks.picker.lsp_incoming_calls()
			end,
			desc = "[G]oto C[a]lls [I]ncoming",
		},
		{
			"gao",
			function()
				Snacks.picker.lsp_outgoing_calls()
			end,
			desc = "[G]oto C[a]lls [O]utgoing",
		},
	},
}
