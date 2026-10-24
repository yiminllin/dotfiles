#!/usr/bin/env fish

# Helper functions
function is_debian; test -f /etc/os-release && grep -Eiq "debian|ubuntu" /etc/os-release; end
function is_fedora; test -f /etc/os-release && grep -Eiq "fedora" /etc/os-release; end
function is_macos; test (uname -s) = "Darwin"; end

# Keep successful updates quiet and show errors before stopping.
function run_update
    set -l label $argv[1]
    set -e argv[1]
    $argv >/dev/null
    set -l update_status $status
    if test $update_status -ne 0
        echo "Failed: $label (exit $update_status)" >&2
        exit $update_status
    end
    echo "Updated $label"
end

echo "Starting system update..."

# OS Package Updates
if is_debian
    run_update "APT package index" sudo apt-get update
    run_update "Debian packages" sudo apt-get upgrade -y
else if is_fedora
    run_update "Fedora packages" sudo dnf upgrade -y
else if is_macos
    run_update "Homebrew package index" brew update
    run_update "Homebrew packages" brew upgrade
    run_update "Homebrew cleanup" brew cleanup
end

# Rust & Cargo Tools
run_update Rust rustup update
if test -f ~/dotfiles/Cargofile
    while read -l package
        set package (string replace -r '#.*$' '' -- "$package" | string trim)
        if test -n "$package"
            run_update "Cargo tool $package" cargo install "$package"
        end
    end < ~/dotfiles/Cargofile
end

# UV Tools
if type -q uv
    run_update "UV tools" uv tool upgrade --all
end

# Node/FNM
if type -q fnm
    run_update "Node LTS" fnm install --lts
end

# Pi
if not type -q npm
    echo "npm is required to update Pi" >&2
    exit 1
end
run_update Pi npm install -g --ignore-scripts @earendil-works/pi-coding-agent

echo "System update complete"
