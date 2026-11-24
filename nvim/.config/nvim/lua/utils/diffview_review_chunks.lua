-- Inventory pinned Git hunks and validate their complete, exclusive section ownership.
local M = {}
local guide_view = require("utils.diffview_review_guide")

-- Name-status and patch output use the same Git ordering, including rename pairs.
function M.parse(names, patch, base, head)
  local fields = vim.split(names, "\0", { plain = true, trimempty = true })
  local files, index = {}, 1
  while index <= #fields do
    local status, path, oldpath = fields[index], fields[index + 1]
    index = index + 2
    if status:match("^[RC]") then
      oldpath, path = path, fields[index]
      index = index + 1
    end
    if not path then
      return nil, "Incomplete Git file inventory"
    end
    table.insert(files, { path = path, oldpath = oldpath, status = status })
  end
  local sections = {}
  for _, line in ipairs(vim.split(patch, "\n", { plain = true })) do
    if line:match("^diff %-%-git ") then
      table.insert(sections, {})
    end
    if #sections > 0 then
      table.insert(sections[#sections], line)
    end
  end
  if #sections ~= #files then
    return nil, "Git file and patch inventories disagree"
  end
  local catalog = { context = { base_oid = base, head_oid = head }, hunks = {}, by_id = {}, change_starts = {} }
  for file_index, lines in ipairs(sections) do
    local file, hunks, current = files[file_index], {}, nil
    local attributes, submodule = {}, false
    for _, line in ipairs(lines) do
      if
        line:match("^old mode ")
        or line:match("^new mode ")
        or line:match("^new file mode ")
        or line:match("^deleted file mode ")
        or line:match("^rename ")
        or line:match("^copy ")
        or line:match("^Binary files ")
      then
        table.insert(attributes, line)
      end
      if line:match("^index .+ 160000$") then
        submodule = true
      end
      local left, left_count, right, right_count = line:match("^@@ %-(%d+)(,?%d*) %+(%d+)(,?%d*) @@")
      if left then
        current = vim.tbl_extend("force", file, {
          kind = "hunk",
          header = line,
          left_start = tonumber(left),
          left_count = tonumber(left_count:sub(2)) or 1,
          right_start = tonumber(right),
          right_count = tonumber(right_count:sub(2)) or 1,
          patch = {},
        })
        table.insert(hunks, current)
      end
      if current and line ~= "" then
        table.insert(current.patch, line)
      end
    end
    if #hunks == 0 or submodule then
      local label = submodule and "Submodule commit change" or table.concat(attributes, " · ")
      hunks = {
        vim.tbl_extend("force", file, {
          kind = "file",
          header = label ~= "" and label or "File-level change",
          patch = lines,
        }),
      }
    elseif #attributes > 0 then
      hunks[1].file_change = table.concat(attributes, " · ")
    end
    for _, hunk in ipairs(hunks) do
      hunk.id = "h-"
        .. vim.fn
          .sha256(vim.json.encode({ base, head, file.path, file.oldpath or "", table.concat(hunk.patch, "\n") }))
          :sub(1, 24)
      if hunk.kind == "hunk" then
        local left, right = hunk.left_start, hunk.right_start
        local starts = {}
        for index = 2, #hunk.patch do
          local marker = hunk.patch[index]:sub(1, 1)
          if marker == "-" then
            starts.LEFT = starts.LEFT or left
          elseif marker == "+" then
            starts.RIGHT = starts.RIGHT or right
          end
          if marker == " " or marker == "-" then
            left = left + 1
          end
          if marker == " " or marker == "+" then
            right = right + 1
          end
        end
        catalog.change_starts[hunk.id] = starts
      end
      hunk.patch = nil
      if catalog.by_id[hunk.id] then
        return nil, "Duplicate hunk identity"
      end
      catalog.by_id[hunk.id] = hunk
      table.insert(catalog.hunks, hunk)
    end
  end
  return catalog
end

function M.inventory(root, base, head, paths)
  local command = {
    "git",
    "--no-pager",
    "-C",
    root,
    "-c",
    "diff.suppressBlankEmpty=false",
    "-c",
    "core.quotePath=false",
    "diff",
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--no-relative",
    "--find-renames",
    "--src-prefix=a/",
    "--dst-prefix=b/",
    "--output-indicator-new=+",
    "--output-indicator-old=-",
    "--output-indicator-context= ",
    "--unified=3",
  }
  local function run(flags)
    local args = vim.list_extend(vim.deepcopy(command), flags)
    vim.list_extend(args, { base, head, "--" })
    vim.list_extend(args, paths or {})
    local result = vim.system(args, { text = false }):wait()
    if result.code ~= 0 then
      return nil, result.stderr
    end
    return result.stdout or ""
  end
  local names, err = run({ "--name-status", "-z" })
  if not names then
    return nil, err
  end
  local patch
  patch, err = run({ "--patch" })
  if not patch then
    return nil, err
  end
  return M.parse(names, patch, base, head)
end

local function is_nonempty_string(value)
  return type(value) == "string" and value ~= ""
end

function M.plan(catalog, guide)
  local context = guide and guide.context or {}
  if context.base_oid ~= catalog.context.base_oid or context.head_oid ~= catalog.context.head_oid then
    return nil, "Section plan does not match the pinned comparison"
  end
  if type(guide.chunks) ~= "table" or (#guide.chunks == 0 and #catalog.hunks > 0) then
    return nil, "No section plan yet; generate/update the guide"
  end
  local plan = { chunks = {}, by_id = {}, owner = {} }
  for _, raw in ipairs(guide.chunks) do
    if
      type(raw) ~= "table"
      or not is_nonempty_string(raw.id)
      or not is_nonempty_string(raw.title)
      or not is_nonempty_string(raw.summary)
      or type(raw.hunks) ~= "table"
    then
      return nil, "Each section needs a stable id, title, summary, and hunk IDs"
    end
    if plan.by_id[raw.id] then
      return nil, "Duplicate section ID: " .. raw.id
    end
    for _, dependency in ipairs(type(raw.depends_on) == "table" and raw.depends_on or {}) do
      if not plan.by_id[dependency] then
        return nil, "Section dependencies must precede their consumers: " .. tostring(dependency)
      end
    end
    local chunk = {
      id = raw.id,
      title = raw.title:gsub("[\r\n]", " "),
      summary = raw.summary,
      number = #plan.chunks + 1,
      relationship = type(raw.relationship) == "string" and raw.relationship or "",
      depends_on = type(raw.depends_on) == "table" and raw.depends_on or {},
      diagram = guide_view.diagram(raw.diagram),
      checks = guide_view.diagram(raw.checks),
      core_code = guide_view.normalize({ core_code = raw.core_code }).core_code,
      depth = raw.depth,
      hunks = {},
    }
    for _, id in ipairs(raw.hunks) do
      if type(id) ~= "string" or not catalog.by_id[id] then
        return nil, "Unknown hunk ID: " .. tostring(id)
      end
      if plan.owner[id] then
        return nil, "Hunk assigned more than once: " .. id
      end
      plan.owner[id] = chunk.id
      table.insert(chunk.hunks, catalog.by_id[id])
    end
    if #chunk.hunks == 0 then
      return nil, "Empty review section: " .. chunk.title
    end
    plan.by_id[chunk.id] = chunk
    table.insert(plan.chunks, chunk)
  end
  local missing = {}
  for _, hunk in ipairs(catalog.hunks) do
    if not plan.owner[hunk.id] then
      table.insert(missing, hunk.id)
    end
  end
  if #missing > 0 then
    return nil, "Unassigned changed regions: " .. table.concat(missing, ", ")
  end
  return plan
end

function M.read_count(hunks, state)
  local count = 0
  for _, hunk in ipairs(hunks) do
    if (state.read_hunks or {})[hunk.id] then
      count = count + 1
    end
  end
  return count, #hunks
end

function M.section_count(plan, state)
  local complete = 0
  for _, section in ipairs(plan.chunks) do
    local done, total = M.read_count(section.hunks, state)
    if total > 0 and done == total then
      complete = complete + 1
    end
  end
  return complete, #plan.chunks
end

function M.progress_bar(done, total, width)
  width = width or 8
  local filled = total == 0 and 0 or math.floor(done / total * width)
  return ("[%s%s] %d/%d"):format(string.rep("█", filled), string.rep("-", width - filled), done, total)
end

function M.overall_progress(workspace, state, width)
  local catalog = workspace and workspace.catalog
  if catalog then
    local done, total = M.read_count(catalog.hunks, state)
    return M.progress_bar(done, total, width)
  end
end

function M.source(hunk, side)
  side = side or ((hunk.right_count == 0 or hunk.status:sub(1, 1) == "D") and "LEFT" or "RIGHT")
  local first = side == "LEFT" and hunk.left_start or hunk.right_start
  local count = side == "LEFT" and hunk.left_count or hunk.right_count
  return {
    path = side == "LEFT" and (hunk.oldpath or hunk.path) or hunk.path,
    side = side,
    line = hunk.kind == "hunk" and count > 0 and first or nil,
  }
end

function M.jump_source(hunk, catalog)
  local starts = catalog.change_starts[hunk.id]
  if not starts then
    return M.source(hunk)
  end
  local side = starts.RIGHT and "RIGHT" or "LEFT"
  local target = M.source(hunk, side)
  target.line = starts[side] or target.line
  return target
end

local function comment_matches(hunk, comment)
  local file = comment.file or comment.path
  local side = comment.side == "LEFT" and "LEFT" or "RIGHT"
  local file_level = not tonumber(comment.line)
    or require("utils.diffview_review_format").is_file_level_comment(comment)
  if file_level then
    return file ~= nil and (file == hunk.path or file == hunk.oldpath)
  end
  local target = M.source(hunk, side)
  if file ~= target.path then
    return false
  end
  if hunk.kind == "file" then
    return true
  end
  local first = side == "LEFT" and hunk.left_start or hunk.right_start
  local count = side == "LEFT" and hunk.left_count or hunk.right_count
  local start_line = tonumber(comment.start_line) or tonumber(comment.line)
  local end_line = tonumber(comment.end_line) or tonumber(comment.line)
  return count > 0 and math.min(start_line, end_line) < first + count and math.max(start_line, end_line) >= first
end

local function section_matches(section, comment)
  for _, hunk in ipairs(section.hunks) do
    if comment_matches(hunk, comment) then
      return true
    end
  end
  return false
end

function M.comment_hunks(plan, comment)
  local matches = {}
  for _, section in ipairs(plan.chunks) do
    for index, hunk in ipairs(section.hunks) do
      if comment_matches(hunk, comment) then
        table.insert(matches, { section = section, hunk = hunk, index = index })
      end
    end
  end
  return matches
end

function M.hunk_location(hunk, side)
  if hunk.kind == "file" then
    return hunk.header
  end
  local target = M.source(hunk, side)
  local before = target.side == "LEFT"
  local count = before and hunk.left_count or hunk.right_count
  local range = count == 0 and "no lines"
    or (count == 1 and tostring(target.line) or ("%d–%d"):format(target.line, target.line + count - 1))
  return (before and "Before " or "After ") .. range
end

-- Keep actual snapshot line numbers: fold the complement, never manufacture commits or excerpt buffers.
function M.hidden_ranges(hunks, path, side, count)
  local visible = {}
  for _, hunk in ipairs(hunks) do
    if hunk.path == path then
      if hunk.kind == "file" then
        return {}
      end
      local first = side == "LEFT" and hunk.left_start or hunk.right_start
      local size = side == "LEFT" and hunk.left_count or hunk.right_count
      if size == 0 then
        first, size = math.max(1, first), 1
      end
      if first < 1 or first + size - 1 > count then
        return nil, "Hunk range exceeds the loaded revision buffer"
      end
      table.insert(visible, { first, first + size - 1 })
    end
  end
  table.sort(visible, function(a, b)
    return a[1] < b[1]
  end)
  local hidden, first = {}, 1
  for _, range in ipairs(visible) do
    if range[1] > first then
      table.insert(hidden, { first, range[1] - 1 })
    end
    first = math.max(first, range[2] + 1)
  end
  if first <= count then
    table.insert(hidden, { first, count })
  end
  return hidden
end

function M.lines(workspace, state)
  local lines, targets, sections, code_rows = {}, {}, {}, {}
  local function add(value, id, target)
    for index, line in ipairs(guide_view.diagram(value)) do
      table.insert(lines, line)
      if index == 1 and id then
        sections[#lines] = { id = id, label = line }
      end
      if index == 1 and target then
        targets[#lines] = target
      end
    end
  end
  if not workspace or not workspace.plan then
    add(workspace and workspace.error or "Generate the guide to build a section plan.", "availability")
    return lines, targets, sections
  end
  if workspace.source_error then
    add("Source focus unavailable: " .. workspace.source_error, "source-error")
  end
  local active = workspace.plan.by_id[workspace.active]
  if not active then
    add("## 🔬 Section guide", "section-guide")
    add("Select a section above to see its guide and focused diff.")
    return lines, targets, sections
  end
  add("")
  add(
    "## 🔬 Section "
      .. active.number
      .. ": "
      .. active.title
      .. (active.depth == "skim" and " · 👀 Skim" or " · 🔎 Careful reading"),
    "purpose:" .. active.id
  )
  add(active.summary)
  if #active.checks > 0 then
    add("")
    add("### 👀 What to look for", "checks:" .. active.id)
    for _, check in ipairs(active.checks) do
      add("- " .. check)
    end
  end
  if active.relationship and active.relationship ~= "" then
    add("")
    add("### 🔗 Place in the PR", "relationship:" .. active.id)
    add(active.relationship)
  end
  if #active.diagram > 0 then
    add("")
    add("### 🗺️ Section diagram", "diagram-heading:" .. active.id)
    add(active.diagram, "diagram:" .. active.id)
  end
  if #active.core_code > 0 then
    add("")
    add("### 💻 Core code", "core-heading:" .. active.id)
  end
  for _, block in ipairs(active.core_code) do
    add("")
    add(block.label .. " — " .. block.title, "core:" .. active.id .. ":" .. (block.id or block.title))
    local language, style = guide_view.code_language(block, workspace.guide)
    add("```" .. language)
    local first = #lines + 1
    add(block.code)
    for row = first, #lines do
      code_rows[row] = style or language
    end
    add("```")
    for _, source in ipairs(block.sources) do
      local label, target = guide_view.source_link(source, workspace.guide)
      add(label, nil, target)
    end
  end
  -- Comments keep their original state and coordinates; show those intersecting this chunk.
  local discussions = false
  for _, comment in ipairs(require("utils.diffview_review_threads").list(state)) do
    if section_matches(active, comment) then
      add("")
      if not discussions then
        add("### 💬 Discussions", "discussions:" .. active.id)
        discussions = true
      end
      add(comment.body, "comment:" .. tostring(comment.id or comment.body), comment)
    end
  end
  return lines, targets, sections, code_rows
end

return M
