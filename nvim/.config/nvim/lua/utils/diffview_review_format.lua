local M = {}

M.COMMENT_BOX_WIDTH = 88
M.COMMENT_MARKER = "▌"

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

function M.boxed_comment_lines(comment, start_line, end_line)
	local body_width = M.COMMENT_BOX_WIDTH - 4
	local header = " Review comment • " .. M.line_range_label(start_line, end_line) .. " "
	local top = "╭─" .. header
	top = top .. string.rep("─", math.max(M.COMMENT_BOX_WIDTH - M.display_width(top) - 1, 0)) .. "╮"

	local lines = { { { top, "DiffviewReviewCommentBorder" } } }
	for _, body_line in ipairs(M.wrap_comment_preview(comment.body, body_width)) do
		table.insert(lines, {
			{ "│ ", "DiffviewReviewCommentBorder" },
			{ M.pad_right(body_line, body_width), "DiffviewReviewCommentVirt" },
			{ " │", "DiffviewReviewCommentBorder" },
		})
	end
	table.insert(lines, { { "╰" .. string.rep("─", M.COMMENT_BOX_WIDTH - 2) .. "╯", "DiffviewReviewCommentBorder" } })
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
