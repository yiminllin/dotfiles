# Dotfiles Plugins & CLI Tools Summary

## Neovim Plugins


| Category | Plugin | Purpose | Config File |
|----------|----------------|---------|-------------|
| Essential/Core | lazy.nvim | Plugin manager | [.lua](nvim/.config/nvim/init.lua) |
| Essential/Core | nvim-lspconfig | LSP configuration | [.lua](nvim/.config/nvim/lua/plugins/essential/lsp-config.lua) |
| Essential/Core | mason.nvim | LSP/tool installer | [.lua](nvim/.config/nvim/lua/plugins/essential/lsp-config.lua) |
| Essential/Core | mason-lspconfig.nvim | LSP/tool installer | [.lua](nvim/.config/nvim/lua/plugins/essential/lsp-config.lua) |
| Essential/Core | mason-lspconfig.nvim | LSP/tool installer | [.lua](nvim/.config/nvim/lua/plugins/essential/lsp-config.lua) |
| Essential/Core | mason-tool-installer.nvim | Auto-install tools | [.lua](nvim/.config/nvim/lua/plugins/essential/lsp-config.lua) |
| Essential/Core | fidget.nvim | LSP status notifications | [.lua](nvim/.config/nvim/lua/plugins/essential/lsp-config.lua) |
| Essential/Core | nvim-cmp | Autocompletion engine | [.lua](nvim/.config/nvim/lua/plugins/essential/nvim-cmp.lua) |
| Essential/Core | LuaSnip | Snippet engine | [.lua](nvim/.config/nvim/lua/plugins/essential/nvim-cmp.lua) |
| Essential/Core | cmp_luasnip | Snippet completion source | [.lua](nvim/.config/nvim/lua/plugins/essential/nvim-cmp.lua) |
| Essential/Core | cmp-nvim-lsp | LSP completion source | [.lua](nvim/.config/nvim/lua/plugins/essential/nvim-cmp.lua) |
| Essential/Core | cmp-path | Path completion source | [.lua](nvim/.config/nvim/lua/plugins/essential/nvim-cmp.lua) |
| Essential/Core | lspkind.nvim | Completion icons | [.lua](nvim/.config/nvim/lua/plugins/essential/nvim-cmp.lua) |
| Essential/Core | nvim-treesitter | Syntax highlighting & parsing | [.lua](nvim/.config/nvim/lua/plugins/essential/treesitter.lua) |
| Essential/Core | nvim-treesitter-context | Show code context | [.lua](nvim/.config/nvim/lua/plugins/essential/treesitter-context.lua) |
| Essential/Core | telescope.nvim | Fuzzy finder | [.lua](nvim/.config/nvim/lua/plugins/essential/telescope.lua) |
| Essential/Core | telescope-fzf-native.nvim | FZF integration | [.lua](nvim/.config/nvim/lua/plugins/essential/telescope.lua) |
| Essential/Core | telescope-ui-select.nvim | UI improvements | [.lua](nvim/.config/nvim/lua/plugins/essential/telescope.lua) |
| Essential/Core | snacks.nvim | Modern picker/explorer/UI utilities | [.lua](nvim/.config/nvim/lua/plugins/essential/snacks.lua) |
| Essential/Core | plenary.nvim | Lua utility library | [.lua](nvim/.config/nvim/lua/plugins/essential/telescope.lua) |
| Essential/Core | nvim-web-devicons | File icons | Multiple plugins |
| Essential/Core | luarocks.nvim | Lua package manager integration | [.lua](nvim/.config/nvim/lua/plugins/essential/luarocks.lua) |
| Essential/Core | wilder.nvim | Enhanced command/search UI | [.lua](nvim/.config/nvim/lua/plugins/essential/wilder.lua) |
| Editing | conform.nvim | Code formatter | [.lua](nvim/.config/nvim/lua/plugins/editing/conform.lua) |
| Editing | Comment.nvim | Toggle comments | [.lua](nvim/.config/nvim/lua/plugins/editing/comment.lua) |
| Editing | nvim-autopairs | Auto-close brackets | [.lua](nvim/.config/nvim/lua/plugins/editing/nvim-autopairs.lua) |
| Editing | which-key.nvim | Keymap helper | [.lua](nvim/.config/nvim/lua/plugins/editing/which-key.lua) |
| Editing | todo-comments.nvim | Highlight TODO/FIXME | [.lua](nvim/.config/nvim/lua/plugins/editing/todo-comments.lua) |
| Editing | vim-sleuth | Auto-detect indentation | [.lua](nvim/.config/nvim/lua/plugins/editing/sleuth.lua) |
| Editing | venn.nvim | ASCII diagram drawing | [.lua](nvim/.config/nvim/lua/plugins/editing/venn.lua) |
| Editing | kitty-scrollback.nvim | Kitty terminal integration | [.lua](nvim/.config/nvim/lua/plugins/editing/kitty-scrollback.lua) |
| Git | gitsigns.nvim | Git signs in gutter | [.lua](nvim/.config/nvim/lua/plugins/git/gitsigns.lua) |
| Git | diffview.nvim | Git diff viewer | [.lua](nvim/.config/nvim/lua/plugins/git/diffview.lua) |
| Git | gitlinker.nvim | Generate git links | [.lua](nvim/.config/nvim/lua/plugins/git/gitlinker.lua) |
| UI/Visual | gruvbox.nvim | Gruvbox color scheme | [.lua](nvim/.config/nvim/lua/plugins/ui/colorscheme.lua) |
| UI/Visual | lualine.nvim | Status line | [.lua](nvim/.config/nvim/lua/plugins/ui/lualine.lua) |
| UI/Visual | indent-blankline.nvim | Indent guides | [.lua](nvim/.config/nvim/lua/plugins/ui/indent-blankline.lua) |
| UI/Visual | nvim-colorizer.lua | Color code highlighting | [.lua](nvim/.config/nvim/lua/plugins/ui/nvim-colorizer.lua) |
| UI/Visual | neoscroll.nvim | Smooth scrolling | [.lua](nvim/.config/nvim/lua/plugins/ui/neoscroll.lua) |
| UI/Visual | nvim-tree.lua | File explorer | [.lua](nvim/.config/nvim/lua/plugins/ui/nvim-tree.lua) |
| UI/Visual | oil.nvim | File browser | [.lua](nvim/.config/nvim/lua/plugins/ui/oil.lua) |
| UI/Visual | aerial.nvim | Code outline/symbol navigator | [.lua](nvim/.config/nvim/lua/plugins/essential/aerial.lua) |
| UI/Visual | zen-mode.nvim | Distraction-free mode | [.lua](nvim/.config/nvim/lua/plugins/ui/zenmode.lua) |
| AI/Coding | opencode.nvim | AI code assistant integration | [.lua](nvim/.config/nvim/lua/plugins/ai/opencode.lua) |
| Misc | telekasten.nvim | Zettelkasten note-taking | [.lua](nvim/.config/nvim/lua/plugins/misc/telekasten.lua) |
| Misc | leetcode.nvim | LeetCode integration | [.lua](nvim/.config/nvim/lua/plugins/misc/leetcode.lua) |
| Misc | bazel.nvim | Bazel build system support | [.lua](nvim/.config/nvim/lua/plugins/languages/bazel.lua) |

