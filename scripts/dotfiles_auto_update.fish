#!/usr/bin/env fish

# Dotfiles auto-update and config reload script
if test -d ~/dotfiles
    cd ~/dotfiles

    # Try to pull. --ff-only ensures it aborts if there is a merge conflict.
    if git pull --ff-only >/dev/null 2>&1
        # Update Neovim plugins
        nvim --headless "+Lazy! sync" +qa >/dev/null 2>&1

        # Update Fish plugins
        fish -c "fisher update" >/dev/null 2>&1

        # Update Tmux plugins
        if test -f ~/.tmux/plugins/tpm/bin/update_plugins
            ~/.tmux/plugins/tpm/bin/update_plugins all >/dev/null 2>&1
        end

        # Reload configs
        source ~/.config/fish/config.fish >/dev/null 2>&1
        if type -q tmux
            tmux source-file ~/.tmux.conf >/dev/null 2>&1
        end
        
        echo "Dotfiles updated"
    else
        echo "Merge conflict - manual resolution required"
    end

    cd -
end
