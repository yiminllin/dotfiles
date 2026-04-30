local function get_cwd()
	local uv = vim.uv or vim.loop
	if uv and uv.cwd then
		return uv.cwd()
	end
	return vim.fn.getcwd()
end

local function in_systems_dir()
	local cwd = get_cwd()
	return cwd:match("/Systems[^/]*(/|$)") ~= nil
end

local function diffview_open(extra_args)
	local args = extra_args and vim.deepcopy(extra_args) or {}
	if in_systems_dir() then
		vim.list_extend(args, { "--", ".", ":!.opencode/skills", ":!notes" })
	end
	vim.api.nvim_cmd({ cmd = "DiffviewOpen", args = args }, {})
end

local function diffview_file_history()
	local args = {}
	if in_systems_dir() then
		vim.list_extend(args, { ".", ":!.opencode/skills", ":!notes" })
	end
	vim.api.nvim_cmd({ cmd = "DiffviewFileHistory", args = args }, {})
end

return {
	"sindrets/diffview.nvim",
	dependencies = {
		{ "lifepillar/vim-solarized8", branch = "neovim" }, -- Pin to master branch
	},
	config = function()
		local review = require("utils.diffview_review")
		review.setup()

		require("diffview").setup({
			enhanced_diff_hl = true,
			keymaps = review.diffview_keymaps(),
		})

		local function apply_diff2_winhl()
			review.apply_highlights()

			local view = require("diffview.lib").get_current_view()
			if not view or not view.winopts or not view.winopts.diff2 then
				return
			end

			-- Only for diff2 layouts:
			-- left  deleted/changed lines -> red GitHub color
			-- right added/changed lines   -> green GitHub color
			-- added/deleted counterpart filler lines use Diffview's subtle delete-dim group
			-- changed text chunks         -> brighter side-specific colors
			view.winopts.diff2.a.winhl = {
				"DiffAdd:DiffviewDiffAddAsDelete",
				"DiffDelete:DiffviewDiffDeleteDim",
				"DiffChange:DiffDelete",
				"DiffText:DiffviewLeftDiffText",
			}
			view.winopts.diff2.b.winhl = {
				"DiffDelete:DiffviewDiffDeleteDim",
				"DiffAdd:DiffviewDiffAdd",
				"DiffChange:DiffAdd",
				"DiffText:DiffviewRightDiffText",
			}
		end

		local refresh_ibl = function()
			vim.api.nvim_set_hl(0, "Base2", { fg = "#eee8d5" })
			require("ibl").setup({
				indent = { highlight = "Base2", repeat_linebreak = true },
				scope = { show_start = false, show_end = false },
			})
		end

		local function auto_switch_diffview_layout()
			local view = require("diffview.lib").get_current_view()
			local entry = view and view.cur_entry
			if
				not view
				or not view.cur_layout
				or not entry
				or not entry.layout
				or not entry.layout.a
				or not entry.layout.b
			then
				return
			end

			local width = vim.o.columns
			local height = vim.o.lines
			if width == 0 or height == 0 then
				return
			end

			local visual_height = height * 2.0 -- Monospace font ratio
			local target_layout_name = width > visual_height and "diff2_horizontal" or "diff2_vertical"

			local old_layout = entry.layout
			local current_layout_name = old_layout.name or (old_layout.class and old_layout.class.name)
			if current_layout_name == target_layout_name then
				return
			end

			local LayoutClass = require("diffview.config").name_to_layout(target_layout_name)
			entry.layout = LayoutClass({ a = old_layout.a.file, b = old_layout.b.file })
			old_layout:destroy()
			view:use_entry(entry)
			vim.cmd("wincmd =") -- Resize to equal dimension
		end

		local resize_timer = nil
		vim.api.nvim_create_autocmd({ "VimResized", "WinResized" }, {
			callback = function()
				local view = require("diffview.lib").get_current_view()
				if not view then
					return
				end

				if resize_timer then
					vim.fn.timer_stop(resize_timer)
				end

				resize_timer = vim.fn.timer_start(100, function()
					auto_switch_diffview_layout()
					resize_timer = nil
				end)
			end,
		})

		vim.api.nvim_create_autocmd("User", {
			pattern = "DiffviewViewPostLayout",
			callback = function()
				apply_diff2_winhl()
			end,
		})
		vim.api.nvim_create_autocmd("User", {
			pattern = "DiffviewViewOpened",
			callback = function()
				-- Check if this is a FileHistory view (don't close explorer for it)
				local ok, view = pcall(function()
					return require("diffview.lib").get_current_view()
				end)
				if ok and view then
					local view_type = tostring(view.class or view.__class or "")
					if not view_type:match("FileHistory") then
						-- Close explorer for non-FileHistory views
						vim.cmd("DiffviewToggleFiles")
					end
				end
				vim.o.background = "light"
				vim.cmd.colorscheme("solarized8_flat")
				review.apply_highlights()
				apply_diff2_winhl()
				review.refresh_visible()
				refresh_ibl()
			end,
		})
		vim.api.nvim_create_autocmd("User", {
			pattern = "DiffviewViewClosed",
			callback = function()
				require("gruvbox").setup({
					contrast = "hard",
					overrides = {
						DiffDelete = { bg = "#f4c2a2" },
						DiffAdd = { bg = "#e6e9c1" },
						DiffChange = { bg = "#cecba1" },
						DiffText = { bg = "#c5e0dc", fg = "#323024", bold = true },
					},
				})
				vim.o.background = "light"
				vim.cmd.colorscheme("gruvbox")
				refresh_ibl()
			end,
		})
	end,
	keys = {
		{
			"<leader>gdc",
			function()
				diffview_open()
			end,
			mode = { "n", "v" },
			desc = "[G]it [D]iffview Open [C]urrent Changes",
		},
		{
			"<leader>gdm",
			function()
				if string.find(vim.fn.system("git remote get-url origin"), "FlightSystems", 1, true) then
					diffview_open({ "origin/develop" })
				else
					diffview_open({ "origin/main" })
				end
			end,
			mode = { "n", "v" },
			desc = "[G]it [D]iffview Open [M]ain branch",
		},
		{
			"<leader>gdp",
			function()
				-- Get the immediate parent branch from git-spice stack metadata.
				local function get_parent_branch()
					local git_spice_log_levels = { WRN = true, INF = true, ERR = true, FTL = true }

					local function first_branch_line(lines)
						for _, line in ipairs(lines or {}) do
							line = vim.trim(line)
							local first_token = line:match("^(%S+)")
							if line ~= "" and not git_spice_log_levels[first_token] then
								return line
							end
						end
					end

					if vim.fn.executable("git-spice") ~= 1 then
						return nil
					end

					local lines = vim.fn.systemlist({ "git-spice", "--no-prompt", "down", "--dry-run" })
					if vim.v.shell_error ~= 0 then
						return nil
					end

					return first_branch_line(lines)
				end

				local parent = get_parent_branch()
				if not parent then
					vim.notify("Could not determine git-spice parent branch", vim.log.levels.WARN)
					return
				end
				diffview_open({ parent })
			end,
			mode = { "n", "v" },
			desc = "[G]it [D]iffview Open [P]arent branch",
		},
		{
			"<leader>gdx",
			"<cmd>DiffviewClose<cr>",
			mode = { "n", "v" },
			desc = "[G]it [D]iffview [X] Close",
		},
		{
			"<leader>gde",
			"<cmd>DiffviewToggleFiles<cr>",
			mode = { "n", "v" },
			desc = "[G]it [D]iffview Toggle File [E]xplorer",
		},
		{
			"<leader>gdr",
			"<cmd>DiffviewRefresh<cr>",
			mode = { "n", "v" },
			desc = "[G]it [D]iffview [R]efresh",
		},
		{
			"<leader>gdf",
			function()
				diffview_file_history()
			end,
			mode = { "n", "v" },
			desc = "[G]it [D]iffview [F]ile History",
		},
		{
			"<leader>gda",
			function()
				require("utils.diffview_review").add_comment()
			end,
			mode = "n",
			desc = "[G]it [D]iffview [A]dd Review Comment",
		},
		{
			"<leader>gda",
			function()
				require("utils.diffview_review").add_comment_visual()
			end,
			mode = "v",
			desc = "[G]it [D]iffview [A]dd Review Comment",
		},
		{
			"<leader>gdd",
			function()
				require("utils.diffview_review").delete_comment()
			end,
			mode = { "n", "v" },
			desc = "[G]it [D]iffview [D]elete Review Comment",
		},
		{
			"<leader>gdv",
			function()
				require("utils.diffview_review").toggle_file_viewed()
			end,
			mode = { "n", "v" },
			desc = "[G]it [D]iffview Toggle File [V]iewed",
		},
		{
			"<leader>gdu",
			function()
				require("utils.diffview_review").pick_unviewed_file()
			end,
			mode = { "n", "v" },
			desc = "[G]it [D]iffview Pick [U]nviewed File",
		},
	},
}
