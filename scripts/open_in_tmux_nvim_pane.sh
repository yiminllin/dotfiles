#!/usr/bin/env bash

set -euo pipefail

PANE_OPTION='@kitty_hint_nvim_pane'
PANE_TITLE='kitty-hint-nvim'

main() {
  local selected target line col tmux_window base_cwd file pane

  selected="$*"
  [ -n "$selected" ] || exit 0

  if ! command -v tmux >/dev/null 2>&1; then
    printf 'open_in_tmux_nvim_pane: tmux is required\n' >&2
    exit 1
  fi

  if ! IFS=$'\t' read -r tmux_window base_cwd < <(tmux_context); then
    printf 'open_in_tmux_nvim_pane: no unique active tmux pane found\n' >&2
    exit 1
  fi

  IFS=$'\t' read -r target line col < <(parse_selection "$selected")
  file="$(resolve_path "$target" "$base_cwd")"

  pane="$(find_nvim_pane "$tmux_window" || true)"
  if [ -z "$pane" ]; then
    pane="$(create_nvim_pane "$tmux_window" "$file" "$line" "$col" "$base_cwd")"
  else
    open_in_existing_pane "$pane" "$file" "$line" "$col"
  fi

  set_nvim_pane_option "$tmux_window" "$pane"
  tmux select-pane -t "$pane" -T "$PANE_TITLE"
}

parse_selection() {
  local raw="$1"
  local target line='' col=''

  if [[ "$raw" == file://* ]]; then
    raw="${raw#file://}"
    raw="${raw#localhost}"
  fi
  raw="${raw//%20/ }"
  raw="${raw//%3A/:}"
  raw="${raw//%3a/:}"
  raw="${raw//%2F//}"
  raw="${raw//%2f//}"
  raw="${raw//%7E/~}"
  raw="${raw//%7e/~}"
  raw="${raw//%25/%}"

  if [[ "$raw" =~ ^(.+):([0-9]+):([0-9]+)$ ]]; then
    target="${BASH_REMATCH[1]}"
    line="${BASH_REMATCH[2]}"
    col="${BASH_REMATCH[3]}"
  elif [[ "$raw" =~ ^(.+):([0-9]+)$ ]]; then
    target="${BASH_REMATCH[1]}"
    line="${BASH_REMATCH[2]}"
  else
    target="$raw"
  fi

  printf '%s\t%s\t%s\n' "$target" "$line" "$col"
}

tmux_context() {
  local context

  if [ -n "${TMUX_PANE:-}" ] && context="$(tmux display-message -p -t "$TMUX_PANE" -F $'#{window_id}\t#{pane_current_path}' 2>/dev/null)"; then
    printf '%s\n' "$context"
    return 0
  fi

  if [ -n "${TMUX:-}" ] && context="$(tmux display-message -p -F $'#{window_id}\t#{pane_current_path}' 2>/dev/null)"; then
    printf '%s\n' "$context"
    return 0
  fi

  active_attached_tmux_context
}

active_attached_tmux_context() {
  local attached window_active pane_active window_id pane_cwd context=''
  local count=0

  while IFS=$'\t' read -r attached window_active pane_active window_id pane_cwd; do
    [ "${attached:-0}" -gt 0 ] 2>/dev/null || continue
    [ "$window_active" = '1' ] || continue
    [ "$pane_active" = '1' ] || continue

    context="${window_id}"$'\t'"${pane_cwd}"
    count=$((count + 1))
  done < <(tmux list-panes -a -F $'#{session_attached}\t#{window_active}\t#{pane_active}\t#{window_id}\t#{pane_current_path}' 2>/dev/null)

  [ "$count" -eq 1 ] || return 1
  printf '%s\n' "$context"
}

resolve_path() {
  local path="$1"
  local base_cwd="$2"

  case "$path" in
    '~') printf '%s\n' "$HOME" ;;
    '~/'*) printf '%s/%s\n' "$HOME" "${path#~/}" ;;
    /*) printf '%s\n' "$path" ;;
    *) printf '%s/%s\n' "$base_cwd" "$path" ;;
  esac
}

find_nvim_pane() {
  local tmux_window="$1"
  local pane command

  pane="$(show_nvim_pane_option "$tmux_window" || true)"
  [ -n "$pane" ] || return 1

  command="$(tmux display-message -p -t "$pane" -F '#{pane_current_command}' 2>/dev/null || true)"
  [ "$command" = 'nvim' ] || return 1

  printf '%s\n' "$pane"
}

show_nvim_pane_option() {
  local tmux_window="$1"

  tmux show-option -wqv -t "$tmux_window" "$PANE_OPTION" 2>/dev/null
}

set_nvim_pane_option() {
  local tmux_window="$1"
  local pane="$2"

  tmux set-option -wq -t "$tmux_window" "$PANE_OPTION" "$pane"
}

create_nvim_pane() {
  local tmux_window="$1"
  local file="$2"
  local line="$3"
  local col="$4"
  local start_dir="$5"
  local command pane
  local nvim_args=(nvim)

  if [ -n "$line" ]; then
    if [ -n "$col" ]; then
      nvim_args+=("+call cursor($line, $col)")
    else
      nvim_args+=("+$line")
    fi
  fi
  nvim_args+=("$file")
  command="$(shell_command "${nvim_args[@]}")"

  pane="$(tmux split-window -t "$tmux_window" -h -d -c "$start_dir" -P -F '#{pane_id}' "$command")"
  printf '%s\n' "$pane"
}

open_in_existing_pane() {
  local pane="$1"
  local file="$2"
  local line="$3"
  local col="$4"
  local command path_literal

  path_literal="$(vim_single_quote "$file")"
  command=":execute 'edit ' . fnameescape($path_literal)"
  if [ -n "$line" ]; then
    command+=" | call cursor($line, ${col:-1}) | normal! zv"
  fi

  tmux send-keys -t "$pane" Escape
  tmux send-keys -t "$pane" -l "$command"
  tmux send-keys -t "$pane" Enter
}

shell_command() {
  printf '%q ' "$@"
}

vim_single_quote() {
  local value="$1"
  printf "'%s'\n" "${value//\'/\'\'}"
}

main "$@"
