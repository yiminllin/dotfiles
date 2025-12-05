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

abbr -a devbox TERM=xterm-256color command kitten ssh -L 3030:localhost:3030 yimin_dev
function to_dev_container_flight_software
    TERM=xterm-256color ssh -L 3030:localhost:3030 -t yimin_dev 'cd ~/github/FlightSystems && direnv exec . devcontainer-fs --flightsystems'
end
abbr -a fs to_dev_container_flight_software 

function find_all_local_zipline_logs
    set log_paths_joined (find ~/github/FlightSystems/.phoenix/logs/latest/**/*.{zml,zml.zst} ~/github/FlightSystems/.starling/logs/latest/**/*.{zml,zml.zst} | sed 's|^|fs://|g' | paste -sd ',')
    echo $log_paths_joined
    set encoded_log_paths (python3 -c "import urllib.parse; import sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$log_paths_joined")
    echo "https://baraza2.platform.flyzipline.com/log_plots?id=$encoded_log_paths"
end
abbr -a ldb_url find_all_local_zipline_logs
abbr -a ldb "log_data_bridge -i '/home/ubuntu/github/FlightSystems/.starling/**/*.{zml,zst}" -i "/home/ubuntu/github/FlightSystems/.phoenix/logs/latest/**/*.{zml,zst}'"

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
abbr -a t0 task project: or estimate: or priority: list
abbr -a tb task blocked:T
abbr -a ta --set-cursor 'task add "%"'
abbr -a td task done
abbr -a tr task delete
abbr -a te task edit 
abbr -a ts --set-cursor 'task description.has:%'
abbr -a tm task modify
abbr -a teh --position anywhere "estimate:H"
abbr -a ted --position anywhere "estimate:D"
abbr -a tew --position anywhere "estimate:W"
abbr -a tem --position anywhere "estimate:M"
abbr -a tph --position anywhere "priority:H"
abbr -a tpm --position anywhere "priority:M"
abbr -a tpl --position anywhere "priority:L"
abbr -a tpn --position anywhere "project:note"
abbr -a tpi --position anywhere "project:improve"
abbr -a tpo --position anywhere "project:opensource"
abbr -a tpc --position anywhere "project:code"
abbr -a tpr --position anywhere "project:read"
abbr -a tbt --position anywhere "blocked:T"

# Git Worktree Helper
function git_worktree_add --description "Interactive Adding Git Worktree"
    set branch (git branch -r | fzf --prompt="Select Branch > " | string trim | string replace 'origin/' '')
    if test -n "$branch"
        set repo (basename (git rev-parse --show-toplevel))
        set repo_name (string replace -a '.' '-' $repo)
        set branch_name (string replace -a '/' '-' $branch)
        set folder_name "$repo_name-$branch_name"
        echo "Creating worktree for $branch in ../$folder_name"
        git worktree add "../$folder_name" "$branch"
    end
end
abbr -a gwa git_worktree_add

function git_worktree_remove --description "Interactive Removing Git Worktree"
    set worktree_out (git worktree list | fzf --prompt="Select Worktree to Remove > ")
    if test -n "$worktree_out"
        set worktree_path (echo "$worktree_out" | awk '{print $1}')
        git worktree remove "$worktree_path"
    end
end
abbr -a gwr git_worktree_remove

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

################################################################################
# Vi-Mode System Clipboard
################################################################################
function fish_user_key_bindings
    fish_vi_key_bindings
    
    # Copy to system clipboard, only works for visual mode. yy does not work.
    bind -M visual y "fish_clipboard_copy"
end

function fish_clipboard_copy --description "Copy selection to system clipboard"
    if command -v pbcopy &> /dev/null
        # macOS
        commandline -b | pbcopy
    else if command -v xclip &> /dev/null
        # Linux (Fedora, Ubuntu)
        commandline -b | xclip -selection clipboard
    else
        echo "No clipboard utility found"
    end
end

# opencode
fish_add_path ~/.opencode/bin
