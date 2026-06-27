local M = {}

M.COMMENT_BOX_WIDTH = 88
M.COMMENT_MARKER = "▌"
M.GUIDE_MARKER = "🤖"
M.GITHUB_MARKER = "GH"
M.GUIDE_SIGN_NAMES = {
	"DiffviewReviewGuideHigh",
	"DiffviewReviewGuideMedium",
	"DiffviewReviewGuideLow",
	"DiffviewReviewGuideInfo",
}

local GUIDE_STYLE_BY_SEVERITY = {
	High = {
		border = "DiffviewReviewGuideHighBorder",
		range = "DiffviewReviewGuideHighRange",
		sign = "DiffviewReviewGuideHigh",
		status = "DiffviewReviewStatusGuideHigh",
		virt = "DiffviewReviewGuideHighVirt",
	},
	Medium = {
		border = "DiffviewReviewGuideMediumBorder",
		range = "DiffviewReviewGuideMediumRange",
		sign = "DiffviewReviewGuideMedium",
		status = "DiffviewReviewStatusGuideMedium",
		virt = "DiffviewReviewGuideMediumVirt",
	},
	Low = {
		border = "DiffviewReviewGuideLowBorder",
		range = "DiffviewReviewGuideLowRange",
		sign = "DiffviewReviewGuideLow",
		status = "DiffviewReviewStatusGuideLow",
		virt = "DiffviewReviewGuideLowVirt",
	},
	Info = {
		border = "DiffviewReviewGuideInfoBorder",
		range = "DiffviewReviewGuideInfoRange",
		sign = "DiffviewReviewGuideInfo",
		status = "DiffviewReviewStatusGuideInfo",
		virt = "DiffviewReviewGuideInfoVirt",
	},
}

local MANUAL_STYLE = {
	border = "DiffviewReviewCommentBorder",
	range = "DiffviewReviewCommentRange",
	sign = "DiffviewReviewComment",
	status = "DiffviewReviewStatusComment",
	virt = "DiffviewReviewCommentVirt",
}

local GITHUB_STYLE = {
	border = "DiffviewReviewGithubBorder",
	range = "DiffviewReviewGithubRange",
	sign = "DiffviewReviewGithub",
	status = "DiffviewReviewStatusGithub",
	virt = "DiffviewReviewGithubVirt",
}

function M.normalize_comment_text(value)
	return vim.trim(tostring(value or ""):gsub("\r\n", " "):gsub("\r", " "):gsub("\n", " "):gsub("%s+", " "))
end

function M.wrap_comment_preview(value, width)
	local text = M.normalize_comment_text(value)
	width = width or M.COMMENT_BOX_WIDTH
	if text == "" then
		return { "" }
	end

	local lines = {}
	local line = ""
	for word in text:gmatch("%S+") do
		while #word > width do
			if line ~= "" then
				table.insert(lines, line)
				line = ""
			end
			table.insert(lines, word:sub(1, width))
			word = word:sub(width + 1)
		end

		if word ~= "" then
			if line == "" then
				line = word
			elseif #line + #word + 1 <= width then
				line = line .. " " .. word
			else
				table.insert(lines, line)
				line = word
			end
		end
	end

	if line ~= "" then
		table.insert(lines, line)
	end
	return lines
end

function M.display_width(value)
	return vim.fn.strdisplaywidth(value)
end

function M.pad_right(value, width)
	return value .. string.rep(" ", math.max(width - M.display_width(value), 0))
end

function M.line_range_label(start_line, end_line)
	if start_line == end_line then
		return ("L%d"):format(start_line)
	end
	return ("L%d-L%d"):format(start_line, end_line)
end

function M.range_label(start_line, end_line)
	if start_line == end_line then
		return tostring(start_line)
	end
	return ("%d-%d"):format(start_line, end_line)
end

function M.is_guide_comment(comment)
	return type(comment) == "table" and comment.source == "guide"
end

function M.is_imported_github_comment(comment)
	return type(comment) == "table" and comment.source == "github"
end

local function is_stale_github_anchor(comment)
	return M.is_imported_github_comment(comment)
		and comment.github_line == nil
		and comment.original_line ~= nil
end

function M.is_file_level_comment(comment)
	return type(comment) == "table"
		and (
			comment.file_level == true
			or (M.is_guide_comment(comment) and comment.kind == "guide_note")
			or is_stale_github_anchor(comment)
		)
end

local function is_posted_comment(comment)
	local sync_status = tostring(comment and comment.sync_status or "")
	return sync_status == "posted"
		or sync_status == "exported"
		or sync_status == "exported-to-github"
		or (comment and comment.github_posted_at ~= nil)
		or (comment and comment.github_posted_pr ~= nil)
		or (comment and comment.github_comment_id ~= nil)
		or (comment and comment.github_review_id ~= nil)
end

function M.comment_status_text(comment)
	local labels = {}
	local sync_status = tostring(comment and comment.sync_status or "")
	if is_stale_github_anchor(comment) then
		table.insert(labels, "stale original anchor")
	elseif comment and (comment.outdated == true or comment.stale == true) then
		table.insert(labels, "outdated")
	end

	if sync_status == "edited-locally" then
		table.insert(labels, "edited locally")
	elseif sync_status == "github-unknown-resolution" then
		table.insert(labels, "unknown resolution")
	elseif M.is_imported_github_comment(comment) and sync_status == "imported" then
		table.insert(labels, "imported")
	elseif is_posted_comment(comment) then
		table.insert(labels, "posted")
	elseif sync_status ~= "" then
		table.insert(labels, sync_status)
	end

	return table.concat(labels, "; ")
