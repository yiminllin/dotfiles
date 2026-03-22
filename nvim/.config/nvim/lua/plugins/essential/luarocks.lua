return {
  "vhyrro/luarocks.nvim",
  priority = 1000,
  config = function(plugin, opts)
    local vendor_path = plugin.dir .. "/.rocks/share/lua/5.1/luarocks/vendor/?.lua"

    if not string.find(package.path, vendor_path, 1, true) then
      package.path = vendor_path .. ";" .. package.path
    end

    require("luarocks-nvim").setup(opts)
  end,
}
