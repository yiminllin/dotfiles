#!/bin/bash
# Minimal dotfiles install: fish, nvim (lightweight), tmux, fzf, ripgrep, fd, bat, eza, delta.
# Entry point: ./install_minimal.sh
# Stows: lightweight/fish, lightweight/nvim, lightweight/tmux

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

is_debian() {
  [ -f /etc/os-release ] && grep -Eiq "debian|ubuntu" /etc/os-release
}

is_fedora() {
  [ -f /etc/os-release ] && grep -Eiq "fedora" /etc/os-release
}

is_macos() {
  [ "$(uname -s)" = "Darwin" ]
}

################################################################################
# System packages: fish, neovim, tmux, ripgrep, stow (fzf from git below)
# Snacks.nvim needs Neovim >= 0.9.4; on Debian we use tarball for latest.
################################################################################
echo "[minimal] Installing system packages..."

mkdir -p ~/.config ~/.local/bin

if is_debian; then
  sudo apt-get update
  sudo apt-get install -y fish tmux ripgrep stow git curl xclip
  # Optional: fd-find, bat, eza, git-delta (may be missing on older Debian/Ubuntu)
  for pkg in fd-find bat eza git-delta; do
    sudo apt-get install -y "$pkg" 2>/dev/null || echo "[minimal] Skip $pkg (not in repo)."
  done
  # Neovim from tarball so we get 0.9.4+ (required by snacks.nvim)
  echo "[minimal] Installing Neovim from release tarball..."
  arch=$(uname -m)
  if [ "$arch" = "x86_64" ]; then
    nvim_tarball="/tmp/nvim-linux-x86_64.tar.gz"
    nvim_url="https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz"
    nvim_dir="nvim-linux-x86_64"
  elif [ "$arch" = "aarch64" ] || [ "$arch" = "arm64" ]; then
    nvim_tarball="/tmp/nvim-linux-arm64.tar.gz"
    nvim_url="https://github.com/neovim/neovim/releases/latest/download/nvim-linux-arm64.tar.gz"
    nvim_dir="nvim-linux-arm64"
  else
    echo "[minimal] Unsupported architecture: $arch. Install Neovim manually."; exit 1
  fi
  curl -fSL -o "$nvim_tarball" "$nvim_url" || { echo "[minimal] Failed to download Neovim."; exit 1; }
  sudo rm -rf /opt/nvim-linux-x86_64 /opt/nvim-linux64 /opt/nvim-linux-arm64
  sudo tar -C /opt -xzf "$nvim_tarball"
  rm -f "$nvim_tarball"
  if [ -x "/opt/$nvim_dir/bin/nvim" ]; then
    ln -sf "/opt/$nvim_dir/bin/nvim" ~/.local/bin/nvim
  else
    echo "[minimal] Neovim binary not found after extract. Check tarball layout."; exit 1
  fi
  # Debian/Ubuntu: fd is fdfind, bat is batcat; symlink so fd/bat work
  if command -v fdfind &>/dev/null && ! command -v fd &>/dev/null; then
    ln -sf "$(command -v fdfind)" ~/.local/bin/fd
  fi
  if command -v batcat &>/dev/null && ! command -v bat &>/dev/null; then
    ln -sf "$(command -v batcat)" ~/.local/bin/bat
  fi
  export PATH="$HOME/.local/bin:$PATH"
elif is_fedora; then
  sudo dnf makecache --refresh
  sudo dnf install -y fish neovim tmux ripgrep stow git curl xclip fd-find bat eza delta
elif is_macos; then
  if ! command -v brew &>/dev/null; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  fi
  # Ensure brewed binaries are in PATH (ARM: /opt/homebrew, Intel: /usr/local)
  export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
  brew install fish neovim tmux ripgrep stow git curl fd bat eza git-delta
  # macOS has pbcopy/pbpaste; no xclip needed
else
  echo "Unsupported OS. Install manually: fish, neovim, tmux, ripgrep, stow."
  exit 1
fi

################################################################################
# Fzf (clone and install, no shell rc changes)
################################################################################
echo "[minimal] Installing fzf..."
rm -rf ~/.fzf
git clone --depth 1 https://github.com/junegunn/fzf.git ~/.fzf
~/.fzf/install --all --no-update-rc
export PATH="$HOME/.fzf/bin:$PATH"

################################################################################
# Stow minimal configs (~/.config created above)
################################################################################
echo "[minimal] Stowing lightweight fish, nvim, tmux..."

# Require lightweight config dirs (script must run from repo root)
for pkg in fish nvim tmux; do
  if [ ! -d "lightweight/$pkg" ]; then
    echo "[minimal] Missing lightweight/$pkg. Run from repo root."; exit 1
  fi
done

# Backups and cleanup (must succeed or stow will fail)
for name in fish nvim; do
  target=~/.config/"$name"
  if [ -L "$target" ]; then
    # Remove existing symlink (may conflict with stow)
    rm -f "$target"
  elif [ -d "$target" ]; then
    if ! mv "$target" "$target".bak."$$"; then
      echo "[minimal] Could not backup $target. Remove or rename it, then re-run."; exit 1
    fi
  fi
done
if [ -L ~/.tmux.conf ]; then
  rm -f ~/.tmux.conf
elif [ -f ~/.tmux.conf ]; then
  if ! mv ~/.tmux.conf ~/.tmux.conf.bak."$$"; then
    echo "[minimal] Could not backup ~/.tmux.conf. Remove or rename it, then re-run."; exit 1
  fi
fi

# Stow from lightweight/
stow -d lightweight -t ~ fish
stow -d lightweight -t ~ nvim
stow -d lightweight -t ~ tmux

################################################################################
# Git: use delta as pager for diffs
################################################################################
if command -v delta &>/dev/null; then
  git config --global core.pager delta
fi

################################################################################
# Fish fzf plugin (optional: keybindings in fish)
################################################################################
if command -v fish &>/dev/null; then
  echo "[minimal] Installing fish fzf plugin (fisher + fzf.fish)..."
  fish -c "curl -sL https://raw.githubusercontent.com/jorgebucaran/fisher/main/functions/fisher.fish -o /tmp/fisher.fish && source /tmp/fisher.fish && fisher install patrickf1/fzf.fish" 2>/dev/null || true
fi

echo "[minimal] Done. Start fish and run: nvim, tmux; use <leader>sf / <leader>sg in nvim for search."