---

## CLI Tools

| Category | Tool | Purpose | Install File |
|----------|------|---------|--------------|
| CLI Improvement | ripgrep | Fast grep replacement | [Cargofile](Cargofile) |
| CLI Improvement | fd-find | Fast find replacement | [Cargofile](Cargofile) |
| CLI Improvement | bat | Cat with syntax highlighting | [Cargofile](Cargofile) |
| CLI Improvement | eza | Modern ls replacement | [Cargofile](Cargofile) |
| CLI Improvement | git-delta | Better git diff | [Cargofile](Cargofile) |
| CLI Improvement | du-dust | Disk usage analyzer | [Cargofile](Cargofile) |
| CLI Improvement | tokei | Line counter | [Cargofile](Cargofile) |
| CLI Improvement | zoxide | Smart cd replacement | [Cargofile](Cargofile) |
| Tool | aichat | CLI AI chat tool | [Cargofile](Cargofile) |
| Tool | vivid | Syntax highlighting for ripgrep | [Cargofile](Cargofile) |
| Essential | tmux | Terminal multiplexer | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | neovim | Text editor | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | fish | Shell | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | curl | HTTP client | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | wget | File downloader | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | stow | Symlink manager | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | unzip | Archive extractor | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | tldr | Command documentation | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Monitoring/Utilities | ncdu | Disk usage analyzer (TUI) | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Monitoring/Utilities | btop | System monitor | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Monitoring/Utilities | nvtop | GPU monitor | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Monitoring/Utilities | lazygit | Git UI | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Monitoring/Utilities | gh | GitHub CLI | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Monitoring/Utilities | task/taskwarrior | Task manager | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |

---

## Languages & Development Tools

| Category | Tool | Purpose |
|----------|------|---------|
| Language Server | clangd | C/C++ LSP |
| Language Server | lua_ls | Lua LSP |
| Language Server | julials | Julia LSP |
| Language Server | rust_analyzer | Rust LSP |
| Language Server | pyright | Python LSP |
| Formatter | stylua | Lua formatter |
| Formatter | clang-format | C/C++ formatter |
| Formatter | black | Python formatter |
| Formatter | isort | Python import sorter |
| Compiler | llvm/clang | C/C++ compiler |
| Interpreter | python@3.12 | Python interpreter |
| Interpreter | lua | Lua interpreter |
| Package Manager | luarocks | Lua package manager |
| Dependency | imagemagick | Image processing |
| Font | font-commit-mono-nerd-font | Nerd font for icons |

---
