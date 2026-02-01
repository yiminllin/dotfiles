#!/bin/bash

set -e
set -o pipefail

################################################################################
# Install System Packages
################################################################################

echo "Installing system packages"

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
# Install latest Nvim on Debian
################################################################################
if is_debian; then
    curl -LO https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz
    sudo rm -rf /opt/nvim-linux-x86_64
    sudo tar -C /opt -xzf nvim-linux-x86_64.tar.gz
    rm -rf nvim-linux-x86_64.tar.gz
fi

if is_debian; then
    sudo apt-get update
    sudo apt-get install -y software-properties-common
    sed 's/#.*//;/^$/d' Aptfile | xargs sudo apt-get install -y
    # Install Lazygit manually
    LAZYGIT_VERSION=$(curl -s "https://api.github.com/repos/jesseduffield/lazygit/releases/latest" | \grep -Po '"tag_name": *"v\K[^"]*')
    curl -Lo lazygit.tar.gz "https://github.com/jesseduffield/lazygit/releases/download/v${LAZYGIT_VERSION}/lazygit_${LAZYGIT_VERSION}_Linux_x86_64.tar.gz"
    tar xf lazygit.tar.gz lazygit
    sudo install lazygit -D -t /usr/local/bin/
    rm -rf lazygit lazygit.tar.gz
fi

if is_fedora; then
    sudo dnf makecache --refresh
    sudo dnf copr enable dejan/lazygit
    sudo dnf install -y dnf-plugins-core
    sudo dnf install -y $(sed 's/#.*//;/^$/d' Dnffile)
fi

if is_macos; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  brew bundle --file="Brewfile"
fi

################################################################################
# Install Kitty
################################################################################

echo "Installing Kitty"
curl -L https://sw.kovidgoyal.net/kitty/installer.sh | sh /dev/stdin
if is_macos; then
    ln -sf ~/.local/kitty.app/bin/kitty ~/.local/bin/kitty
fi
# Setup Fedora desktop entries and fonts
if is_fedora; then
    mkdir -p ~/.local/share/applications/
    cp ~/.local/kitty.app/share/applications/kitty.desktop ~/.local/share/applications/
    update-desktop-database ~/.local/share/applications/

    FONTS_DIR="$HOME/.local/share/fonts"
    mkdir -p $FONTS_DIR
    curl -fL https://github.com/ryanoasis/nerd-fonts/releases/latest/download/CommitMono.zip -o $FONTS_DIR/CommitMono.zip
    unzip "$FONTS_DIR/CommitMono.zip" -d "$FONTS_DIR/CommitMono"
    rm -f "$FONTS_DIR/CommitMono.zip"
    fc-cache -fv
fi

################################################################################
# Install Fzf
################################################################################

echo "Installing Fzf"
rm -rf ~/.fzf/
git clone --depth 1 https://github.com/junegunn/fzf.git ~/.fzf
~/.fzf/install --all --no-update-rc
export PATH="$HOME/.fzf/bin:$PATH"

################################################################################
# Install Languages
################################################################################

echo "Installing languages"
# Install rustup without modifying shell configs
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path
curl -fsSL https://install.julialang.org | sh -s -- --yes
# Install fnm without modifying shell configs
curl -fsSL https://fnm.vercel.app/install | bash -s -- --skip-shell
curl -LsSf https://astral.sh/uv/install.sh | sh
if is_debian; then
    wget https://go.dev/dl/go1.25.5.linux-amd64.tar.gz && rm -rf /usr/local/go && sudo tar -C /usr/local -xzf go1.25.5.linux-amd64.tar.gz && rm -rf go1.25.5.linux-amd64.tar.gz
    export PATH="/usr/local/go/bin:$PATH"
fi

source $HOME/.cargo/env
export PATH="$HOME/.juliaup/bin:$PATH"
export PATH="$HOME/.local/share/fnm:$PATH"
eval "$(fnm env --use-on-cd)"
export PATH="$HOME/.local/bin:$PATH"

