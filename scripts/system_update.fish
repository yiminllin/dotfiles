#!/usr/bin/env fish

# Helper functions
function is_debian; test -f /etc/os-release && grep -Eiq "debian|ubuntu" /etc/os-release; end
function is_fedora; test -f /etc/os-release && grep -Eiq "fedora" /etc/os-release; end
function is_macos; test (uname -s) = "Darwin"; end

echo "Starting system update..."

# OS Package Updates
if is_debian
    sudo apt-get update >/dev/null 2>&1 && sudo apt-get upgrade -y >/dev/null 2>&1
    echo "Updated Debian packages"
else if is_fedora
    sudo dnf upgrade -y >/dev/null 2>&1
    echo "Updated Fedora packages"
else if is_macos
    brew update >/dev/null 2>&1 && brew upgrade >/dev/null 2>&1
    brew cleanup >/dev/null 2>&1
    echo "Updated Homebrew packages"
end

# Rust & Cargo Tools
rustup update >/dev/null 2>&1
if test -f ~/dotfiles/Cargofile
    cat ~/dotfiles/Cargofile | sed 's/#.*//;/^$/d' | xargs -n1 cargo install >/dev/null 2>&1
end
echo "Updated Rust/Cargo tools"

# UV Tools
if type -q uv
    uv tool upgrade --all >/dev/null 2>&1
    echo "Updated UV tools"
end

# Node/FNM
if type -q fnm
    fnm install --lts >/dev/null 2>&1
    echo "Updated Node LTS"
end

# OpenCode
curl -fsSL https://opencode.ai/install | bash >/dev/null 2>&1
echo "Updated OpenCode"

echo "System update complete"
