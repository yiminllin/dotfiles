#!/usr/bin/env fish

# Dotfiles auto-update and config reload script
if test -d ~/dotfiles
    cd ~/dotfiles
    set run_onchange ./scripts/run_onchange.sh

    # Try to pull. --ff-only ensures it aborts if there is a merge conflict.
    if git pull --ff-only >/dev/null 2>&1
        # Update Neovim plugins
        if test -x $run_onchange
            $run_onchange nvim-plugins nvim/.config/nvim/lua/plugins nvim/.config/nvim/lazy-lock.json -- bash -c 'nvim --headless "+Lazy! sync" +qa >/dev/null 2>&1'
        else
            nvim --headless "+Lazy! sync" +qa >/dev/null 2>&1
        end

        # Update Fish plugins
        if test -x $run_onchange
            $run_onchange fish-plugins fish/.config/fish/fish_plugins -- bash -c 'fish -c "fisher update" >/dev/null 2>&1'
        else
            fish -c "fisher update" >/dev/null 2>&1
        end

        # Update Tmux plugins
        if test -f ~/.tmux/plugins/tpm/bin/update_plugins
            if test -x $run_onchange
                $run_onchange tmux-plugins tmux/.tmux.conf -- bash -c '~/.tmux/plugins/tpm/bin/update_plugins all >/dev/null 2>&1'
            else
                ~/.tmux/plugins/tpm/bin/update_plugins all >/dev/null 2>&1
            end
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
