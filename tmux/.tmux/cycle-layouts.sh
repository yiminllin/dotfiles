#!/bin/bash
# Cycle through layouts for left/right panes

separator=$'\034'
original_pane_id=$(tmux display-message -p "#{pane_id}")

target_pane=""
target_top=""
target_left=""
while IFS="$separator" read -r pane_top pane_left pane_id board_flag; do
  [[ "$board_flag" == 1 ]] && continue

  if [[ -z "$target_pane" ]]; then
    target_pane=$pane_id
    target_top=$pane_top
    target_left=$pane_left
  elif (( pane_top > target_top || (pane_top == target_top && pane_left < target_left) )); then
    target_pane=$pane_id
    target_top=$pane_top
    target_left=$pane_left
  fi
done < <(tmux list-panes -F "#{pane_top}${separator}#{pane_left}${separator}#{pane_id}${separator}#{@opencode_agent_board}")

[[ -n "$target_pane" ]] || exit 0

window_width=$(tmux display-message -p "#{window_width}")
pane_width=$(tmux display-message -p -t "$target_pane" "#{pane_width}")

# Categorize the window width as
#     w0  w1  w2
# |   |   |   |   |
w0=$(( 3*window_width / 10 ))
w1=$(( 5*window_width / 10 ))
w2=$(( 7*window_width / 10 ))
pane_center_distance=$(( pane_width - w1 ))
pane_center_abs_distance=${pane_center_distance#-}  # Absoluate value by str manipulation

if (( pane_center_abs_distance <= 1 )); then
  tmux resize-pane -t "$target_pane" -x $w2
elif (( $pane_width <= $w1 )); then
  tmux resize-pane -t "$target_pane" -x $w1
else
  tmux resize-pane -t "$target_pane" -x $w0
fi

tmux select-pane -t "$original_pane_id"
