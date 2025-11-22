#!/bin/bash
# Cycle through left-large, right-large, and equal-size layouts for left/right panes

CURRENT_STATE=$(tmux show-window-option -v @pane_layout_state 2>/dev/null || echo "equal")

case "$CURRENT_STATE" in
  "equal")
    # Left large
    tmux select-pane -L
    tmux resize-pane -R 30
    tmux set-window-option @pane_layout_state "left-large"
    ;;
  "left-large")
    # Right large
    tmux select-pane -L
    tmux resize-pane -L 60
    tmux set-window-option @pane_layout_state "right-large"
    ;;
  "right-large")
    # Back to equal
    tmux select-pane -L
    tmux resize-pane -R 30
    tmux set-window-option @pane_layout_state "equal"
    ;;
esac
