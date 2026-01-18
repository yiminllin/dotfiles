return {
	"sindrets/diffview.nvim",
	dependencies = {
		{ "lifepillar/vim-solarized8", branch = "neovim" }, -- Pin to master branch
	},
	config = function()
		require("diffview").setup({
			enhanced_diff_hl = true,
		})

		local refresh_ibl = function()
			vim.api.nvim_set_hl(0, "Base2", { fg = "#eee8d5" })
			require("ibl").setup({
				indent = { highlight = "Base2", repeat_linebreak = true },
				scope = { show_start = false, show_end = false },
			})
		end

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
