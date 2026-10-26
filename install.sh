#!/bin/bash

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_ONCHANGE="$SCRIPT_DIR/scripts/run_onchange.sh"
cd "$SCRIPT_DIR"

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

run_manifest_step() {
    local key="$1"
    local manifest="$2"
    shift 2

    if [ -x "$RUN_ONCHANGE" ]; then
        "$RUN_ONCHANGE" "$key" "$manifest" -- "$@"
    else
        "$@"
    fi
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
    sudo dnf install -y dnf-plugins-core
    sudo dnf copr enable -y dejan/lazygit
    sudo dnf install -y $(sed 's/#.*//;/^$/d' Dnffile)
fi

if is_macos; then
    if ! command -v brew >/dev/null 2>&1; then
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi

    # Homebrew is not automatically added to PATH by its installer on a
    # fresh macOS installation, especially on Apple Silicon.
    if [ -x /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi

    command -v brew >/dev/null 2>&1 || {
        echo "Homebrew was installed but could not be found in PATH" >&2
        exit 1
    }
    brew bundle --file="$SCRIPT_DIR/Brewfile"
fi

################################################################################
# Install Kitty
################################################################################

echo "Installing Kitty"
curl -L https://sw.kovidgoyal.net/kitty/installer.sh | sh /dev/stdin
if is_macos; then
    mkdir -p ~/.local/bin
    ln -sfn ~/.local/kitty.app/bin/kitty ~/.local/bin/kitty
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
if [ -d "$HOME/.fzf/.git" ]; then
    git -C "$HOME/.fzf" pull --ff-only
elif [ -e "$HOME/.fzf" ] || [ -L "$HOME/.fzf" ]; then
    echo "Existing ~/.fzf is not a Git checkout. Move it aside and rerun." >&2
    exit 1
else
    git clone --depth 1 https://github.com/junegunn/fzf.git "$HOME/.fzf"
fi
~/.fzf/install --all --no-update-rc
export PATH="$HOME/.fzf/bin:$PATH"

################################################################################
# Install Languages
################################################################################

echo "Installing languages"
# Install rustup without modifying shell configs
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path
curl -fsSL https://install.julialang.org | sh -s -- --yes --add-to-path=no
# Install fnm without modifying shell configs
curl -fsSL https://fnm.vercel.app/install | bash -s -- --skip-shell
curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
if is_debian; then
    curl -fLO https://go.dev/dl/go1.25.5.linux-amd64.tar.gz && sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf go1.25.5.linux-amd64.tar.gz && rm -rf go1.25.5.linux-amd64.tar.gz
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
# v0.31.x currently contains a replace directive, which Go rejects for
# versioned installs. Keep this pinned until upstream publishes a fixed release.
go install go.abhg.dev/gs@v0.30.1
go install github.com/ankitpokhrel/jira-cli/cmd/jira@latest

################################################################################
# Install Cargo and UV Packages
################################################################################

echo "Installing Cargo and UV packages"
run_manifest_step cargo-tools Cargofile bash -c "sed 's/#.*//;/^$/d' Cargofile | xargs -n1 cargo install"
run_manifest_step uv-tools Uvfile bash -c "sed 's/#.*//;/^$/d' Uvfile | xargs -n1 uv tool install"

################################################################################
# Install Keymapping Packages
################################################################################

echo "Installing Keymapping packages"
if is_fedora; then
    # Build in a temporary directory so rerunning the installer is safe even
    # when a previous clone or failed build was left in the repository.
    (
        keyd_build_dir="$(mktemp -d "${TMPDIR:-/tmp}/dotfiles-keyd.XXXXXX")"
        trap 'rm -rf "$keyd_build_dir"' EXIT
        git clone https://github.com/rvaiya/keyd "$keyd_build_dir/keyd"
        make -C "$keyd_build_dir/keyd"
        sudo make -C "$keyd_build_dir/keyd" install
    )
fi

################################################################################
# Install td
################################################################################

echo "Installing td"
cargo install --path "$SCRIPT_DIR/td" --root "$HOME/.cargo" --locked

################################################################################
# Install Pi
################################################################################
if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required to install Pi; install Node with fnm and rerun install.sh" >&2
    exit 1
fi
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
bash "$SCRIPT_DIR/scripts/setup_pi_project_memory.sh" || exit 1

################################################################################
# Stow Configs
################################################################################

echo "Stowing configurations"

CONFIGS=(
    bash
    bat
    fish
    flightsystems
    git
    kitty
    nvim
    pi
    tmux
    visidata
)

# Stow has no built-in backup-and-replace mode. Back up conflicting files first
# so the repository remains authoritative, while preserving existing files for
# recovery. Symlinks already pointing into this repository can be replaced.
BACKUP_DIR="$HOME/.dotfiles-backups/$(date +%Y%m%d-%H%M%S)-$$"
REPO_REALPATH="$(cd "$SCRIPT_DIR" && pwd -P)"

is_repo_symlink() {
    local path="$1"
    local resolved

    [ -L "$path" ] || return 1
    resolved="$(realpath "$path" 2>/dev/null)" || return 1
    [ "$resolved" = "$REPO_REALPATH" ] ||
        [[ "$resolved" == "$REPO_REALPATH"/* ]]
}

has_repo_symlink_ancestor() {
    local path="$1"
    local parent

    while [ "$path" != "$HOME" ] && [[ "$path" == "$HOME"/* ]]; do
        if is_repo_symlink "$path"; then
            return 0
        fi
        parent="$(dirname "$path")"
        [ "$parent" = "$path" ] && break
        path="$parent"
    done
    return 1
}

backup_stow_conflicts() {
    local config="$1"
    local source relative target backup_target

    # Stow may fold package directories into a symlink. Handle those directory
    # links explicitly; find -type l only sees symlinks inside the package.
    while IFS= read -r -d '' source; do
        [ "$source" = "$config" ] && continue
        relative="${source#"$config"/}"
        target="$HOME/$relative"

        [ -L "$target" ] || continue
        if is_repo_symlink "$target"; then
            rm "$target"
            echo "Removed existing repository symlink: $target"
        else
            backup_target="$BACKUP_DIR/$relative"
            mkdir -p "$(dirname "$backup_target")"
            mv "$target" "$backup_target"
            echo "Backed up conflicting symlink: $target"
        fi
    done < <(find "$config" -type d -print0)

    while IFS= read -r -d '' source; do
        [ "$source" = "$config" ] && continue
        relative="${source#"$config"/}"
        target="$HOME/$relative"

        [ -e "$target" ] || [ -L "$target" ] || continue

        if [ "$target" = "$HOME/.gitconfig" ] && command -v mountpoint >/dev/null 2>&1 && mountpoint -q "$target"; then
            continue
        fi

        # A package may already be exposed through a repo-owned directory link.
        # Do not move files through that link into the backup directory.
        if has_repo_symlink_ancestor "$target" && ! is_repo_symlink "$target"; then
            continue
        fi

        if is_repo_symlink "$target"; then
            rm "$target"
            echo "Removed existing repository symlink: $target"
            continue
        fi

        backup_target="$BACKUP_DIR/$relative"
        mkdir -p "$(dirname "$backup_target")"
        mv "$target" "$backup_target"
        echo "Backed up conflicting target: $target"
    done < <(find "$config" \( -type f -o -type l \) -print0)
}

for config in "${CONFIGS[@]}"; do
    backup_stow_conflicts "$config"
    if [ "$config" = git ] && command -v mountpoint >/dev/null 2>&1 && mountpoint -q "$HOME/.gitconfig"; then
        stow --ignore='^\.gitconfig$' "$config"
    else
        stow "$config"
    fi
done

if is_fedora; then
    sudo ln -sfn "$SCRIPT_DIR/keyd/default.conf" /etc/keyd/default.conf
fi

################################################################################
# Install Tmux Packages
################################################################################
if [ ! -d ~/.tmux/plugins/tpm ]; then
    git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm 
    ~/.tmux/plugins/tpm/bin/install_plugins
fi

echo "Complete!"
