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
test (uname) = Darwin; and abbr -a cat bat; or abbr -a cat batcat 
abbr -a du dust
abbr -a top btop

# Convenience
abbr -a ... cd ../..
abbr -a .... cd ../../..
abbr -a vdesk ssh -L 8888:localhost:8888 yilin@yilin.vdesk.cloud.aurora.tech
abbr -a sb tmux_scrollback_pager

function to_devbox
    # Disable cursor_trail for remote sessions (causes visual glitches in tmux over SSH)
    if type -q kitty
        kitty @ load-config --override cursor_trail=0 2>/dev/null
    end
    
    TERM=xterm-256color command kitten ssh -L 3030:localhost:3030 -i ~/.ssh/id_ed25519_zipline ubuntu@devbox_yimin_lin.int.flyzipline.com $argv
    
    # Restore cursor_trail when SSH session ends
    if type -q kitty
        kitty @ load-config --override cursor_trail=3 2>/dev/null
    end
end
abbr -a devbox to_devbox
function to_dev_container_flight_software
    cd ~/github/FlightSystems && direnv exec . devcontainer-fs --flightsystems
end
abbr -a fs to_dev_container_flight_software 

function find_all_local_zipline_logs
    set log_paths_joined (find ~/github/FlightSystems/.phoenix/logs/latest/**/*.{zml,zml.zst} | sed 's|^|fs://|g' | paste -sd ',')
    echo $log_paths_joined
    set encoded_log_paths (python3 -c "import urllib.parse; import sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$log_paths_joined")
    echo "https://baraza2.platform.flyzipline.com/log_plots?id=$encoded_log_paths"
end
abbr -a ldb_url find_all_local_zipline_logs
abbr -a ldb "log_data_bridge -i '/home/ubuntu/github/FlightSystems/.starling/**/*.{zml,zst}" -i "/home/ubuntu/github/FlightSystems/.phoenix/logs/latest/**/*.{zml,zst}'"

# Git
abbr -a gst git status
abbr -a gd git diff
abbr -a ga git add
abbr -a gc --set-cursor 'git commit -m "%"'
abbr -a gca --set-cursor 'git commit --amend'
abbr -a gp git push
abbr -a gl git log --oneline -n 10

# Git Spice
abbr -a gsl gs log long
abbr -a gsbc --set-cursor 'gs branch create yiminlin/%'
abbr -a gsu gs up
abbr -a gsd gs down
abbr -a gsm gs trunk
abbr -a gsur gs upstack restack
abbr -a gsrc gs rebase continue 
abbr -a gsra gs rebase abort

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
abbr -a teq --position anywhere "estimate:Q"
abbr -a teh --position anywhere "estimate:H"
abbr -a ted --position anywhere "estimate:D"
abbr -a tew --position anywhere "estimate:W"
abbr -a tem --position anywhere "estimate:M"
abbr -a tpa --position anywhere "priority:A"
abbr -a tph --position anywhere "priority:H"
abbr -a tpm --position anywhere "priority:M"
abbr -a tpl --position anywhere "priority:L"
abbr -a tpn --position anywhere "project:note"
abbr -a tpi --position anywhere "project:improve"
abbr -a tpo --position anywhere "project:opensource"
abbr -a tpc --position anywhere "project:code"
abbr -a tpr --position anywhere "project:read"
abbr -a tpw --position anywhere "project:work"
abbr -a tbt --position anywhere "blocked:T"


# Note
abbr -a note --set-cursor 'echo "- %" >> ~/notes/main/quick_notes.md'

# Git Worktree Helper
function git_worktree_add --description "Interactive Adding Git Worktree"
    set location $argv[1]
    switch $location
        case "local"
            set branch (git branch --format='%(refname:short)' | fzf --prompt="Select Branch > " | string trim)
        case "remote"
            set branch (git branch -r | fzf --prompt="Select Branch > " | string trim | string replace 'origin/' '')
    end
    if test -n "$branch"
        set repo (basename (git rev-parse --show-toplevel))
        set repo_name (string replace -a '.' '-' $repo)
        set branch_name (string replace -a '/' '-' $branch)
        set folder_name "$repo_name-$branch_name"
        echo "Creating worktree for $branch in $HOME/$folder_name"
        if git worktree add "$HOME/$folder_name" "$branch"
            if test -n "$TMUX"
                ~/.tmux/tmux-sessionizer
            end
        end
    end
end

function git_worktree_remove --description "Interactive Removing Git Worktree"
    set worktree_out (git worktree list | fzf --prompt="Select Worktree to Remove > ")
    if test -n "$worktree_out"
        set worktree_path (echo "$worktree_out" | awk '{print $1}')
        git worktree remove "$worktree_path"
    end
end

function git_worktree --description "Interactive Git Worktree"
    set action $argv[1]
    switch $action
        case "add"
            git_worktree_add $argv[2]
        case "remove"
            git_worktree_remove
    end
end
abbr -a gw git_worktree
abbr -a gwal git_worktree add local
abbr -a gwar git_worktree add remote
abbr -a gwr git_worktree remove

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

# Force true color support for Node.js apps (like cursor-agent) in tmux            
set -gx FORCE_COLOR 3                                                              
# Tell apps we have a light background (fixes cursor-agent theme detection in tmux)
set -gx COLORFGBG "0;15"                                                           

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

# Cursor shape always block - For kitty cursor tail
set -g fish_cursor_insert block
set -g fish_cursor_visual block

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

# direnv hook
direnv hook fish | source
