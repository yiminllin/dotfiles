source ~/.tmux/plugins/tmux-powerline/config/defaults.sh

# Font color
export TMUX_POWERLINE_DEFAULT_FOREGROUND_COLOR="238"
export TMUX_POWERLINE_DEFAULT_BACKGROUND_COLOR="106"
export TMUX_POWERLINE_SEG_AIR_COLOR="106"

# Left right status bar
# Cannot export array in bash: define as global variables
TMUX_POWERLINE_LEFT_STATUS_SEGMENTS=("tmux_session_info 223")
TMUX_POWERLINE_RIGHT_STATUS_SEGMENTS=("vcs_branch 244 223" "vcs_compare 244 223" "vcs_staged 244 223" "vcs_others 244 223" "pwd 223")

export TMUX_POWERLINE_SEG_VCS_BRANCH_MAX_LEN=80
export TMUX_POWERLINE_SEG_PWD_MAX_LEN=80
export TMUX_POWERLINE_SEG_TMUX_SESSION_INFO_MAX_LEN=200
