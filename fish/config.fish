if status is-interactive
    # Commands to run in interactive sessions can go here
end

. ~/.config/fish/themes/solarized.fish

function tmux_scrollback_pager
    tmux capture-pane -S - -p > /tmp/tmux_full_scrollback.txt && /home/yiminlin/.local/share/bob/nvim-bin/nvim -c "normal G" /tmp/tmux_full_scrollback.txt
end

# Abbreviations
abbr -a cp cp -ir
abbr -a mv mv -i
abbr -a rm rm -ir
abbr -a ... cd ../..
abbr -a .... cd ../../..
abbr -a v nvim
abbr -a ninja ninja-build
abbr -a ls lsd -lah
abbr -a cat batcat
abbr -a du ncdu
abbr -a top btop
abbr -a vdesk ssh -L 8888:localhost:8888 yilin@yilin.vdesk.cloud.aurora.tech
abbr -a sb tmux_scrollback_pager

# # >>> juliaup initialize >>>
#
# # !! Contents within this block are managed by juliaup !!
#
# case ":$PATH:" in
#     *:/home/yiminlin/.juliaup/bin:*)
#         ;;
#
#     *)
#         export PATH=/home/yiminlin/.juliaup/bin${PATH:+:${PATH}}
#         ;;
# esac
#
# # <<< juliaup initialize <<<

fzf --fish | source
