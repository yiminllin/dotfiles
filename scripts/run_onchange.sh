#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: run_onchange.sh <key> <input> [<input> ...] -- <command> [args...]

Runs the command only when the content checksum of the input files or
directories has changed. Stamps are stored in ~/.cache/dotfiles by default.
Set DOTFILES_RUN_ONCHANGE_FORCE=1 to force a run and refresh the stamp.
EOF
}

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1"
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1"
  else
    cksum "$1"
  fi
}

checksum_inputs() {
  local manifest
  manifest="$(mktemp)"

  local input file
  for input in "$@"; do
    if [ -f "$input" ]; then
      printf 'file %s\n' "$input" >>"$manifest"
      hash_file "$input" >>"$manifest"
    elif [ -d "$input" ]; then
      printf 'dir %s\n' "$input" >>"$manifest"
      while IFS= read -r file; do
        printf 'file %s\n' "$file" >>"$manifest"
        hash_file "$file" >>"$manifest"
      done < <(find "$input" -type f | LC_ALL=C sort)
    else
      printf 'run-onchange: missing input: %s\n' "$input" >&2
      rm -f "$manifest"
      return 2
    fi
  done

  local checksum
  checksum="$(hash_file "$manifest")"
  rm -f "$manifest"
  printf '%s\n' "${checksum%% *}"
}

safe_key() {
  printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'
}

if [ "$#" -lt 4 ]; then
  usage
  exit 2
fi

key="$1"
shift

inputs=()
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--" ]; then
    shift
    break
  fi
  inputs+=("$1")
  shift
done

if [ "${#inputs[@]}" -eq 0 ] || [ "$#" -eq 0 ]; then
  usage
  exit 2
fi

cache_dir="${DOTFILES_CACHE_DIR:-$HOME/.cache/dotfiles}"
stamp="$cache_dir/$(safe_key "$key").sha256"
current_checksum="$(checksum_inputs "${inputs[@]}")"

if [ "${DOTFILES_RUN_ONCHANGE_FORCE:-0}" != "1" ] && [ -f "$stamp" ] && [ "$(<"$stamp")" = "$current_checksum" ]; then
  printf '[run-onchange] %s unchanged; skipping\n' "$key"
  exit 0
fi

printf '[run-onchange] %s changed; running\n' "$key"
"$@"
mkdir -p "$cache_dir"
printf '%s\n' "$current_checksum" >"$stamp"
