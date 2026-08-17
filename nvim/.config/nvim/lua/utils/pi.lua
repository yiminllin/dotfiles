local M = {}

local CURRENT_CONTEXT_FORMAT = "#{window_id}\t#{pane_id}"
local WINDOW_PANE_FORMAT = table.concat({
	"#{pane_id}",
	"#{pane_left}",
	"#{pane_current_command}",
	"#{@pi_agent_board}",
	"#{pane_start_command}",
}, "\t")
local NAMED_AGENT_PANE_FORMAT = table.concat({
	"#{window_id}",
	"#{pane_id}",
	"#{@pi_agent_name}",
	"#{pane_current_command}",
	"#{pane_start_command}",
	"#{pane_current_path}",
}, "\t")
local PI_LAUNCH_COMMAND = [[tmux set-option -pt "$TMUX_PANE" allow-passthrough off; exec pi]]

local function run_tmux(args)
	local result = vim.system(vim.list_extend({ "tmux" }, args), { text = true }):wait()
	local output = vim.trim(result.stdout or "")
	local error_output = vim.trim(result.stderr or "")

	if result.code ~= 0 then
		return nil, error_output ~= "" and error_output or output
	end

	return output, nil
end

local function ensure_tmux()
	if vim.env.TMUX and vim.env.TMUX ~= "" then
		return true
	end

	vim.notify("This mapping only works inside tmux.", vim.log.levels.WARN, { title = "Pi" })
	return false
end

local function inspect_window_for_pi()
	local context_output, context_err = run_tmux({ "display-message", "-p", CURRENT_CONTEXT_FORMAT })
	if not context_output then
		return nil, context_err
	end

	local context_parts = vim.split(context_output, "\t", { plain = true })
	local context = {
		window_id = context_parts[1],
		pane_id = context_parts[2],
	}

	local panes_output, panes_err = run_tmux({
		"list-panes",
		"-t",
		context.window_id,
		"-F",
		WINDOW_PANE_FORMAT,
	})
	if not panes_output then
		return nil, panes_err
	end

	local panes = {}
	for _, line in ipairs(vim.split(panes_output, "\n", { trimempty = true })) do
		local parts = vim.split(line, "\t", { plain = true })
		if parts[4] ~= "1" then
			table.insert(panes, {
				pane_id = parts[1],
				pane_left = tonumber(parts[2]) or 0,
				current_command = parts[3] or "",
				start_command = parts[5] or "",
			})
		end
	end

	if #panes == 1 then
		return {
			context = context,
			panes = panes,
			decision = "create",
		}, nil
	end

	if #panes ~= 2 then
		return {
			context = context,
			panes = panes,
			decision = "notify",
			message = "Pi pane was not created: current tmux window is not a simple 1- or 2-pane layout.",
		},
			nil
	end

	local left_pane = panes[1]
	local right_pane = panes[2]

	if right_pane.pane_left < left_pane.pane_left then
		left_pane, right_pane = right_pane, left_pane
	end

	if left_pane.pane_left == right_pane.pane_left then
		return {
			context = context,
			panes = panes,
			decision = "notify",
			message = "Pi pane was not created: current tmux window is stacked instead of a left/right split.",
		},
			nil
	end

	local right_pane_looks_like_pi = right_pane.current_command == "pi"
		or right_pane.start_command:find("exec pi", 1, true) ~= nil

	if not right_pane_looks_like_pi then
		return {
			context = context,
			panes = panes,
			decision = "notify",
			message = "Pi pane was not created: right pane is not a Pi pane.",
		},
			nil
	end

	return {
		context = context,
		panes = panes,
		decision = "use_existing",
		target = {
			window_id = context.window_id,
			pane_id = right_pane.pane_id,
		},
	}, nil
end

local function focus_pane(pane_id)
	local _, err = run_tmux({ "select-pane", "-t", pane_id })
	if err then
		return false, err
	end

	return true
end

local function get_existing_pi_target()
	if not ensure_tmux() then
		return nil
	end

	local inspection, err = inspect_window_for_pi()
	if not inspection then
		if err then
			vim.notify("Failed to inspect tmux panes: " .. err, vim.log.levels.ERROR, { title = "Pi" })
		end
		return nil
	end

	return inspection.target
end

local function send_text(target, text, submit)
	local _, send_err = run_tmux({ "send-keys", "-t", target.pane_id, "-l", text })
	if send_err then
		return false, "Failed to send text to Pi: " .. send_err
	end

	if submit then
		local _, enter_err = run_tmux({ "send-keys", "-t", target.pane_id, "Enter" })
		if enter_err then
			return false, "Failed to submit Pi prompt: " .. enter_err
		end
	end

	return true
end

local function normalize_path(path)
	if type(path) ~= "string" or path == "" then
		return nil
	end
	return vim.fs.normalize(vim.fn.fnamemodify(path, ":p")):gsub("/+$", "")
end

local function pane_is_pi(current_command, start_command)
	current_command = tostring(current_command or "")
	start_command = tostring(start_command or "")
	return current_command == "pi"
		or current_command:match("/pi$") ~= nil
		or start_command:find("exec pi", 1, true) ~= nil
end

