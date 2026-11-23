local M = {}

function M.diagram(value)
  if type(value) == "string" then
    return vim.split(value, "\n", { plain = true })
  end
  local lines = {}
  for _, line in ipairs(type(value) == "table" and value or {}) do
    if type(line) == "string" then
      for _, part in ipairs(vim.split(line, "\n", { plain = true })) do
        table.insert(lines, part)
      end
    end
  end
  return lines
end

function M.progress(entries, current, phoenix, width)
  local position
  for index, item in ipairs(entries) do
    if item.path == current then
      position = index
      break
    end
  end
  local scope = phoenix and "Phoenix" or "All"
  if #entries == 0 then
    return scope .. " · no matching files"
  end
  local count = tostring(position or "-") .. "/" .. #entries
  local text = scope .. " · position " .. count
  return width and vim.fn.strdisplaywidth(text) > width and (scope .. " " .. count) or text
end

local function append_text(lines, value)
  vim.list_extend(lines, M.diagram(value))
end

local function core_sections(guide)
  local sections, seen = {}, {}
  for _, block in ipairs(guide and guide.core_code or {}) do
    local _, source = M.source((block.sources or {})[1], guide)
    local anchor = source and (source.path .. ":" .. source.side .. ":" .. source.line)
    local key = block.id or anchor or (block.label .. " — " .. block.title)
    seen[key] = (seen[key] or 0) + 1
    table.insert(sections, { id = "core:" .. key .. ":" .. seen[key], label = block.title, block = block })
  end
  return sections
end

