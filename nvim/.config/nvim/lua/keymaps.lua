-- [[ Basic Keymaps ]]
-- Set highlight on search, but clear on pressing <Esc> in normal mode
vim.keymap.set("n", "<Esc>", "<cmd>nohlsearch<CR>")

-- LSP inspection
vim.keymap.set("n", "K", function()
	require("utils.rust_hover").hover({ border = "rounded", max_width = 88, max_height = 16 })
end, { desc = "Show type and documentation" })

-- Diagnostic keymaps
vim.keymap.set("n", "[d", vim.diagnostic.goto_prev, { desc = "Go to previous [D]iagnostic message" })
vim.keymap.set("n", "]d", vim.diagnostic.goto_next, { desc = "Go to next [D]iagnostic message" })
vim.keymap.set("n", "<leader>e", vim.diagnostic.open_float, { desc = "Show diagnostic [E]rror messages" })
vim.keymap.set("n", "<leader>q", vim.diagnostic.setqflist, { desc = "Open diagnostic [Q]uickfix list" })
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

-- Use Alt+<jk> for the location list when available, otherwise quickfix.
local function nav_loc_or_qf_list(direction)
	local loclist = vim.fn.getloclist(0, { size = 0 })
	if loclist.size > 0 then
		pcall(vim.cmd, direction == "next" and "lnext" or "lprev")
	else
		pcall(vim.cmd, direction == "next" and "cnext" or "cprev")
	end
end
vim.keymap.set("n", "<M-j>", function()
	nav_loc_or_qf_list("next")
end)
vim.keymap.set("n", "<M-k>", function()
	nav_loc_or_qf_list("prev")
end)

local function is_diff_side(win)
	local buf = vim.api.nvim_win_get_buf(win)
	return vim.wo[win].diff and not vim.b[buf].diffview_review_panel and vim.bo[buf].filetype ~= "DiffviewFiles"
end

local function split_pair(layout, current)
	local kind, children = unpack(layout)
	if kind == "leaf" then
		return
	end
	for index, child in ipairs(children) do
		if child[1] == "leaf" and child[2] == current then
			local left, right = children[index - 1], children[index + 1]
			left = left and left[1] == "leaf" and left[2]
			right = right and right[1] == "leaf" and right[2]
			-- In Diffview, favor the other diff side over an adjacent panel.
			if left and (not right or (is_diff_side(current) and is_diff_side(left))) then
				return kind, left, current
			elseif right then
				return kind, current, right
			end
		else
			local axis, first, second = split_pair(child, current)
			if axis then
				return axis, first, second
			end
		end
	end
end

local function cycle_layout()
	local current = vim.api.nvim_get_current_win()
	if vim.api.nvim_win_get_config(current).relative ~= "" then
		return
	end
	local layout = vim.fn.winlayout()
	if layout[1] == "leaf" then
		if vim.env.TMUX and vim.env.TMUX ~= "" then
			vim.system({ "tmux", "run-shell", "-b", "~/.tmux/cycle-layouts.sh" })
		end
		return
	end

	local axis, first, second = split_pair(layout, current)
	if not axis then
		return
	end
	local get_size = axis == "row" and vim.api.nvim_win_get_width or vim.api.nvim_win_get_height
	local move = axis == "row" and vim.fn.win_move_separator or vim.fn.win_move_statusline
	local size = get_size(first)
	local total = size + get_size(second)
	local share = size / total
	-- Cycle the left or top split: 50% → 70% → 30% → 50%.
	local next_share = share < 0.4 and 0.5 or (share <= 0.6 and 0.7 or 0.3)
	move(first, math.floor(total * next_share) - size)
end

vim.keymap.set("n", "<M-c>", cycle_layout, { desc = "Cycle Split Layout" })
vim.keymap.set("n", "<M-|>", ":vsplit<CR>", { desc = "Vertical split" })
vim.keymap.set("n", "<M-->", ":split<CR>", { desc = "Horizontal split" })

-- Pi Related
local pi = require("utils.pi")
vim.keymap.set({ "n", "x" }, "<M-u>", function()
	pi.scroll_pane("up")
end, { desc = "Right Tmux Scroll Up" })
vim.keymap.set({ "n", "x" }, "<M-d>", function()
	pi.scroll_pane("down")
end, { desc = "Right Tmux Scroll Down" })

vim.keymap.set({ "n", "x" }, "<leader>cp", pi.create_window_or_prompt, { desc = "Pi [P]rompt" })
vim.keymap.set({ "n", "x" }, "<leader>ca", pi.add_current_location, { desc = "Pi [A]dd Context" })
vim.keymap.set(
	{ "n", "x" },
	"<leader>cb",
	pi.add_current_buffer_path_relative_to_cwd,
	{ desc = "Pi Add [B]uffer" }
)

-- Note related
local function append_quick_note(prefix)
	vim.ui.input({ prompt = string.format("Quick note (%s): ", prefix) }, function(prompt)
		if not prompt then
			return
		end
		local notes_file = vim.fn.expand("~/notes/docs/reference/quick_notes.md")
		local file = io.open(notes_file, "a")
		file:write(string.format("- %s: %s\n", prefix, prompt))
		file:close()
	end)
end

vim.keymap.set({ "n", "x" }, "<leader>nb", function()
	append_quick_note("BUG")
end, { desc = "Quick [N]ote [B]ug" })
vim.keymap.set({ "n", "x" }, "<leader>nn", function()
	append_quick_note("NOTE")
end, { desc = "Quick [N]ote" })

-- For Zettlekasten
vim.keymap.set("n", "<leader>zn", function()
	local curr_dir = vim.fn.getcwd()
	if vim.fs.normalize(curr_dir) ~= vim.fs.normalize(vim.fn.expand("~/notes/")) then
		return
	end
	local template_file = vim.fs.joinpath(curr_dir, "template.md")
	local target_dir = vim.fs.joinpath(curr_dir, "main/")
	vim.ui.input({ prompt = "New note name (No .md needed): " }, function(note_name)
		if not note_name or note_name == "" then
			return
		end
		note_name = vim.fn.strftime("%Y-%m-%d-%H-%M-%S-") .. note_name:gsub("[_ ]", "-") .. ".md"
		local new_note_path = vim.fs.joinpath(target_dir, note_name)

		vim.fn.writefile(vim.fn.readfile(template_file), new_note_path)
		vim.cmd.edit(new_note_path)
	end)
end, { desc = "[Z]ettlekasten [N]ew Note" })
