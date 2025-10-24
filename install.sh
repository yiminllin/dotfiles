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
    sed 's/#.*//;/^$/d' Aptfile | xargs apt-get install -y
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
sed 's/#.*//;/^$/d' Luarocksfile | xargs -n1 luarocks install

################################################################################
# Stow Configs
################################################################################

echo "Stowing configurations"

# Cleanups
mv ~/.bashrc ~/.bashrc.backup
rm -rf ~/.config/fish

CONFIGS=(
    bash
    bat
    fish
    git
    kitty
    nvim
    tmux
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
