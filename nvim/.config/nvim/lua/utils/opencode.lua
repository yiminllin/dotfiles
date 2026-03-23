local M = {}

local CURRENT_CONTEXT_FORMAT = "#{window_id}\t#{pane_id}"
local WINDOW_PANE_FORMAT = table.concat({
	"#{pane_id}",
	"#{pane_left}",
	"#{pane_current_command}",
	"#{pane_start_command}",
}, "\t")
local OPENCODE_LAUNCH_COMMAND = [[tmux set-option -pt "$TMUX_PANE" allow-passthrough off; exec fish -l -c 'exec opencode']]

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

	vim.notify("This mapping only works inside tmux.", vim.log.levels.WARN, { title = "OpenCode" })
	return false
end

local function inspect_window_for_opencode()
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
		table.insert(panes, {
			pane_id = parts[1],
			pane_left = tonumber(parts[2]) or 0,
			current_command = parts[3] or "",
			start_command = parts[4] or "",
		})
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
			message = "OpenCode pane was not created: current tmux window is not a simple 1- or 2-pane layout.",
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
			message = "OpenCode pane was not created: current tmux window is stacked instead of a left/right split.",
		},
			nil
	end

	local right_pane_looks_like_opencode = right_pane.current_command == "opencode"
		or right_pane.start_command:find("opencode", 1, true) ~= nil
		or (right_pane.current_command == "fish" and right_pane.start_command:find("opencode", 1, true) ~= nil)

	if not right_pane_looks_like_opencode then
		return {
			context = context,
			panes = panes,
			decision = "notify",
			message = "OpenCode pane was not created: right pane is not an OpenCode pane.",
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

local function get_existing_opencode_target()
	if not ensure_tmux() then
		return nil
	end

	local inspection, err = inspect_window_for_opencode()
	if not inspection then
		if err then
			vim.notify("Failed to inspect tmux panes: " .. err, vim.log.levels.ERROR, { title = "OpenCode" })
		end
		return nil
	end

	return inspection.target
end

local function send_text(target, text, submit)
	local _, send_err = run_tmux({ "send-keys", "-t", target.pane_id, "-l", text })
	if send_err then
		return false, "Failed to send text to OpenCode: " .. send_err
	end

	if submit then
		local _, enter_err = run_tmux({ "send-keys", "-t", target.pane_id, "Enter" })
		if enter_err then
			return false, "Failed to submit OpenCode prompt: " .. enter_err
		end
	end

	return true
end

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

	local target = get_existing_opencode_target()
	if not target then
		return
	end

	local _, err = run_tmux({ "send-keys", "-t", target.pane_id, scroll_key })
	if err then
		vim.notify("Failed to scroll OpenCode: " .. err, vim.log.levels.ERROR, { title = "OpenCode" })
	end
end

function M.create_window_or_prompt()
	if not ensure_tmux() then
		return
	end

	local inspection, err = inspect_window_for_opencode()
	if not inspection then
		vim.notify("Failed to inspect tmux panes: " .. err, vim.log.levels.ERROR, { title = "OpenCode" })
		return
	end

	if inspection.decision == "notify" then
		return
	end

	local original_pane_id = inspection.context.pane_id

	if inspection.decision == "create" then
		local _, create_err = run_tmux({
			"split-window",
			"-d",
			"-h",
			"-P",
			"-F",
			"#{pane_id}",
			"-c",
			vim.fs.normalize(vim.fn.getcwd()),
			OPENCODE_LAUNCH_COMMAND,
		})
		if create_err then
			vim.notify("Failed to open OpenCode pane: " .. create_err, vim.log.levels.ERROR, { title = "OpenCode" })
			return
		end

		local focused, focus_err = focus_pane(original_pane_id)
		if not focused then
			vim.notify("Failed to restore pane focus: " .. focus_err, vim.log.levels.ERROR, { title = "OpenCode" })
		end

		return
	end

	local target = inspection.target

	vim.ui.input({ prompt = "OpenCode Prompt: " }, function(prompt)
		if not prompt or prompt == "" then
			return
		end

		local ok, send_err = send_text(target, prompt, true)
		if not ok and send_err then
			vim.notify(send_err, vim.log.levels.ERROR, { title = "OpenCode" })
			return
		end

		local focused, focus_err = focus_pane(original_pane_id)
		if not focused then
			vim.notify("Failed to restore pane focus: " .. focus_err, vim.log.levels.ERROR, { title = "OpenCode" })
		end
	end)
end

function M.add_current_location()
	local reference = current_ref(true)
	if not reference then
		return
	end

	local target = get_existing_opencode_target()
	if not target then
		return
	end

	local ok, err = send_text(target, reference, false)
	if not ok and err then
		vim.notify(err, vim.log.levels.ERROR, { title = "OpenCode" })
	end
end

function M.add_current_buffer_path_relative_to_cwd()
	local reference = current_ref(false)
	if not reference then
		return
	end

	local target = get_existing_opencode_target()
	if not target then
		return
	end

	local ok, err = send_text(target, reference, false)
	if not ok and err then
		vim.notify(err, vim.log.levels.ERROR, { title = "OpenCode" })
	end
end

return M
