local M = {}
local codeowners = require("utils.codeowners")
local PHOENIX = "@ZiplineTeam/phoenix-reviewers"

-- Keep Git's reconciliation order intact. Only the panel's list is reordered;
-- its entries are the same objects used by the diff layouts and native Tab.
local function ordered_files(files, order)
  local result = require("diffview.vcs.file_dict").FileDict()
  for index, set in ipairs(files.sets) do
    local positions, copy = {}, result.sets[index]
    for position, entry in ipairs(set) do
      copy[position] = entry
      positions[entry] = position
    end
    table.sort(copy, function(a, b)
      local ar, br = order[a.path] or math.huge, order[b.path] or math.huge
      if ar ~= br then
        return ar < br
      end
      return positions[a] < positions[b]
    end)
  end
  return result
end

function M.apply_order(view, guide)
  local scope, panel = view.review_scope, view.panel
  if not scope or not scope.presentation then
    return
  end
  local order, paths = {}, {}
  for index, file in ipairs(guide and guide.files or {}) do
    if not order[file.path] then
      order[file.path] = index
      table.insert(paths, file.path)
    end
  end
  local key = table.concat(paths, "\n")
  if key == scope.order_key then
    return
  end
  local selected = panel:is_open() and panel:get_item_at_cursor() or nil
  if next(order) and not next(scope.order) then
    scope.panel_style = panel.listing_style
  elseif not next(order) and next(scope.order) then
    panel.listing_style = scope.panel_style
  end
  scope.order, scope.order_key = order, key
  panel:update_components()
  panel:render()
  panel:redraw()
  selected = selected and selected.layout and selected or panel.cur_file
  if selected then
    panel:highlight_file(selected)
  end
end

function M.attach(view, root, head)
  if view.review_scope then
    return view.review_scope
  end
  local scope = { enabled = false, root = root, head = head, order = {}, order_key = "" }
  view.review_scope = scope
  if not head or not view.get_updated_files then
    return scope
  end
  local update_components = view.panel.update_components
  scope.presentation = true
  view.panel.update_components = function(panel)
    if next(scope.order) then
      panel.listing_style = "list" -- A directory tree cannot express an arbitrary review route.
      panel.files = ordered_files(view.files, scope.order)
    else
      panel.files = view.files
    end
    update_components(panel)
  end
  local get_updated_files = view.get_updated_files
  -- Filter complete FileEntry objects, not Git pathspecs: preserve renames and revision buffers.
  view.get_updated_files = require("diffview.async").wrap(function(self, callback)
    get_updated_files(
      self,
      vim.schedule_wrap(function(err, files)
        if not err and scope.enabled then
          for _, set in ipairs(files.sets) do
            for index = #set, 1, -1 do
              if not codeowners.owned_by(scope.rules, set[index].path, PHOENIX) then
                local entry = table.remove(set, index)
                entry:destroy()
              end
            end
          end
          files:update_file_trees()
        end
        callback(err, files)
      end)
    )
  end)
  return scope
end

function M.set(scope, enabled)
  if enabled then
    if not scope.head then
      return false, "Open an immutable review before filtering by CODEOWNERS"
    end
    if not scope.rules then
      local rules, err = codeowners.read(scope.root, scope.head)
      if not rules then
        return false, err
      end
      scope.rules = rules
    end
  end
  scope.enabled = enabled
  return true
end

return M
