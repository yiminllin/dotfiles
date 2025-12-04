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
fi

if is_debian; then
    sudo apt-get update
    sudo apt-get install -y software-properties-common
    # sudo add-apt-repository ppa:lazygit-team/release
    sed 's/#.*//;/^$/d' Aptfile | xargs sudo apt-get install -y
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
~/.fzf/install --all

################################################################################
# Install Languages
################################################################################

echo "Installing languages"
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
curl -fsSL https://install.julialang.org | sh -s -- --yes
curl -fsSL https://fnm.vercel.app/install | bash
curl -LsSf https://astral.sh/uv/install.sh | sh

source $HOME/.cargo/env
export PATH="$HOME/.juliaup/bin:$PATH"
export PATH="$HOME/.local/share/fnm:$PATH"
eval "$(fnm env --use-on-cd)"
export PATH="$HOME/.local/bin:$PATH"

fnm install --lts
uv python install

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

if is_macos; then
    mkdir -p ~/.task/themes/
    # solarized-light does not work on macOS...
    curl -o ~/.task/themes/solarized-256.theme https://raw.githubusercontent.com/GothenburgBitFactory/taskwarrior/develop/doc/rc/solarized-dark-256.theme
    sed -i '' 's/color.alternate=on color0/color.alternate=/g' ~/.task/themes/solarized-256.theme
fi

if is_fedora || is_debian; then
    mkdir -p ~/.task/themes/
    curl -o ~/.task/themes/solarized-256.theme https://raw.githubusercontent.com/GothenburgBitFactory/taskwarrior/develop/doc/rc/solarized-light-256.theme
fi

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

CONFIGS=(
    aichat
    bash
    bat
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