local function select_named_agent_target(lines, current_window_id, agent_name, repo_root)
	local expected_root = normalize_path(repo_root)
	local current_window_matches = {}
	local all_matches = {}
	for _, line in ipairs(lines or {}) do
		local parts = vim.split(line, "\t", { plain = true })
		if
			parts[3] == agent_name
			and pane_is_pi(parts[4], parts[5])
			and normalize_path(parts[6]) == expected_root
		then
			local target = { window_id = parts[1], pane_id = parts[2] }
			table.insert(all_matches, target)
			if parts[1] == current_window_id then
				table.insert(current_window_matches, target)
			end
		end
	end

	if #current_window_matches == 1 then
		return current_window_matches[1]
	end
	if #current_window_matches > 1 then
		return nil, ("Multiple Pi panes named %s exist in the current tmux window"):format(agent_name)
	end
	if #all_matches == 1 then
		return all_matches[1]
	end
	if #all_matches > 1 then
		return nil, ("Multiple Pi panes named %s exist; keep the review pane in this tmux window"):format(agent_name)
	end
	return nil, ("No active Pi pane named %s; start this review with `review ...`"):format(agent_name)
end

local function named_agent_target(agent_name, repo_root)
	if not (vim.env.TMUX and vim.env.TMUX ~= "") then
		return nil, "Not inside tmux; start this review with `review ...`"
	end
	if type(agent_name) ~= "string" or agent_name == "" then
		return nil, "The active Diffview review has no persistent Pi assistant name"
	end
	if not normalize_path(repo_root) then
		return nil, "The active Diffview review has no repository root"
	end

	local current_window_id, current_error = run_tmux({ "display-message", "-p", "#{window_id}" })
	if not current_window_id then
		return nil, current_error
	end
	local panes_output, panes_error = run_tmux({ "list-panes", "-a", "-F", NAMED_AGENT_PANE_FORMAT })
	if not panes_output then
		return nil, panes_error
	end
	return select_named_agent_target(
		vim.split(panes_output, "\n", { trimempty = true }),
		current_window_id,
		agent_name,
		repo_root
	)
end

function M.send_to_named_agent(agent_name, repo_root, text)
	local target, target_error = named_agent_target(agent_name, repo_root)
	if not target then
		return false, target_error
	end
	return send_text(target, text, true)
end

M._select_named_agent_target = select_named_agent_target

local function current_ref(with_location)
	local relative_path = vim.fn.expand("%:.")
	if relative_path == "" then
		return nil
	end

	local reference = vim.startswith(relative_path, "@") and relative_path or "@" .. relative_path
	if not with_location then
		return reference .. " "
	end

	local mode = vim.fn.mode()
	if mode == "n" then
		return reference .. ":" .. vim.fn.line(".") .. " "
	end

	if mode == "v" or mode == "V" or mode == "\22" then
		local start_v_line = vim.fn.getpos("v")[2]
		local end_v_line = vim.fn.getpos(".")[2]
		return reference .. ":" .. math.min(start_v_line, end_v_line) .. "-" .. math.max(start_v_line, end_v_line) .. " "
	end

	return nil
end

function M.scroll_pane(direction)
	local scroll_key = direction == "up" and "C-u" or direction == "down" and "C-d" or nil
	if not scroll_key then
		return
	end

	local target = get_existing_pi_target()
	if not target then
		return
	end

	local _, err = run_tmux({ "send-keys", "-t", target.pane_id, scroll_key })
	if err then
		vim.notify("Failed to scroll Pi: " .. err, vim.log.levels.ERROR, { title = "Pi" })
	end
end

function M.create_window_or_prompt()
	if not ensure_tmux() then
		return
	end

	local inspection, err = inspect_window_for_pi()
	if not inspection then
		vim.notify("Failed to inspect tmux panes: " .. err, vim.log.levels.ERROR, { title = "Pi" })
		return
	end

	if inspection.decision == "notify" then
		vim.notify(inspection.message, vim.log.levels.WARN, { title = "Pi" })
		return
	end

	if inspection.decision == "create" then
		local _, create_err = run_tmux({
			"split-window",
			"-h",
			"-P",
			"-F",
			"#{pane_id}",
			"-c",
			vim.fs.normalize(vim.fn.getcwd()),
			PI_LAUNCH_COMMAND,
		})
		if create_err then
			vim.notify("Failed to open Pi pane: " .. create_err, vim.log.levels.ERROR, { title = "Pi" })
			return
		end

		return
	end

	local original_pane_id = inspection.context.pane_id
	local target = inspection.target

	vim.ui.input({ prompt = "Pi Prompt: " }, function(prompt)
		if not prompt or prompt == "" then
			return
		end

		local ok, send_err = send_text(target, prompt, true)
		if not ok and send_err then
			vim.notify(send_err, vim.log.levels.ERROR, { title = "Pi" })
			return
		end

		local focused, focus_err = focus_pane(original_pane_id)
		if not focused then
			vim.notify("Failed to restore pane focus: " .. focus_err, vim.log.levels.ERROR, { title = "Pi" })
		end
	end)
end

function M.add_current_location()
	local reference = current_ref(true)
	if not reference then
		return
	end

	local target = get_existing_pi_target()
	if not target then
		return
	end

	local ok, err = send_text(target, reference, false)
	if not ok and err then
		vim.notify(err, vim.log.levels.ERROR, { title = "Pi" })
	end
end

function M.add_current_buffer_path_relative_to_cwd()
	local reference = current_ref(false)
	if not reference then
		return
	end

	local target = get_existing_pi_target()
	if not target then
		return
	end

	local ok, err = send_text(target, reference, false)
	if not ok and err then
		vim.notify(err, vim.log.levels.ERROR, { title = "Pi" })
	end
end

return M
