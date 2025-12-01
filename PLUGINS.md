# Dotfiles Plugins & CLI Tools Summary

## Neovim Plugins

| Category | Plugin | Purpose | Config File |
|----------|----------------|---------|-------------|
| Essential/Core | lazy.nvim | Plugin manager | [init.lua](nvim/.config/nvim/init.lua) |
| Essential/Core | nvim-lspconfig | LSP configuration | [lsp-config.lua](nvim/.config/nvim/lua/plugins/essential/lsp-config.lua) |
| Essential/Core | mason.nvim | LSP/tool installer | [lsp-config.lua](nvim/.config/nvim/lua/plugins/essential/lsp-config.lua) |
| Essential/Core | mason-lspconfig.nvim | Mason-LSP bridge | [lsp-config.lua](nvim/.config/nvim/lua/plugins/essential/lsp-config.lua) |
| Essential/Core | mason-tool-installer.nvim | Auto-install tools | [lsp-config.lua](nvim/.config/nvim/lua/plugins/essential/lsp-config.lua) |
| Essential/Core | fidget.nvim | LSP status notifications | [lsp-config.lua](nvim/.config/nvim/lua/plugins/essential/lsp-config.lua) |
| Essential/Core | nvim-cmp | Autocompletion engine | [nvim-cmp.lua](nvim/.config/nvim/lua/plugins/essential/nvim-cmp.lua) |
| Essential/Core | LuaSnip | Snippet engine | [nvim-cmp.lua](nvim/.config/nvim/lua/plugins/essential/nvim-cmp.lua) |
| Essential/Core | cmp_luasnip | Snippet completion source | [nvim-cmp.lua](nvim/.config/nvim/lua/plugins/essential/nvim-cmp.lua) |
| Essential/Core | cmp-nvim-lsp | LSP completion source | [nvim-cmp.lua](nvim/.config/nvim/lua/plugins/essential/nvim-cmp.lua) |
| Essential/Core | cmp-path | Path completion source | [nvim-cmp.lua](nvim/.config/nvim/lua/plugins/essential/nvim-cmp.lua) |
| Essential/Core | lspkind.nvim | Completion icons | [nvim-cmp.lua](nvim/.config/nvim/lua/plugins/essential/nvim-cmp.lua) |
| Essential/Core | nvim-treesitter | Syntax highlighting & parsing | [treesitter.lua](nvim/.config/nvim/lua/plugins/essential/treesitter.lua) |
| Essential/Core | nvim-treesitter-context | Show code context | [treesitter-context.lua](nvim/.config/nvim/lua/plugins/essential/treesitter-context.lua) |
| Essential/Core | telescope.nvim | Fuzzy finder | [telescope.lua](nvim/.config/nvim/lua/plugins/essential/telescope.lua) |
| Essential/Core | telescope-fzf-native.nvim | FZF integration | [telescope.lua](nvim/.config/nvim/lua/plugins/essential/telescope.lua) |
| Essential/Core | telescope-ui-select.nvim | UI improvements | [telescope.lua](nvim/.config/nvim/lua/plugins/essential/telescope.lua) |
| Essential/Core | snacks.nvim | Modern picker/explorer/UI utilities | [snacks.lua](nvim/.config/nvim/lua/plugins/essential/snacks.lua) |
| Essential/Core | trouble.nvim | Diagnostics & quickfix list | [trouble.lua](nvim/.config/nvim/lua/plugins/essential/trouble.lua) |
| Essential/Core | aerial.nvim | Code outline/symbol navigator | [aerial.lua](nvim/.config/nvim/lua/plugins/essential/aerial.lua) |
| Essential/Core | plenary.nvim | Lua utility library | [telescope.lua](nvim/.config/nvim/lua/plugins/essential/telescope.lua) |
| Essential/Core | nvim-web-devicons | File icons | Multiple plugins |
| Essential/Core | luarocks.nvim | Lua package manager integration | [luarocks.lua](nvim/.config/nvim/lua/plugins/essential/luarocks.lua) |
| Essential/Core | wilder.nvim | Enhanced command/search UI | [wilder.lua](nvim/.config/nvim/lua/plugins/essential/wilder.lua) |
| Essential/Core | vim-tmux-navigator | Seamless tmux/vim navigation | [vim-tmux-navigator.lua](nvim/.config/nvim/lua/plugins/essential/vim-tmux-navigator.lua) |
| Essential/Core | persistence.nvim | Session management | [persistence.lua](nvim/.config/nvim/lua/plugins/essential/persistence.lua) |
| Editing | conform.nvim | Code formatter | [conform.lua](nvim/.config/nvim/lua/plugins/editing/conform.lua) |
| Editing | Comment.nvim | Toggle comments | [comment.lua](nvim/.config/nvim/lua/plugins/editing/comment.lua) |
| Editing | nvim-autopairs | Auto-close brackets | [nvim-autopairs.lua](nvim/.config/nvim/lua/plugins/editing/nvim-autopairs.lua) |
| Editing | which-key.nvim | Keymap helper | [which-key.lua](nvim/.config/nvim/lua/plugins/editing/which-key.lua) |
| Editing | todo-comments.nvim | Highlight TODO/FIXME | [todo-comments.lua](nvim/.config/nvim/lua/plugins/editing/todo-comments.lua) |
| Editing | vim-sleuth | Auto-detect indentation | [sleuth.lua](nvim/.config/nvim/lua/plugins/editing/sleuth.lua) |
| Editing | venn.nvim | ASCII diagram drawing | [venn.lua](nvim/.config/nvim/lua/plugins/editing/venn.lua) |
| Editing | debugprint.nvim | Debug print statements | [debugprint.lua](nvim/.config/nvim/lua/plugins/editing/debugprint.lua) |
| Editing | kitty-scrollback.nvim | Kitty terminal integration | [kitty-scrollback.lua](nvim/.config/nvim/lua/plugins/editing/kitty-scrollback.lua) |
| Git | gitsigns.nvim | Git signs in gutter | [gitsigns.lua](nvim/.config/nvim/lua/plugins/git/gitsigns.lua) |
| Git | diffview.nvim | Git diff viewer | [diffview.lua](nvim/.config/nvim/lua/plugins/git/diffview.lua) |
| Git | gitlinker.nvim | Generate git links | [gitlinker.lua](nvim/.config/nvim/lua/plugins/git/gitlinker.lua) |
| UI/Visual | gruvbox.nvim | Gruvbox color scheme | [colorscheme.lua](nvim/.config/nvim/lua/plugins/ui/colorscheme.lua) |
| UI/Visual | lualine.nvim | Status line | [lualine.lua](nvim/.config/nvim/lua/plugins/ui/lualine.lua) |
| UI/Visual | indent-blankline.nvim | Indent guides | [indent-blankline.lua](nvim/.config/nvim/lua/plugins/ui/indent-blankline.lua) |
| UI/Visual | nvim-colorizer.lua | Color code highlighting | [nvim-colorizer.lua](nvim/.config/nvim/lua/plugins/ui/nvim-colorizer.lua) |
| UI/Visual | neoscroll.nvim | Smooth scrolling | [neoscroll.lua](nvim/.config/nvim/lua/plugins/ui/neoscroll.lua) |
| UI/Visual | oil.nvim | File browser | [oil.lua](nvim/.config/nvim/lua/plugins/ui/oil.lua) |
| UI/Visual | zen-mode.nvim | Distraction-free mode | [zenmode.lua](nvim/.config/nvim/lua/plugins/ui/zenmode.lua) |
| Languages | markview.nvim | Markdown preview | [markview.lua](nvim/.config/nvim/lua/plugins/languages/markview.lua) |
| Languages | bazel.nvim | Bazel build system support | [bazel.lua](nvim/.config/nvim/lua/plugins/languages/bazel.lua) |
| AI | opencode.nvim | AI code assistant integration | [opencode.lua](nvim/.config/nvim/lua/plugins/ai/opencode.lua) |
| Misc | leetcode.nvim | LeetCode integration | [leetcode.lua](nvim/.config/nvim/lua/plugins/misc/leetcode.lua) |

