local M = {}

local function segments(path)
  local result = {}
  for part in path:gmatch("[^/]+") do
    table.insert(result, part)
  end
  return result
end

local function segment_matches(pattern, value)
  local escaped = pattern:gsub("([%^%$%(%)%%%.%[%]%+%-])", "%%%1")
  escaped = escaped:gsub("%*", ".*"):gsub("%?", ".")
  return value:match("^" .. escaped .. "$") ~= nil
end

function M.matches(pattern, path)
  local anchored = pattern:sub(1, 1) == "/"
  local directory = pattern:sub(-1) == "/"
  pattern = pattern:gsub("^/", ""):gsub("/$", "")
  local parts, target = segments(pattern), segments(path)
  if #parts == 0 then
    return false
  end
  local rooted = anchored or #parts > 1
  local last = #target - ((directory or (#parts > 1 and parts[#parts] == "**")) and 1 or 0)
  local function match_from(start, finish)
    local memo = {}
    local function match(i, j)
      local key = i .. ":" .. j
      if memo[key] ~= nil then
        return memo[key]
      end
      local result
      if i > #parts then
        result = j > finish
      elseif parts[i] == "**" then
        result = match(i + 1, j) or (j <= finish and match(i, j + 1))
      else
        result = j <= finish and segment_matches(parts[i], target[j]) and match(i + 1, j + 1)
      end
      memo[key] = result
      return result
    end
    return match(1, start)
  end
  for finish = 1, last do
    if rooted then
      if match_from(1, finish) then
        return true
      end
    elseif match_from(finish, finish) then
      return true
    end
  end
  return false
end

function M.parse(lines)
  local rules = {}
  for _, line in ipairs(lines) do
    local tokens, token = {}, ""
    local index = 1
    while index <= #line do
      local char = line:sub(index, index)
      if char == "#" then
        break
      end
      if char == "\\" and line:sub(index + 1, index + 1):match("%s") then
        index = index + 1
        token = token .. line:sub(index, index)
      elseif char:match("%s") then
        if token ~= "" then
          table.insert(tokens, token)
          token = ""
        end
      else
        token = token .. char
      end
      index = index + 1
    end
    if token ~= "" then
      table.insert(tokens, token)
    end
    local pattern = table.remove(tokens, 1)
    -- CODEOWNERS does not support negation, character classes, or escaped '#'.
    if pattern and pattern:sub(1, 1) ~= "!" and not pattern:find("[%[%]]") then
      table.insert(rules, { pattern = pattern, owners = tokens })
    end
  end
  return rules
end

function M.owned_by(rules, path, owner)
  local owners = {}
  for _, rule in ipairs(rules) do
    if M.matches(rule.pattern, path) then
      owners = rule.owners
    end
  end
  for _, candidate in ipairs(owners) do
    if candidate == owner then
      return true
    end
  end
  return false
end

function M.read(root, revision)
  if not revision then
    return nil, "An immutable review head is required for CODEOWNERS"
  end
  for _, path in ipairs({ ".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS" }) do
    local lines = vim.fn.systemlist({ "git", "-C", root, "show", revision .. ":" .. path })
    if vim.v.shell_error == 0 then
      return M.parse(lines)
    end
  end
  return nil, "No CODEOWNERS file at the reviewed head; Phoenix filtering is unavailable"
end

return M
