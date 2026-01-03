-- [[ Basic Keymaps ]]
-- Set highlight on search, but clear on pressing <Esc> in normal mode
vim.keymap.set("n", "<Esc>", "<cmd>nohlsearch<CR>")

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

-- Use Alt+<jk> to go through loclist if exists, or quickfix list
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

-- Cycle through vertical and horizontal layouts
local function cycle_layout()
	local wins = vim.api.nvim_tabpage_list_wins(0)
	if #wins ~= 2 then
		return
	end

	local win1, win2 = wins[1], wins[2]

	local pos1 = vim.api.nvim_win_get_position(win1)
	local pos2 = vim.api.nvim_win_get_position(win2)
	local is_vertical = pos1[1] == pos2[1]

	local get_dim = is_vertical and vim.api.nvim_win_get_width or vim.api.nvim_win_get_height
	local set_dim = is_vertical and vim.api.nvim_win_set_width or vim.api.nvim_win_set_height

	local current_size = get_dim(win1)
	local total_size = current_size + get_dim(win2)

	local small = math.floor(0.3 * total_size)
	local medium = math.floor(0.5 * total_size)
	local large = math.floor(0.7 * total_size)
	local tolerance = math.floor(0.1 * total_size)

	-- Cycle: 50 -> 70 -> 30 -> 50
	if math.abs(current_size - medium) <= tolerance then
		set_dim(win1, large)
	elseif current_size > medium then
		set_dim(win1, small)
	else
		set_dim(win1, medium)
	end
end

vim.keymap.set("n", "<M-c>", cycle_layout, { desc = "Cycle Split Layout" })
vim.keymap.set("n", "<M-|>", ":vsplit<CR>", { desc = "Vertical split" })
vim.keymap.set("n", "<M-->", ":split<CR>", { desc = "Horizontal split" })

-- Scroll right tmux pane
local function tmux_scroll_right_pane_silent(direction)
	local scroll_cmd = direction == "up" and "halfpage-up" or "halfpage-down"
	vim.fn.system("tmux copy-mode -t '{right}'")
	vim.fn.system("tmux send-keys -X -t '{right}' " .. scroll_cmd)
end
vim.keymap.set({ "n", "x" }, "<M-u>", function()
	tmux_scroll_right_pane_silent("up")
end, { desc = "Right Tmux Scroll Up" })
vim.keymap.set({ "n", "x" }, "<M-d>", function()
	tmux_scroll_right_pane_silent("down")
end, { desc = "Right Tmux Scroll Down" })

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

local function quit_scroll_mode_right_tmux_pane()
	vim.fn.system("tmux select-pane -t 1")
	if vim.trim(vim.fn.system("tmux display-message -p '#{pane_in_mode}'")) == "1" then
		vim.fn.system("tmux send-keys -X cancel")
	end
	vim.fn.system("tmux select-pane -t 0")
end

-- Cursor-agent keymap
local function create_cursor_split_or_prompt()
	local function is_cursor_running_in_window()
		local cmd =
			[[tmux list-panes -F '#{pane_tty}' | xargs -I{} ps -t {} -o args= 2>/dev/null | grep -qi cursor-agent]]
		vim.fn.system(cmd)
		return vim.v.shell_error == 0
	end
	if not is_cursor_running_in_window() then
		vim.fn.system("tmux split-window -h")
		vim.fn.system("tmux select-pane -t 1")
		vim.fn.system("tmux send-keys -t 1 'cursor-agent' Enter")
	else
		vim.ui.input({ prompt = "Cursor Prompt: " }, function(prompt)
			if not prompt then
				return
			end
			quit_scroll_mode_right_tmux_pane()
			vim.fn.system(string.format("tmux send-keys -t 1 '%s'", prompt))
			vim.fn.system("tmux send-keys -t 1 Enter")
		end)
	end
	vim.fn.system("tmux select-pane -t 0")
end

local function add_curr_buffer_path_relative_to_cwd_to_right_tmux_window()
	quit_scroll_mode_right_tmux_pane()
	local relative_path = vim.fn.expand("%:.")
	vim.fn.system("tmux send-keys -t 1 " .. relative_path .. " Space")
end

local function add_curr_loc_to_right_tmux_window()
	quit_scroll_mode_right_tmux_pane()
	local relative_path = vim.fn.expand("%:.")
	if vim.fn.mode() == "n" then
		local curr_line_num = vim.fn.line(".")
		vim.fn.system("tmux send-keys -t 1 " .. relative_path .. ":" .. curr_line_num .. " Space")
		return
	end

	if vim.fn.mode() == "v" or vim.fn.mode() == "V" or vim.fn.mode == "^V" then
		local start_v_line = vim.fn.getpos("v")[2]
		local end_v_line = vim.fn.getpos(".")[2]
		local start_line = math.min(start_v_line, end_v_line)
		local end_line = math.max(start_v_line, end_v_line)
		vim.fn.system("tmux send-keys -t 1 " .. relative_path .. ":" .. start_line .. "-" .. end_line .. " Space")
		return
	end
end

local function add_git_diff_to_right_tmux_window()
	vim.fn.system("tmux send-keys -t 1 'For git diff, '")
end

vim.keymap.set({ "n", "x" }, "<leader>cp", create_cursor_split_or_prompt, { desc = "[C]ursor [P]rompt" })
vim.keymap.set({ "n", "x" }, "<leader>ca", add_curr_loc_to_right_tmux_window, { desc = "[C]ursor [A]dd Context" })
vim.keymap.set(
	{ "n", "x" },
	"<leader>cb",
	add_curr_buffer_path_relative_to_cwd_to_right_tmux_window,
	{ desc = "[C]ursor Add [B]uffers" }
)
vim.keymap.set({ "n", "x" }, "<leader>cd", add_git_diff_to_right_tmux_window, { desc = "[C]ursor Add [G]it Diff" })
