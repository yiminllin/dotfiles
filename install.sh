#!/bin/bash

set -e
set -o pipefail

################################################################################
# Install System Packages
################################################################################

echo "Installing system packages"

if grep -Eiq "debian|ubuntu" /etc/os-release; then
    apt-get update
    apt-get install -y software-properties-common
    add-apt-repository ppa:lazygit-team/release
    sed 's/#.*//;/^$/d' Aptfile | xargs apt-get install -y
fi

if grep -Eiq "fedora" /etc/os-release; then
    sudo dnf makecache --refresh
    sudo dnf copr enable dejan/lazygit
    sudo dnf install -y dnf-plugins-core
    sudo dnf install -y $(sed 's/#.*//;/^$/d' Dnffile)
fi

if [ "$(uname -s)" = "Darwin" ]; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  brew bundle --file="Brewfile"
fi

################################################################################
# Install Kitty
################################################################################

echo "Installing Kitty"
curl -L https://sw.kovidgoyal.net/kitty/installer.sh | sh /dev/stdin
ln -sf ~/.local/kitty.app/bin/kitty ~/.local/bin/kitty
# Setup Fedora desktop entries and fonts
if grep -Eiq "fedora" /etc/os-release; then
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
# Stow Configs
################################################################################

echo "Stowing configurations"

# Cleanups
mv ~/.bash_profile ~/.bash_profile.backup
mv ~/.bashrc ~/.bashrc.backup
rm -rf ~/.config/fish

CONFIGS=(
    aichat
    bash
    bat
    fish
    git
    kitty
    nvim
    tmux
    visidata
)
for config in "${CONFIGS[@]}"; do
    stow "$config"
done

################################################################################
# Install Tmux Packages
################################################################################
git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm 
~/.tmux/plugins/tpm/bin/install_plugins

echo "Complete!"
