return {
	"sindrets/diffview.nvim",
	dependencies = {
		{ "lifepillar/vim-solarized8", branch = "neovim" }, -- Pin to master branch
	},
	config = function()
		require("diffview").setup({
			enhanced_diff_hl = true,
		})

		local function apply_diff2_winhl()
			local view = require("diffview.lib").get_current_view()
			if not view or not view.winopts or not view.winopts.diff2 then
				return
			end

			-- Darker variant of current DiffDelete (#f4c2a2) for left changed text.
			vim.api.nvim_set_hl(0, "DiffviewLeftDiffText", { bg = "#dca482" })

			-- Only for diff2 layouts:
			-- left  changed lines -> DiffDelete color
			-- right changed lines -> DiffAdd color
			-- changed text chunks  -> DiffChange color
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
				"DiffText:DiffChange",
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
				vim.api.nvim_set_hl(0, "DiffAdd", { bg = "#e6e9c1" })
				vim.api.nvim_set_hl(0, "DiffChange", { bg = "#cecba1" })
				vim.api.nvim_set_hl(0, "DiffText", { bg = "#c5e0dc", fg = "#323024", bold = true })
				vim.api.nvim_set_hl(0, "DiffDelete", { bg = "#f4c2a2" })
				apply_diff2_winhl()
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
			"<cmd>DiffviewOpen<cr>",
			mode = { "n", "v" },
			desc = "[G]it [D]iffview Open [C]urrent Changes",
		},
		{
			"<leader>gdm",
			function()
				if string.find(vim.fn.system("git remote get-url origin"), "FlightSystems", 1, true) then
					vim.cmd("DiffviewOpen origin/develop")
				else
					vim.cmd("DiffviewOpen origin/main")
				end
			end,
			mode = { "n", "v" },
			desc = "[G]it [D]iffview Open [M]ain branch",
		},
		{
			"<leader>gdp",
			function()
				-- Get the immediate parent branch (one level above)
				local function get_parent_branch()
					local current_branch = vim.fn.system("git branch --show-current"):gsub("%s+", "")
					if current_branch == "" then
						return nil
					end

					-- Get all local branches
					local branches_output = vim.fn.system("git branch --list")
					local branches = {}
					for branch in branches_output:gmatch("[* ] ([^\n]+)") do
						branch = branch:gsub("%s+", "")
						if branch ~= current_branch then
							table.insert(branches, branch)
						end
					end

					local branch_tip = vim.fn.system("git rev-parse " .. current_branch):gsub("%s+", "")
					if branch_tip == "" then
						return nil
					end

					local closest_parent = nil
					local shortest_dist = math.huge

					-- Find the closest ancestor branch
					for _, candidate in ipairs(branches) do
						local candidate_tip = vim.fn.system("git rev-parse " .. candidate):gsub("%s+", "")
						if candidate_tip == "" then
							goto continue
						end

						-- Check if candidate is an ancestor of current branch
						vim.fn.system("git merge-base --is-ancestor " .. candidate_tip .. " " .. branch_tip .. " 2>&1")
						if vim.v.shell_error ~= 0 then
							goto continue
						end

						-- Skip if current branch is an ancestor of candidate (would create cycle)
						vim.fn.system("git merge-base --is-ancestor " .. branch_tip .. " " .. candidate_tip .. " 2>&1")
						if vim.v.shell_error == 0 then
							goto continue
						end

						-- Count commits between candidate and current branch
						local dist_output =
							vim.fn.system("git rev-list --count " .. candidate_tip .. ".." .. branch_tip .. " 2>&1")
						local dist = tonumber(dist_output:match("%d+"))
						if dist and dist < shortest_dist then
							closest_parent = candidate
							shortest_dist = dist
						end

						::continue::
					end

					return closest_parent
				end

				local parent = get_parent_branch()
				if not parent then
					vim.notify("Could not determine parent branch", vim.log.levels.WARN)
					return
				end
				vim.cmd("DiffviewOpen " .. parent)
			end,
			mode = { "n", "v" },
			desc = "[G]it [D]iffview Open [P]arent branch",
		},
		{
			"<leader>gdx",
			"<cmd>DiffviewClose<cr>",
			mode = { "n", "v" },
			desc = "[G]it [D]iffview [X]Close",
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
		{ "<leader>gdf", "<cmd>DiffviewFileHistory<cr>", mode = { "n", "v" }, desc = "[G]it Diffview [F]ile History" },
	},
}
