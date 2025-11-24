#!/bin/bash
# Cycle through layouts for left/right panes

# Assume zeroth pane is the leftmost pane
tmux select-pane -t 0
window_width=$(tmux display-message -p "#{window_width}")
pane_width=$(tmux display-message -p "#{pane_width}")

# Categorize the window width as
#     w0  w1  w2
# |   |   |   |   |
w0=$(( window_width / 4 ))
w1=$(( window_width / 2 ))
w2=$(( 3 * window_width / 4 ))
pane_center_distance=$(( pane_width - w1 ))
pane_center_abs_distance=${pane_center_distance#-}  # Absoluate value by str manipulation

if (( pane_center_abs_distance <= 1 )); then
  tmux resize-pane -x $w2
elif (( $pane_width <= $w1 )); then
  tmux resize-pane -x $w1
else
  tmux resize-pane -x $w0
fi
