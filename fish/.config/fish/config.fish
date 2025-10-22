if status is-interactive
    # Commands to run in interactive sessions can go here
end

################################################################################
# Theme
################################################################################
. ~/.config/fish/themes/solarized.fish

################################################################################
# Scrollback pager
################################################################################
function tmux_scrollback_pager
    tmux capture-pane -S - -p > /tmp/tmux_full_scrollback.txt && /home/yiminlin/.local/share/bob/nvim-bin/nvim -c "normal G" /tmp/tmux_full_scrollback.txt
end

################################################################################
# Abbreviations
################################################################################
# Better defaults
abbr -a cp cp -ir
abbr -a mv mv -i
abbr -a rm rm -ir

# Better CLI tools
abbr -a v nvim
abbr -a ls eza -lah --git
abbr -a cat batcat
abbr -a du dust
abbr -a top btop

# Convenience
abbr -a ... cd ../..
abbr -a .... cd ../../..
abbr -a gs git status
abbr -a gd git diff
abbr -a gp git push
abbr -a vdesk ssh -L 8888:localhost:8888 yilin@yilin.vdesk.cloud.aurora.tech
abbr -a sb tmux_scrollback_pager


################################################################################
# FZF
################################################################################
fzf --fish | source
