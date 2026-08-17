local M = {}

M.SCHEMA_VERSION = 1
M.CONTEXT_LINES = 2

local function copy_lines(lines, first, last)
  local result = {}
  for index = math.max(first, 1), math.min(last, #lines) do
    table.insert(result, tostring(lines[index] or ""))
  end
  return result
end

local function sequence_matches(lines, start_line, expected)
  if start_line < 1 or #expected == 0 or start_line + #expected - 1 > #lines then
    return false
  end
  for offset, value in ipairs(expected) do
    if tostring(lines[start_line + offset - 1] or "") ~= value then
      return false
    end
  end
  return true
end

local function context_score(lines, start_line, text_count, original)
  local score = 0
  local before = original.before or {}
  local before_start = start_line - #before
  if before_start >= 1 and sequence_matches(lines, before_start, before) then
    score = score + #before
  end
  local after = original.after or {}
  local after_start = start_line + text_count
  if #after > 0 and sequence_matches(lines, after_start, after) then
    score = score + #after
  end
  return score
end

function M.file_hash(lines)
  return vim.fn.sha256(table.concat(lines or {}, "\n"))
end

function M.capture(lines, opts)
  opts = opts or {}
  local start_line = math.max(tonumber(opts.line) or 1, 1)
  local end_line = math.max(tonumber(opts.end_line) or start_line, start_line)
  end_line = math.min(end_line, #lines)
  start_line = math.min(start_line, math.max(#lines, 1))
  local context_lines = tonumber(opts.context_lines) or M.CONTEXT_LINES

  return {
    schema_version = M.SCHEMA_VERSION,
    path = opts.path,
    side = opts.side,
    original = {
      line = start_line,
      end_line = end_line,
      text = copy_lines(lines, start_line, end_line),
      before = copy_lines(lines, start_line - context_lines, start_line - 1),
      after = copy_lines(lines, end_line + 1, end_line + context_lines),
      file_hash = M.file_hash(lines),
      blob_sha = opts.blob_sha,
      commit_sha = opts.commit_sha,
    },
    resolved = {
      line = start_line,
      end_line = end_line,
      status = "anchored",
      confidence = "exact-line",
    },
  }
end

function M.resolve(anchor, lines)
  local original = type(anchor) == "table" and anchor.original or nil
  local text = original and original.text or nil
  if type(original) ~= "table" or type(text) ~= "table" or #text == 0 then
    return { status = "stale", confidence = "none", candidates = {} }
  end

  local original_line = tonumber(original.line) or 1
  local end_offset = #text - 1
  if sequence_matches(lines, original_line, text) then
    return {
      line = original_line,
      end_line = original_line + end_offset,
      status = "anchored",
      confidence = "exact-line",
      candidates = { original_line },
    }
  end

  local candidates = {}
  for line = 1, math.max(#lines - #text + 1, 0) do
    if sequence_matches(lines, line, text) then
      table.insert(candidates, {
        line = line,
        score = context_score(lines, line, #text, original),
        distance = math.abs(line - original_line),
      })
    end
  end

  if #candidates == 0 then
    return { status = "stale", confidence = "none", candidates = {} }
  end
  if #candidates == 1 then
    return {
      line = candidates[1].line,
      end_line = candidates[1].line + end_offset,
      status = "moved",
      confidence = "unique-exact",
      candidates = { candidates[1].line },
    }
  end

  table.sort(candidates, function(left, right)
    if left.score ~= right.score then
      return left.score > right.score
    end
    return left.distance < right.distance
  end)
  local best = candidates[1]
  local second = candidates[2]
  if best.score > 0 and best.score > second.score then
    local positions = {}
    for _, candidate in ipairs(candidates) do
      table.insert(positions, candidate.line)
    end
    return {
      line = best.line,
      end_line = best.line + end_offset,
      status = "moved",
      confidence = "exact-context",
      candidates = positions,
    }
  end

  local positions = {}
  for _, candidate in ipairs(candidates) do
    table.insert(positions, candidate.line)
  end
  table.sort(positions)
  return { status = "ambiguous", confidence = "none", candidates = positions }
end

function M.apply_resolution(comment, resolution)
  comment.anchor.resolved = vim.deepcopy(resolution)
  comment.anchor_status = resolution.status
  if resolution.line and (resolution.status == "anchored" or resolution.status == "moved") then
    comment.line = resolution.line
    comment.end_line = resolution.end_line
  end
end

return M
