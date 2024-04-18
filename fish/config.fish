if status is-interactive
    # Commands to run in interactive sessions can go here
end

. ~/.config/fish/themes/solarized.fish

# Abbreviations
abbr -a ls ls -G
abbr -a cp cp -ir
abbr -a mv mv -ir
abbr -a rm rm -ir
abbr -a ... cd ../..
abbr -a .... cd ../../..
abbr -a v nvim
abbr -a ninja ninja-build
abbr -a vdesk ssh -L 8888:localhost:8888 yilin@yilin.vdesk.cloud.aurora.tech

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
