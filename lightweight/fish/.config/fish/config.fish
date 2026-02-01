if status is-interactive
    # Lightweight fish: minimal abbrs, no tmux/task/aichat/opencode
end

# So fzf and (on Debian) tarball nvim are in PATH after minimal install
fish_add_path $HOME/.fzf/bin $HOME/.local/bin

################################################################################
# Theme (optional: comment out if you prefer default)
################################################################################
if test -f ~/.config/fish/themes/solarized.fish
    . ~/.config/fish/themes/solarized.fish
end

################################################################################
# Abbreviations
################################################################################
abbr -a v nvim
abbr -a ... cd ../..
abbr -a .... cd ../../..

# Basic git
abbr -a gst git status
abbr -a gd git diff
abbr -a ga git add
abbr -a gc "git commit -m"
abbr -a gp git push
abbr -a gl "git log --oneline -n 10"

# Safer defaults (optional)
abbr -a cp cp -i
abbr -a mv mv -i
abbr -a rm rm -i

# Better CLI tools (if installed)
type -q eza && abbr -a ls eza -lah --git
type -q bat && abbr -a cat bat

################################################################################
# FZF: one binding source (fzf.fish from fisher, or stock fzf --fish)
################################################################################
if functions -q fzf_configure_bindings
    fzf_configure_bindings
else if type -q fzf
    fzf --fish | source
end

################################################################################
# Completion
################################################################################
if not set -q fish_complete_hidden
    set -U fish_complete_hidden 1
end
