# Dotfiles Repository Development Guidelines

## Project Overview
- Type: Personal Dotfile Configuration
- Primary Languages: Lua (Neovim), Shell Scripts
- Target Platforms: macOS, Debian, Fedora

## Setup & Dependencies
- Install: `./install.sh`
- Required Tools: Neovim, Lua 5.1+, Fish shell
- Dependency Management: Homebrew, DNF, APT

## Code Style Guidelines
1. **Lua Conventions**:
   - Use 2-space soft tabs
   - Prefer `local` variables
   - Use `vim.opt` and `vim.g` for Neovim config
   - Meaningful, descriptive names
   - Utilize `pcall()` for error handling

2. **File Structure**:
   - `init.lua`: Main entry point
   - `lua/settings.lua`: Global settings
   - `lua/keymaps.lua`: Keyboard mappings
   - `lua/autocmds.lua`: Event handlers

## Plugin Management
- Uses lazy.nvim
- Plugins in `nvim/.config/nvim/lua/plugins/`
- Clear documentation for each plugin

## Testing & Validation
- Manual configuration testing
- Cross-platform (macOS) compatibility
- Validate plugin interactions

## Commit Guidelines
- Small, focused commits
- Descriptive messages
- No sensitive information

## Linting & Formatting
- Lua: Use `stylua` for formatting
- No global configuration for other languages

## Comprehensive Repository Description

### What are Dotfiles?
Dotfiles are configuration files in Unix-like systems that start with a dot (.) and are typically hidden from standard file listings. They are used to customize various applications and system behaviors.

### Repository Characteristics
- **Purpose**: Personal development environment configuration
- **Cross-Platform Support**: 
  - macOS
  - Debian/Ubuntu
  - Fedora

### Configured Tools
- Neovim (advanced text editor)
- Fish shell
- Git
- tmux
- Kitty terminal
- Various development plugins and tools

### Key Features
- Automated installation via `./install.sh`
- Uses `stow` for managing symlinks
- Supports multiple package managers (Homebrew, DNF, APT)
- Custom scripts for auto-updating configurations
- Special key mappings (e.g., Caps Lock mapped to {ESC, CTRL})

### Installation Process
1. Clone the repository
2. Navigate to the dotfiles directory
3. Run `./install.sh`
4. Perform tool-specific setup (Copilot, GitHub CLI, etc.)