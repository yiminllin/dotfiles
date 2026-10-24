# Development guidelines

Personal dotfiles for macOS, Debian/Ubuntu, and Fedora. Main languages: Lua and shell.

- Install with `./install.sh`; use `./install_minimal.sh` for the lightweight setup.
- Manage symlinks with Stow and platform packages with Homebrew, APT, or DNF.
- Neovim uses lazy.nvim. Plugin specs live in `nvim/.config/nvim/lua/plugins/`.
- Keep Neovim entry, settings, mappings, and events in `init.lua`, `lua/settings.lua`, `lua/keymaps.lua`, and `lua/autocmds.lua`.
- Lua: use 2-space indentation, local variables, descriptive names, `vim.opt`/`vim.g`, and `pcall()` for error handling. Format with Stylua.
- Run `scripts/check_dotfiles.sh` and test affected workflows, plugin interactions, and macOS compatibility. No global formatter is prescribed for other languages.
- Keep commits small and descriptive. Never commit secrets.
- Keep Markdown concise: simple technical English, short active sentences, and no repeated context. Preserve commands, behavior, requirements, and uncertainty. Link detailed guides instead of repeating them.
- Update `PLUGINS.md` when installed tools or plugins change.
- When removing, replacing, deprecating, or making a dependency optional, add it to `GONE_BUT_NOT_FORGOTTEN.md`: one table with linked names and short technical descriptions. Avoid duplicates; exclude version, install-method, and file-location changes.
- Keep shell setup in tracked config. Disable installer profile edits and leave generated plugin files ignored.
