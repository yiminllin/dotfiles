source ~/.tmux/plugins/tmux-powerline/config/defaults.sh

# Font color
export TMUX_POWERLINE_DEFAULT_FOREGROUND_COLOR="238"
export TMUX_POWERLINE_DEFAULT_BACKGROUND_COLOR="106"
export TMUX_POWERLINE_SEG_AIR_COLOR="106"

# Left right status bar
# Cannot export array in bash: define as global variables
TMUX_POWERLINE_LEFT_STATUS_SEGMENTS=("tmux_session_info 223" "vcs_branch 244 223")
TMUX_POWERLINE_RIGHT_STATUS_SEGMENTS=("pwd 223" "date_day 106" "date 106" "time 106")
