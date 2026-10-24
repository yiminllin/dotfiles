#!/usr/bin/env bash

# Optional full TeX distribution; run separately from the default installer.
set -e
set -o pipefail

case "$(uname -s)" in
    Darwin)
        if ! command -v brew >/dev/null 2>&1; then
            echo "Homebrew is required. Run the default dotfiles installer first." >&2
            exit 1
        fi
        brew install --cask mactex
        ;;
    Linux)
        if [ -f /etc/os-release ] && grep -Eiq "debian|ubuntu" /etc/os-release; then
            sudo apt-get update
            sudo apt-get install -y texlive-full
        elif [ -f /etc/os-release ] && grep -Eiq "fedora" /etc/os-release; then
            sudo dnf install -y texlive-scheme-full
        else
            echo "Unsupported Linux distribution. Install TeX manually." >&2
            exit 1
        fi
        ;;
    *)
        echo "Unsupported OS. Install TeX manually." >&2
        exit 1
        ;;
esac