function M.source(source, guide)
  local path, first, last, revision, side, text
  if type(source) == "table" then
    path, first, last, revision, side = source.path, source.line, source.end_line, source.revision, source.side
    text = tostring(path or "?")
      .. ":"
      .. tostring(first or "?")
      .. (last and ("-" .. tostring(last)) or "")
      .. " at "
      .. tostring(revision or side or "?")
  else
    text = tostring(source)
    local location
    location, revision = text:match("^(.-)%s+at%s+(%S+)$")
    if location then
      path, first, last = location:match("^(.-):(%d+)%-(%d+)$")
      if not path then
        path, first = location:match("^(.-):(%d+)$")
      end
      local without_symbol = path and path:match("^(.-):[^/:]+$")
      if without_symbol and guide.files_by_path[without_symbol] and not guide.files_by_path[path] then
        path = without_symbol
      end
    end
  end
  local context = guide.context or {}
  if not revision then
    revision = side == "LEFT" and context.base_oid or (side == "RIGHT" and context.head_oid or nil)
  end
  if revision == "base" then
    revision = context.base_oid
  end
  if revision == "head" then
    revision = context.head_oid
  end
  local base, head = context.base_oid, context.head_oid
  if type(revision) == "string" and #revision >= 7 then
    local is_base = base and base:sub(1, #revision) == revision
    local is_head = head and head:sub(1, #revision) == revision
    if is_base and not is_head then
      revision, side = base, side or "LEFT"
    end
    if is_head and not is_base then
      revision, side = head, side or "RIGHT"
    end
  end
  last = last or first
  first = (type(first) == "number" or type(first) == "string") and tonumber(first) or nil
  last = (type(last) == "number" or type(last) == "string") and tonumber(last) or nil
  if
    type(path) ~= "string"
    or not first
    or not last
    or first % 1 ~= 0
    or last % 1 ~= 0
    or first < 1
    or last < first
    or (side ~= "LEFT" and side ~= "RIGHT")
    or revision ~= (side == "LEFT" and base or head)
  then
    return text
  end
  return text, { path = path, line = first, end_line = last, side = side, revision = revision }
end

function M.source_link(source, guide)
  local text, target = M.source(source, guide)
  if not target then
    return "Source: " .. text, nil
  end
  local range = tostring(target.line)
  if target.end_line ~= target.line then
    range = range .. "-" .. target.end_line
  end
  return ("↗ %s:%s · %s"):format(vim.fs.basename(target.path), range, target.side == "LEFT" and "Before" or "After"),
    target
end

function M.code_language(block, guide)
  local label = vim.trim(block.label):lower()
  if label:find("pseudocode", 1, true) or label:find("pseudo-code", 1, true) then
    return "text", "pseudocode"
  end
  if label ~= "source excerpt" then
    return "text"
  end
  for _, source in ipairs(block.sources or {}) do
    local _, target = M.source(source, guide)
    if target then
      local filetype = vim.filetype.match({ filename = target.path })
      local lang = filetype and vim.treesitter.language.get_lang(filetype)
      if
        lang
        and lang:match("^[%w_]+$")
        and #vim.api.nvim_get_runtime_file("queries/" .. lang .. "/highlights.scm", false) > 0
      then
        local ok, loaded = pcall(vim.treesitter.language.add, lang)
        if ok and loaded then
          return lang
        end
      end
    end
  end
  return "text"
end

local function legacy_sections(guide, entries)
  local chunks, seen, summaries = {}, {}, {}
  for _, file in ipairs(guide and guide.files or {}) do
    local stage = file.stage and vim.trim(file.stage:gsub("[\r\n]", " "))
    if stage and not summaries[stage] then
      summaries[stage] = file.reason
    end
  end
  for _, item in ipairs(entries) do
    local file = guide and guide.files_by_path[item.path]
    local stage = file and file.stage and vim.trim(file.stage:gsub("[\r\n]", " "))
    if not stage or stage == "" then
      stage = item.path
    end
    local chunk = chunks[#chunks]
    if not chunk or chunk.stage ~= stage then
      local name = file and file.stage and stage:gsub("^%d+[.)]%s*", "") or stage
      seen[name] = (seen[name] or 0) + 1
      chunk = {
        id = "chunk:" .. name .. ":" .. seen[name],
        name = name,
        stage = stage,
        files = {},
        summary = summaries[stage] or (file and file.reason),
        number = file and file.stage and stage:match("^(%d+)[.)]%s*") or tostring(#chunks + 1),
      }
      table.insert(chunks, chunk)
    end
    table.insert(chunk.files, { item = item, guide = file })
  end
  return chunks
end

local function reading_label(reason)
  local text = (" " .. (reason or "")):gsub("(%s)%[([^%]]+)%]$", function(space, tag)
    local key = vim.trim(tag:gsub("^🔎%s*", ""):gsub("^👀%s*", "")):lower()
    local label = ({
      ["read carefully"] = "🔎 Careful reading",
      ["careful reading"] = "🔎 Careful reading",
      deep = "🔎 Careful reading",
      skim = "👀 Skim",
      ["optional/generated"] = "👀 Skim · optional/generated",
    })[key]
    return space .. "[" .. (label or tag) .. "]"
  end)
  return text:sub(2)
end

function M.lines(guide, entries, current, phoenix, status, workspace, state, opts)
  opts = opts or {}
  local lines, targets, sections, code_rows = {}, {}, {}, {}
  local divider = string.rep("─", math.max(1, (opts.width or 72) - 2))
  local function section(id, label)
    table.insert(lines, label)
    sections[#lines] = { id = id, label = label }
  end
  local overall = require("utils.diffview_review_chunks").overall_progress(workspace, state or {})
  if overall then
    section("overall-progress", "Overall review  " .. overall .. " hunks")
    table.insert(lines, "")
  end
  if status then
    local label = ({
      queued = "queued",
      running = "updating guide…",
      completed = "guide ready",
      failed = "guide update failed",
    })[status.status]
    if label then
      table.insert(lines, "Main Pi: " .. label)
    end
    if status.error then
      append_text(lines, status.error)
    end
    table.insert(lines, "")
  end
  if guide then
    section("overview", "## 🧭 PR overview")
    table.insert(lines, divider)
  end
  if guide then
    table.insert(lines, "")
    section("goal", "### 🎯 Goal")
    append_text(lines, guide.summary)
    local behavior = guide.behavior_change or {}
    if behavior.before and behavior.before ~= "" then
      table.insert(lines, "")
      append_text(lines, "Before: " .. behavior.before)
    end
    if behavior.after and behavior.after ~= "" then
      append_text(lines, "After: " .. behavior.after)
    end
    table.insert(lines, "")
    section("diagram", "### 🗺️ PR flow / code diagram")
    table.insert(lines, "")
    append_text(lines, guide.diagram)
    if #guide.diagram == 0 then
      table.insert(lines, "No diagram yet; press r to update the guide.")
    end
    table.insert(lines, "")
    section("core", "### 💻 Core code changes")
    for _, part in ipairs(core_sections(guide)) do
      local block = part.block
      table.insert(lines, "")
      section(part.id, block.label .. " — " .. block.title)
      local language, style = M.code_language(block, guide)
      table.insert(lines, "```" .. language)
      local first = #lines + 1
      append_text(lines, block.code)
      for row = first, #lines do
        code_rows[row] = style or language
      end
      table.insert(lines, "```")
      for _, source in ipairs(block.sources or {}) do
        local text, target = M.source_link(source, guide)
        table.insert(lines, text)
        targets[#lines] = target
      end
    end
    if #(guide.core_code or {}) == 0 then
      table.insert(lines, "Core code is not included yet; press r to update the guide.")
    end
  elseif not guide then
    section("availability", "Guide not ready; press r to generate it in the main Pi session, or continue reviewing.")
  end
  table.insert(lines, "")
  if workspace and workspace.plan then
    table.insert(lines, divider)
    section("route", "## 📚 Review sections · Enter opens · v viewed")
    local chunks_view = require("utils.diffview_review_chunks")
    local counts, completed = {}, 0
    for _, chunk in ipairs(workspace.plan.chunks) do
      local viewed, total = chunks_view.read_count(chunk.hunks, state or {})
      counts[chunk.id] = chunks_view.progress_bar(viewed, total)
      if total > 0 and viewed == total then
        completed = completed + 1
      end
    end
    table.insert(lines, "Sections viewed  " .. chunks_view.progress_bar(completed, #workspace.plan.chunks))
    for _, chunk in ipairs(workspace.plan.chunks) do
      local visible = not workspace.visible or #workspace.visible(chunk) > 0
      local prefix = (chunk.id == workspace.active and "> " or "  ") .. counts[chunk.id] .. "  "
      local title = ("%d. %s"):format(chunk.number, chunk.title)
      section(
        "chunk:" .. chunk.id,
        prefix
          .. title
          .. (visible and "" or " · outside ownership scope")
          .. " — "
          .. chunk.summary:gsub("[\r\n]", " ")
      )
      sections[#lines].title_range = { #prefix, #prefix + #title }
      targets[#lines] = { chunk_id = chunk.id }
      if chunk.id == workspace.active then
        table.insert(lines, "    Hunks viewed     " .. counts[chunk.id])
        local in_scope = {}
        for _, hunk in ipairs(workspace.visible and workspace.visible(chunk) or chunk.hunks) do
          in_scope[hunk.id] = true
        end
        for number, hunk in ipairs(chunk.hunks) do
          local read = state and state.read_hunks and state.read_hunks[hunk.id]
          section(
            "section:hunk:" .. hunk.id,
            ("    • %s %s %d. %s · %s%s"):format(
              workspace.hunk == hunk.id and "▶" or " ",
              read and "✓" or "○",
              number,
              chunks_view.hunk_location(hunk),
              hunk.path:gsub("[\r\n]", " "),
              in_scope[hunk.id] and "" or " · outside ownership scope"
            )
          )
          if in_scope[hunk.id] then
            targets[#lines] = { chunk_id = chunk.id, hunk_id = hunk.id }
          end
          if hunk.file_change then
            table.insert(lines, "        File attributes: " .. hunk.file_change)
          end
        end
      end
    end
    if workspace.error then
      append_text(lines, "Plan update rejected: " .. workspace.error)
    end
  else
    if workspace and workspace.error then
      append_text(lines, "Sections: " .. workspace.error)
    end
    local chunks = legacy_sections(guide, entries)
    section("overview-route", "### 📚 Overview route (current scope)")
    for _, chunk in ipairs(chunks) do
      section("overview:" .. chunk.id, chunk.number .. ". " .. chunk.name)
      sections[#lines].title_range = { 0, #lines[#lines] }
    end
    table.insert(lines, "")
    table.insert(lines, divider)
    section("route", "## 🔬 Section review")
    table.insert(lines, "Enter opens a file or source reference.")
    if #entries == 0 then
      table.insert(lines, phoenix and "No Phoenix-owned changed files at this revision." or "No changed files.")
    end
    local index = 0
    for _, chunk in ipairs(chunks) do
      table.insert(lines, "")
      section(chunk.id, "### 🔬 Section " .. chunk.number .. " — " .. chunk.name)
      table.insert(lines, "")
      local summary = chunk.summary
      append_text(
        lines,
        summary and ("Purpose/change: " .. reading_label(summary):gsub("^Chunk summary:%s*", ""))
          or "No purpose/change summary in this guide yet."
      )
      for _, entry in ipairs(chunk.files) do
        index = index + 1
        local item, file = entry.item, entry.guide
        local reason = file and file.reason ~= summary and file.reason
        section(
          "route:" .. item.path,
          ("%s %s %d. %s%s"):format(
            item.path == current and ">" or " ",
            item.viewed and "[x]" or "[ ]",
            index,
            item.path,
            reason and (" — " .. reading_label(reason):gsub("[\r\n]", " ")) or ""
          )
        )
        targets[#lines] = item
        for suggestion_index, suggestion in ipairs(file and file.suggestions or {}) do
          table.insert(lines, "")
          local body = M.diagram(suggestion.body)
          section("suggestion:" .. item.path .. ":" .. (suggestion.id or suggestion_index), body[1] or "")
          vim.list_extend(lines, body, 2)
          if suggestion.line then
            local source, target = M.source_link({
              path = item.path,
              side = suggestion.side,
              line = suggestion.line,
              end_line = suggestion.end_line,
              revision = (guide.context or {})[suggestion.side == "LEFT" and "base_oid" or "head_oid"],
            }, guide)
            table.insert(lines, source)
            targets[#lines] = target
          else
            table.insert(lines, "Source: " .. item.path .. " (file-level / approximate anchor)")
          end
          if suggestion.why then
            append_text(lines, "Why: " .. suggestion.why)
          end
        end
        if #(file and file.suggestions or {}) > 0 then
          table.insert(lines, "")
        end
      end
    end
  end
  if workspace and workspace.plan then
    table.insert(lines, "")
    table.insert(lines, divider)
    local detail, detail_targets, detail_sections, detail_code =
      require("utils.diffview_review_chunks").lines(workspace, state or {})
    local offset = #lines
    vim.list_extend(lines, detail)
    for row, target in pairs(detail_targets) do
      targets[row + offset] = target
    end
    for row, part in pairs(detail_sections) do
      sections[row + offset] = { id = "section:" .. part.id, label = part.label }
    end
    for row, language in pairs(detail_code or {}) do
      code_rows[row + offset] = language
    end
  end
  return lines, targets, sections, code_rows
end

local function notify(message, level)
  vim.notify(message, level or vim.log.levels.INFO, { title = "Diffview Review" })
end

local function string_list(value)
  if type(value) == "string" and value ~= "" then
    return { value }
  end
  if type(value) ~= "table" then
    return {}
  end

  local result = {}
  for _, item in ipairs(value) do
    if item ~= nil and item ~= vim.NIL and tostring(item) ~= "" then
      table.insert(result, tostring(item))
    end
  end
  return result
end

local function positive_line(value)
  if type(value) ~= "number" and type(value) ~= "string" then
    return nil
  end

  local number = tonumber(value)
  if number and number >= 1 then
    return math.floor(number)
  end
end

local function string_id(value)
  if type(value) == "string" and value ~= "" then
    return value
  end
  if type(value) == "number" then
    return tostring(value)
  end
end

local function normalize_file(path)
  if not path or path == "" then
    return nil
  end

  return path:gsub("\\", "/"):gsub("^%./", "")
end

function M.normalize(decoded)
  if type(decoded) ~= "table" then
    return nil
  end

  local behavior = type(decoded.behavior_change) == "table" and decoded.behavior_change or {}
  local validation = type(decoded.validation) == "table" and decoded.validation or {}
  local guide = {
    context = type(decoded.context) == "table" and decoded.context or {},
    pr_number = type(decoded.pr) == "table" and decoded.pr.number
      or (type(decoded.context) == "table" and decoded.context.pr_number or nil),
    pr_url = type(decoded.pr) == "table" and decoded.pr.url or nil,
    summary = type(decoded.summary) == "string" and decoded.summary or "",
    diagram = M.diagram(decoded.diagram),
    behavior_change = {
      before = type(behavior.before) == "string" and behavior.before or "",
      after = type(behavior.after) == "string" and behavior.after or "",
    },
    core_code = {},
    chunks = type(decoded.chunks) == "table" and decoded.chunks or {},
    validation = {
      review_scope = type(validation.review_scope) == "string" and validation.review_scope or "",
      observed = string_list(validation.observed),
      gaps = string_list(validation.gaps),
    },
    high_risk = string_list(decoded.high_risk),
    files = {},
    files_by_path = {},
  }

  for _, block in ipairs(type(decoded.core_code) == "table" and decoded.core_code or {}) do
    local code = type(block) == "table" and M.diagram(block.code) or {}
    if #code > 0 then
      table.insert(guide.core_code, {
        id = string_id(block.id),
        label = type(block.label) == "string" and block.label or "Core pseudocode",
        title = type(block.title) == "string" and block.title or "Core mechanism",
        code = code,
        sources = type(block.sources) == "table" and vim.deepcopy(block.sources) or string_list(block.sources),
      })
    end
  end

  for _, file in ipairs(type(decoded.files) == "table" and decoded.files or {}) do
    local path = type(file) == "table" and normalize_file(file.path) or nil
    if path and not guide.files_by_path[path] then
      local guide_file = {
        id = string_id(file.guide_id) or string_id(file.id),
        reason = type(file.reason) == "string" and file.reason or nil,
        stage = type(file.stage) == "string" and file.stage or nil,
        path = path,
        suggestions = {},
      }
      for _, suggestion in ipairs(type(file.suggestions) == "table" and file.suggestions or {}) do
        local body = type(suggestion) == "table" and type(suggestion.body) == "string" and vim.trim(suggestion.body)
          or ""
        if body ~= "" then
          local start_line = positive_line(suggestion.line)
          local end_line = positive_line(suggestion.end_line) or start_line
          table.insert(guide_file.suggestions, {
            body = body,
            end_line = end_line,
            id = string_id(suggestion.guide_id) or string_id(suggestion.id),
            line = start_line,
            side = tostring(suggestion.side or "RIGHT"):upper() == "LEFT" and "LEFT" or "RIGHT",
            severity = type(suggestion.severity) == "string" and suggestion.severity or "Medium",
            why = type(suggestion.why) == "string" and suggestion.why or nil,
          })
        end
      end

      table.insert(guide.files, guide_file)
      guide.files_by_path[path] = guide_file
    end
  end

  return guide
end

function M.load(path, context)
  if not path then
    return nil
  end

  local stat = (vim.uv or vim.loop).fs_stat(path)
  local mtime = stat and (tostring(stat.mtime.sec) .. ":" .. tostring(stat.mtime.nsec) .. ":" .. stat.size) or -1
  if mtime == -1 then
    M.cache = { path = path, mtime = mtime, guide = nil }
    return nil
  end
  if M.cache and M.cache.path == path and M.cache.mtime == mtime then
    return M.cache.guide
  end

  local read_ok, lines = pcall(vim.fn.readfile, path)
  if not read_ok then
    notify("Could not read guide JSON: " .. path, vim.log.levels.WARN)
    M.cache = { path = path, mtime = mtime, guide = nil }
    return nil
  end

  local decode_ok, decoded = pcall(vim.fn.json_decode, table.concat(lines, "\n"))
  local guide = decode_ok and M.normalize(decoded) or nil
  if not guide then
    notify("Ignoring invalid guide JSON: " .. path, vim.log.levels.WARN)
  elseif
    context
    and context.head_oid
    and (guide.context.head_oid ~= context.head_oid or guide.context.base_oid ~= context.base_oid)
  then
    notify("Guide is stale for this revision; ask Pi to refresh it", vim.log.levels.WARN)
    guide = nil
  else
    guide.source_path = path
    if context then
      local paths = {}
      for _, file in ipairs(guide.files) do
        table.insert(paths, file.path)
      end
      local order = table.concat(paths, "\n")
      if context.review_order and context.review_order ~= order then
        notify("Guide review order updated; current file and progress were preserved")
      end
      context.review_order = order
    end
    guide.context_pr_number = context and context.pr_number or nil
    guide.repo_key = context and context.repo_key or nil
  end
  M.cache = { path = path, mtime = mtime, guide = guide }
  return guide
end

return M
