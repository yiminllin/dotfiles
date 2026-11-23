local M = {}

M.COMMENT_MARKER = "▌"
M.GUIDE_MARKER = "🤖"
M.GITHUB_MARKER = "GH"
M.GUIDE_SIGN_NAMES = {
	"DiffviewReviewGuideHigh",
	"DiffviewReviewGuideMedium",
	"DiffviewReviewGuideLow",
	"DiffviewReviewGuideInfo",
}

function M.normalize_comment_text(value)
	return vim.trim(tostring(value or ""):gsub("\r\n", " "):gsub("\r", " "):gsub("\n", " "):gsub("%s+", " "))
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
	return M.is_imported_github_comment(comment) and comment.github_line == nil and comment.original_line ~= nil
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

function M.agent_status_label(status)
	return ({
		pending = "Queued",
		running = "Investigating",
		blocked = "Needs input",
		completed = "Answered",
		cancelled = "Cancelled",
		failed = "Failed",
		unavailable = "Unavailable",
		unread = "Unread",
		attention = "Needs attention",
	})[status] or "Comment"
end

function M.comment_status_text(comment)
	local labels = {}
	if comment and comment.guide_retired then
		table.insert(labels, "earlier guide")
	end
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

	local anchor_status = tostring(comment and comment.anchor_status or "")
	if anchor_status == "moved" then
		local original_line = comment.anchor and comment.anchor.original and tonumber(comment.anchor.original.line)
		local resolved_line = tonumber(comment.line)
		if original_line and resolved_line then
			table.insert(labels, ("moved L%d→L%d"):format(original_line, resolved_line))
		else
			table.insert(labels, "moved anchor")
		end
	elseif anchor_status == "stale" then
		table.insert(labels, "stale anchor")
	elseif anchor_status == "ambiguous" then
		table.insert(labels, "ambiguous anchor")
	elseif anchor_status == "legacy_unverified" then
		table.insert(labels, "unverified legacy anchor")
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

function M.comment_sign(comment)
	if M.is_imported_github_comment(comment) then
		return "DiffviewReviewGithub"
	end
	if not M.is_guide_comment(comment) then
		return "DiffviewReviewComment"
	end
	local _, severity = M.severity_label(comment.severity)
	return "DiffviewReviewGuide" .. severity
end

function M.comment_body(comment)
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
	if
		M.is_guide_comment(comment)
		and comment.kind == "guide_suggestion"
		and comment.why
		and tostring(comment.why) ~= ""
	then
		body = body .. "\n\nWhy it matters: " .. tostring(comment.why)
	end
	return body
end

local function abbreviate(text, width, has_more)
	if not has_more and vim.fn.strdisplaywidth(text) <= width then
		return text
	end
	text = vim.fn.strcharpart(text, 0, width - 1)
	while vim.fn.strdisplaywidth(text) >= width do
		text = vim.fn.strcharpart(text, 0, vim.fn.strchars(text) - 1)
	end
	return text .. "…"
end

function M.comment_preview(comment, width, has_more)
	local body = vim.trim(tostring(comment and comment.body or ""))
	local first = M.normalize_comment_text(body:match("^[^\r\n]*") or "")
	if first == "" then
		first = "(empty comment)"
	end
	return abbreviate(first, math.max(1, math.min(width or 96, 96)), has_more or body:find("[\r\n]"))
end

function M.comment_card(comment, first, last, width, has_more)
	width = math.min(width, 66)
	local anchor = M.is_file_level_comment(comment) and "File-level" or M.range_label(first, last)
	local header = abbreviate(M.normalize_comment_text(M.comment_source_label(comment)) .. " · " .. anchor, width - 5)
	local top = "╭─ " .. header .. " "
	top = top .. string.rep("─", width - vim.fn.strdisplaywidth(top) - 1) .. "╮"
	local preview = M.comment_preview(comment, width - 4, has_more)
	local border = "DiffviewReviewCommentBorder"
	return {
		{ { top, border } },
		{
			{ "│ ", border },
			{ preview .. string.rep(" ", width - 4 - vim.fn.strdisplaywidth(preview)), "DiffviewReviewCommentPreview" },
			{ " │", border },
		},
		{ { "╰" .. string.rep("─", width - 2) .. "╯", border } },
	}
end

function M.split_comment_text(text)
	text = tostring(text or "")
	if text == "" then
		return { "" }
	end
	return vim.split(text, "\n", { plain = true })
end

return M
