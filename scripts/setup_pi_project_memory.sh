#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail

[ "$#" -eq 0 ] || { echo "This script takes no arguments." >&2; exit 1; }

agent_root="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
link="$agent_root/projects-memory"
target="$HOME/notes/pi-memory/projects"

if [ -e "$link" ] || [ -L "$link" ]; then
    if [ ! -L "$link" ] || [ "$(readlink "$link")" != "$target" ]; then
        echo "Refusing to replace $link; see ~/notes/README.md for migration." >&2
        exit 1
    fi
fi
if [ ! -e "$target" ] && [ ! -L "$target" ]; then
    echo "Warning: $target is missing; clone notes and rerun to link memory." >&2
    exit 0
fi
if [ ! -d "$target" ] || [ -L "$target" ]; then
    echo "Expected a real directory: $target" >&2
    exit 1
fi
[ -L "$link" ] && exit 0
mkdir -p "$agent_root"
ln -s "$target" "$link"
echo "Linked $link -> $target"