---

## CLI Tools

### Rust Tools (via Cargo)
| Tool | Purpose | Install File |
|------|---------|--------------|
| ripgrep | Fast grep replacement | [Cargofile](Cargofile) |
| fd-find | Fast find replacement | [Cargofile](Cargofile) |
| bat | Cat with syntax highlighting | [Cargofile](Cargofile) |
| eza | Modern ls replacement | [Cargofile](Cargofile) |
| git-delta | Better git diff | [Cargofile](Cargofile) |
| du-dust | Disk usage analyzer | [Cargofile](Cargofile) |
| tokei | Line counter | [Cargofile](Cargofile) |
| zoxide | Smart cd replacement | [Cargofile](Cargofile) |
| aichat | CLI AI chat tool | [Cargofile](Cargofile) |
| vivid | LS_COLORS generator | [Cargofile](Cargofile) |

### Python Tools (via UV)
| Tool | Purpose | Install File |
|------|---------|--------------|
| ipython | Enhanced Python REPL | [Uvfile](Uvfile) |
| rexi | Interactive regex testing | [Uvfile](Uvfile) |
| visidata | CSV/data visualization & editing | [Uvfile](Uvfile) |
| pynvim | Python client for Neovim | [Uvfile](Uvfile) |
| black | Python formatter | [Uvfile](Uvfile) |
| isort | Python import sorter | [Uvfile](Uvfile) |
| jupytext | Jupyter notebook text format | [Uvfile](Uvfile) |
| jupyter-client | Jupyter kernel client | [Uvfile](Uvfile) |