fnm install --lts
uv python install

################################################################################
# Install Git Spice
################################################################################
go install go.abhg.dev/gs@latest

################################################################################
# Install TDF
################################################################################
cargo install --git https://github.com/itsjunetime/tdf.git

################################################################################
# Setup python venv for neovim
################################################################################
uv venv ~/.venv/neovim
~/.venv/neovim/bin/python3 -m ensurepip --upgrade
~/.venv/neovim/bin/python3 -m pip install pynvim

################################################################################
# Install Cargo, UV, Luarocks Packages
################################################################################

echo "Installing Cargo and UV packages"
sed 's/#.*//;/^$/d' Cargofile | xargs -n1 cargo install
sed 's/#.*//;/^$/d' Uvfile | xargs -n1 uv tool install
# sed 's/#.*//;/^$/d' Luarocksfile | xargs -n1 luarocks install

################################################################################
# Install Keymapping Packages
################################################################################

echo "Installing Keymapping packages"
if is_fedora; then
    git clone https://github.com/rvaiya/keyd
    cd keyd
    make && sudo make install
    cd .. && rm -rf keyd
fi

################################################################################
# Install Task
################################################################################

# Install Taskwarrior from source on Linux
if is_fedora || is_debian; then
    echo "Installing Taskwarrior from source"
    TASK_VERSION="3.4.2"
    curl -LO "https://github.com/GothenburgBitFactory/taskwarrior/releases/download/v${TASK_VERSION}/task-${TASK_VERSION}.tar.gz"
    tar xzvf "task-${TASK_VERSION}.tar.gz"
    cd "task-${TASK_VERSION}"
    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
    cmake --build build
    sudo cmake --install build
    cd ..
    rm -rf "task-${TASK_VERSION}" "task-${TASK_VERSION}.tar.gz"
fi

# Task theme is managed via stow (task/.task/themes/solarized.theme)

################################################################################
# Install OpenCode
################################################################################
curl -fsSL https://opencode.ai/install | bash

################################################################################
# Install Cursor-Agent CLI
################################################################################
curl https://cursor.com/install -fsS | bash

################################################################################
# Stow Configs
################################################################################

echo "Stowing configurations"

# Cleanups
if [ -e ~/.bash_profile ]; then
    mv ~/.bash_profile ~/.bash_profile.backup
fi
if [ -e ~/.bashrc ]; then
    mv ~/.bashrc ~/.bashrc.backup
fi
rm -rf ~/.config/fish

# Clean up auto-generated lines from installers that don't support suppression flags
# (opencode and cursor installers may still modify .bashrc)
if [ -e ~/.bashrc ]; then
    sed -i '/export PATH=.*\/home\/.*\/\.opencode\/bin/d' ~/.bashrc
    sed -i '/source.*bazel-complete\.bash/d' ~/.bashrc
fi

CONFIGS=(
    aichat
    bash
    bat
    codex
    cursor-agent
    fish
    git
    kitty
    nvim
    opencode
    task
    tmux
    tmux-powerline
    tmuxinator
    visidata
)
for config in "${CONFIGS[@]}"; do
    stow --adopt "$config"
done

if is_fedora; then
    sudo ln -s ~/dotfiles/keyd/default.conf /etc/keyd/default.conf
fi

################################################################################
# Install Fish Plugins
################################################################################
fish -c "curl -sL https://raw.githubusercontent.com/jorgebucaran/fisher/main/functions/fisher.fish -o /tmp/fisher.fish && source /tmp/fisher.fish && fisher install patrickf1/fzf.fish"

################################################################################
# Install Tmux Packages
################################################################################
if [ ! -d ~/.tmux/plugins/tpm ]; then
    git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm 
    ~/.tmux/plugins/tpm/bin/install_plugins
fi

echo "Complete!"