end

function M.comment_source_label(comment)
	if M.is_imported_github_comment(comment) then
		local author = comment.author and tostring(comment.author) ~= "" and (" @" .. comment.author) or ""
		if comment.sync_status == "edited-locally" then
			return M.GITHUB_MARKER .. " Local edit" .. author
		end
		return M.GITHUB_MARKER .. " GitHub" .. author
	end
	if M.is_guide_comment(comment) then
		if comment.kind == "guide_note" then
			return M.GUIDE_MARKER .. " Guide"
		end
		local severity = M.severity_label(comment.severity)
		return M.severity_emoji(severity) .. " Guide " .. severity
	end
	return "Local decision"
end

function M.severity_label(value)
	local severity = type(value) == "string" and vim.trim(value) or ""
	local key = severity:lower()
	if key == "blocker" then
		return "Blocker", "High"
	elseif key == "high" then
		return "High", "High"
	elseif key == "medium" then
		return "Medium", "Medium"
	elseif key == "low" then
		return "Low", "Low"
	elseif key == "nit" then
		return "Nit", "Low"
	elseif key == "curiosity" then
		return "Curiosity", "Low"
	elseif key == "info" then
		return "Info", "Info"
	end
	return severity ~= "" and severity or "Info", "Info"
end

function M.severity_emoji(value)
	local severity = type(value) == "string" and vim.trim(value):lower() or ""
	if severity == "blocker" or severity == "critical" or severity == "high" then
		return "🚨"
	elseif severity == "medium" then
		return "⚠️"
	elseif severity == "low" then
		return "💡"
	elseif severity == "curiosity" then
		return "🤔"
	elseif severity == "nit" then
		return "🧹"
	end
	return M.GUIDE_MARKER
end

function M.comment_highlights(comment)
	if M.is_imported_github_comment(comment) then
		return GITHUB_STYLE
	end
	if not M.is_guide_comment(comment) then
		return MANUAL_STYLE
	end

	local _, severity_key = M.severity_label(comment.severity)
	return GUIDE_STYLE_BY_SEVERITY[severity_key] or GUIDE_STYLE_BY_SEVERITY.Info
end

local function boxed_comment_header(comment, start_line, end_line)
	local label = M.line_range_label(start_line, end_line)
	local anchor = M.is_file_level_comment(comment) and "File-level" or label
	local status = M.comment_status_text(comment)
	if status ~= "" then
		status = " [" .. status .. "]"
	end
	return " " .. M.comment_source_label(comment) .. " • " .. anchor .. status .. " "
end

local function boxed_comment_body(comment)
	local body = tostring(comment and comment.body or "")
	if is_stale_github_anchor(comment) then
		local original_line = tonumber(comment.original_line)
		local original_start_line = tonumber(comment.original_start_line)
		local note = ("Imported from a stale GitHub anchor at original line %d."):format(original_line)
		if original_start_line and original_start_line ~= original_line then
			note = ("Imported from a stale GitHub anchor at original lines %d-%d."):format(
				original_start_line,
				original_line
			)
		end
		body = body ~= "" and (note .. "\n\n" .. body) or note
	end
	if M.is_guide_comment(comment) and comment.kind == "guide_suggestion" and comment.why and tostring(comment.why) ~= "" then
		body = body .. "\nWhy it matters: " .. tostring(comment.why)
	end
	return body
end

local function wrap_comment_body(value, width)
	local lines = {}
	for _, body_line in ipairs(vim.split(tostring(value or ""), "\n", { plain = true })) do
		vim.list_extend(lines, M.wrap_comment_preview(body_line, width))
	end
	return #lines > 0 and lines or { "" }
end

function M.boxed_comment_lines(comment, start_line, end_line)
	local body_width = M.COMMENT_BOX_WIDTH - 4
	local hls = M.comment_highlights(comment)
	local header = boxed_comment_header(comment, start_line, end_line)
	local top = "╭─" .. header
	top = top .. string.rep("─", math.max(M.COMMENT_BOX_WIDTH - M.display_width(top) - 1, 0)) .. "╮"

	local lines = { { { top, hls.border } } }
	for _, body_line in ipairs(wrap_comment_body(boxed_comment_body(comment), body_width)) do
		table.insert(lines, {
			{ "│ ", hls.border },
			{ M.pad_right(body_line, body_width), hls.virt },
			{ " │", hls.border },
		})
	end
	table.insert(lines, { { "╰" .. string.rep("─", M.COMMENT_BOX_WIDTH - 2) .. "╯", hls.border } })
	return lines
end

function M.comment_preview(comment)
	local body = tostring(comment and comment.body or "")
	local first = body:match("^[^\r\n]*") or ""
	first = M.normalize_comment_text(first)
	if first == "" then
		first = "(empty comment)"
	end
	local multiline = body:find("[\r\n]") ~= nil
	if #first > 96 then
		first = first:sub(1, 96)
		multiline = true
	end
	return multiline and (first .. "…") or first
end

function M.split_comment_text(text)
	text = tostring(text or "")
	if text == "" then
		return { "" }
	end
	return vim.split(text, "\n", { plain = true })
end

return M