### System Packages
| Category | Tool | Purpose | Install File |
|----------|------|---------|--------------|
| Essential | tmux | Terminal multiplexer | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | neovim | Text editor | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | fish | Shell | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | curl | HTTP client | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | wget | File downloader | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | stow | Symlink manager | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | unzip | Archive extractor | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Essential | tldr | Command documentation | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Utilities | ncdu | Disk usage analyzer (TUI) | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Utilities | btop | System monitor | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Utilities | nvtop | GPU monitor | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Utilities | lazygit | Git TUI | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Utilities | gh | GitHub CLI | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Utilities | task/taskwarrior | Task manager | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Utilities | tmuxinator | Tmux session manager | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Clipboard | xsel | X11 clipboard (Linux) | [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Clipboard | xclip | X11 clipboard (Linux) | [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Clipboard | wl-clipboard | Wayland clipboard (Fedora) | [Dnffile](Dnffile) |

---

## Languages & Development Tools

### Language Runtimes
| Language | Tool | Install Method |
|----------|------|----------------|
| Rust | rustup | [install.sh](install.sh) |
| Julia | juliaup | [install.sh](install.sh) |
| Node.js | fnm (Fast Node Manager) | [install.sh](install.sh) |
| Python | uv | [install.sh](install.sh) |
| Python | python@3.12 | [Brewfile](Brewfile), [Aptfile](Aptfile) |
| Lua | lua/lua5.4 | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| Ruby | ruby | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |

### Language Servers (via Mason)
| Language | LSP | Purpose |
|----------|-----|---------|
| C/C++ | clangd | C/C++ language server |
| Lua | lua_ls | Lua language server |
| Julia | julials | Julia language server |
| Rust | rust_analyzer | Rust language server |
| Python | pyright | Python language server |
| Markdown | marksman | Markdown language server |

### Formatters & Linters
| Tool | Purpose | Install Method |
|------|---------|----------------|
| stylua | Lua formatter | Via Mason |
| clang-format | C/C++ formatter | Via Mason, [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |
| black | Python formatter | Via Mason, [Uvfile](Uvfile) |
| isort | Python import sorter | Via Mason, [Uvfile](Uvfile) |
| rustfmt | Rust formatter | Via Mason |
| prettier | Multi-language formatter | Via Mason |

### Build Tools & Compilers
| Tool | Purpose | Install Method |
|------|---------|----------------|
| llvm/clang | C/C++ compiler | [Brewfile](Brewfile), [Dnffile](Dnffile) |
| gcc/gcc-c++ | C/C++ compiler | [Aptfile](Aptfile), [Dnffile](Dnffile) |
| make | Build automation | [Aptfile](Aptfile), [Dnffile](Dnffile) |

### Package Managers
| Tool | Purpose | Install Method |
|------|---------|----------------|
| luarocks | Lua package manager | [Brewfile](Brewfile), [Aptfile](Aptfile), [Dnffile](Dnffile) |

### Dependencies
| Tool | Purpose | Install Method |
|------|---------|----------------|
| imagemagick | Image processing (for image.nvim) | [Brewfile](Brewfile), [Aptfile](Aptfile) |
| libmagickwand-dev | ImageMagick development files | [Aptfile](Aptfile) |

### Fonts
| Font | Purpose | Install Method |
|------|---------|----------------|
| CommitMono Nerd Font | Nerd font with icons | [Brewfile](Brewfile), [install.sh](install.sh) (Fedora) |

---

## Tmux Plugins

| Plugin | Purpose | Config File |
|--------|---------|-------------|
| tpm | Tmux Plugin Manager | [.tmux.conf](tmux/.tmux.conf) |
| tmux-sensible | Better defaults | [.tmux.conf](tmux/.tmux.conf) |
| tmux-fzf | Fuzzy finder for tmux | [.tmux.conf](tmux/.tmux.conf) |
| tmux-resurrect | Save/restore sessions | [.tmux.conf](tmux/.tmux.conf) |
| tmux-continuum | Auto-save sessions | [.tmux.conf](tmux/.tmux.conf) |
| tmux-copycat | Enhanced search in copy mode | [.tmux.conf](tmux/.tmux.conf) |
| tmux-powerline | Better status line | [.tmux.conf](tmux/.tmux.conf) |
| vim-tmux-navigator | Seamless vim/tmux navigation | [.tmux.conf](tmux/.tmux.conf) |

---

## Fish Plugins

| Plugin | Purpose | Config File |
|--------|---------|-------------|
| fzf.fish | FZF integration for Fish | [fish_plugins](fish/.config/fish/fish_plugins) |

---

## Additional Tools

| Tool | Purpose | Install Method |
|------|---------|----------------|
| kitty | Terminal emulator | [install.sh](install.sh) |
| fzf | Fuzzy finder | [install.sh](install.sh) |
| opencode | AI coding assistant | [install.sh](install.sh) |
| keyd | Key remapping (Linux) | [install.sh](install.sh) (Fedora) |

---
