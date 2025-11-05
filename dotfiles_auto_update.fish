#!/usr/bin/env fish

# Dotfiles auto-update and config reload script
if test -d ~/dotfiles
    cd ~/dotfiles
    git pull --ff-only
    cd -
    # Reload configs
    nvim --headless +"Lazy sync" +q
    source ~/.config/fish/config.fish
    if type -q tmux
        tmux source-file ~/.tmux.conf
    end
end
