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
    tmux capture-pane -S - -p > /tmp/tmux_full_scrollback.txt && $EDITOR_PATH  -c "normal G" /tmp/tmux_full_scrollback.txt
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
abbr -a vdesk ssh -L 8888:localhost:8888 yilin@yilin.vdesk.cloud.aurora.tech
abbr -a sb tmux_scrollback_pager

# Git
abbr -a gs git status
abbr -a gd git diff
abbr -a ga git add
abbr -a gc --set-cursor 'git commit -m "%"'
abbr -a gp git push

# AIchat
abbr -a ai "aichat --role concise-bot"

# Task
abbr -a t task
abbr -a t0 task project: list
abbr -a ta --set-cursor 'task add "%"'
abbr -a td task done
abbr -a tr task delete
abbr -a te task edit 
abbr -a ts --set-cursor 'task description.has:%'
abbr -a tph "task modify priority:H"
abbr -a tpm "task modify priority:M"
abbr -a tpl "task modify priority:L"
abbr -a tpn "task modify project:note"
abbr -a tpi "task modify project:improve"
abbr -a tpc "task modify project:code"
abbr -a tpr "task modify project:read"
abbr -a tps "task modify project:study"

function nvim_help --description "View command help in vim"
    $argv --help 2>&1 | nvim -R -c 'set ft=man' -
end
abbr -a h nvim_help

# Man pager
set -x MANPAGER 'nvim +Man!'

function rexi_string --description "Test regex on the input string"
    echo $argv | rexi
end
abbr -a rexi rexi_string

# Show hidden files in completion
set -U fish_complete_hidden 1

################################################################################
# FZF
################################################################################
fzf --fish | source

# opencode
fish_add_path ~/.opencode/bin
