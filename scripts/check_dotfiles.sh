#!/usr/bin/env bash

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

failures=0

pass() { printf '[pass] %s\n' "$1"; }
skip() { printf '[skip] %s\n' "$1"; }
fail() {
  printf '[fail] %s\n' "$1" >&2
  failures=$((failures + 1))
}

run_check() {
  local label="$1"
  shift
  if "$@"; then
    pass "$label"
  else
    fail "$label"
  fi
}

check_bash_syntax() {
  local files=(install.sh install_minimal.sh scripts/*.sh tmux/.tmux/cycle-layouts.sh git/git-tree.sh tmux-powerline/.config/tmux-powerline/config.sh .githooks/pre-push)
  local file
  for file in "${files[@]}"; do
    [ -f "$file" ] || continue
    bash -n "$file" || return 1
  done
}

check_fish_syntax() {
  command -v fish >/dev/null 2>&1 || return 77
  shopt -s globstar nullglob
  local file
  for file in **/*.fish; do
    fish --no-execute "$file" || return 1
  done
}

check_json() {
  shopt -s globstar nullglob
  local file
  if command -v python3 >/dev/null 2>&1; then
    for file in **/*.json; do
      case "$file" in */node_modules/*|*/.git/*|*/.ruff_cache/*) continue ;; esac
      python3 -m json.tool "$file" >/dev/null || return 1
    done
  elif command -v jq >/dev/null 2>&1; then
    for file in **/*.json; do
      case "$file" in */node_modules/*|*/.git/*|*/.ruff_cache/*) continue ;; esac
      jq empty "$file" >/dev/null || return 1
    done
  else
    return 77
  fi
}

check_lua_parse() {
  command -v luac >/dev/null 2>&1 || return 77
  shopt -s globstar nullglob
  local file
  for file in nvim/.config/nvim/**/*.lua; do
    luac -p "$file" || return 1
  done
}

check_stylua() {
  command -v stylua >/dev/null 2>&1 || return 77
  stylua --check nvim/.config/nvim >/dev/null
}

check_stow_dry_run() {
  command -v stow >/dev/null 2>&1 || return 77
  local target
  target="$(mktemp -d)"
  stow --no --target "$target" bash bat fish flightsystems git kitty nvim opencode task tmux tmux-powerline tmuxinator visidata >/dev/null
  local status=$?
  rm -rf "$target"
  return "$status"
}

check_agent_permissions() {
  local deprecated
  deprecated="$(grep -R -n '^tools:' opencode/.config/opencode/agents 2>/dev/null || true)"
  if [ -n "$deprecated" ]; then
    printf '%s\n' "$deprecated" >&2
    return 1
  fi

  local agent
  for agent in opencode/.config/opencode/agents/*.md; do
    grep -q '^permission:' "$agent" || {
      printf 'missing permission frontmatter: %s\n' "$agent" >&2
      return 1
    }
  done

  require_agent_permission opencode/.config/opencode/agents/yolo.md bash allow || return 1
  require_agent_permission opencode/.config/opencode/agents/yolo.md edit allow || return 1
  require_agent_permission opencode/.config/opencode/agents/yolo.md task allow || return 1
  require_agent_permission opencode/.config/opencode/agents/orchestrator.md task allow || return 1
  require_agent_permission opencode/.config/opencode/agents/orchestrator.md edit deny || return 1
  require_agent_permission opencode/.config/opencode/agents/orchestrator.md bash allow || return 1
  require_agent_permission opencode/.config/opencode/agents/builder.md bash allow || return 1
  require_agent_permission opencode/.config/opencode/agents/builder.md edit allow || return 1
  require_agent_permission opencode/.config/opencode/agents/builder.md task allow || return 1
  require_agent_permission opencode/.config/opencode/agents/debugger.md bash allow || return 1
  require_agent_permission opencode/.config/opencode/agents/debugger.md edit deny || return 1
  require_agent_permission opencode/.config/opencode/agents/code-reviewer.md edit deny || return 1
  require_agent_permission opencode/.config/opencode/agents/teacher.md edit deny || return 1
  require_agent_permission opencode/.config/opencode/agents/brainstormer.md edit deny || return 1
  require_agent_permission opencode/.config/opencode/agents/dotfile-documenter.md edit allow || return 1
  require_agent_permission opencode/.config/opencode/agents/dotfile-documenter.md bash allow || return 1
  require_agent_permission opencode/.config/opencode/agents/dotfile-documenter.md task deny || return 1
}

require_agent_permission() {
  local agent="$1"
  local permission="$2"
  local action="$3"

  grep -q "^  $permission: $action$" "$agent" || {
    printf 'expected %s to contain %s: %s\n' "$agent" "$permission" "$action" >&2
    return 1
  }
}

check_agent_fixtures() {
  local fixture_dir="opencode/.config/opencode/evals"
  local fixtures=(
    permission-frontmatter.md
    permission-boundary-escalation.md
    yolo-autonomy.md
    prompt-edit-approval.md
    commit-safety.md
    dotfile-documenter-plugins.md
    insights-followup.md
  )
  local fixture
  for fixture in "${fixtures[@]}"; do
    [ -f "$fixture_dir/$fixture" ] || {
      printf 'missing fixture: %s\n' "$fixture_dir/$fixture" >&2
      return 1
    }
  done
}

check_skill_anatomy() {
  shopt -s nullglob
  local skills=(opencode/.config/opencode/skills/*/SKILL.md)
  shopt -u nullglob

  [ "${#skills[@]}" -gt 0 ] || return 77

  local failures=0
  local skill
  for skill in "${skills[@]}"; do
    skill_has_frontmatter_field "$skill" name || {
      printf 'missing or empty skill frontmatter field: %s: name\n' "$skill" >&2
      failures=$((failures + 1))
    }
    skill_has_frontmatter_field "$skill" description || {
      printf 'missing or empty skill frontmatter field: %s: description\n' "$skill" >&2
      failures=$((failures + 1))
    }
  done

  [ "$failures" -eq 0 ]
}

skill_has_frontmatter_field() {
  local file="$1"
  local field="$2"
  local line
  local in_frontmatter=0

  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$in_frontmatter" -eq 0 ]; then
      [ "$line" = '---' ] || return 1
      in_frontmatter=1
      continue
    fi

    [ "$line" = '---' ] && return 1

    [[ "$line" =~ ^[[:space:]]*${field}:[[:space:]]*[^[:space:]].* ]] && return 0
  done <"$file"

  return 1
}

check_opencode_smoke() {
  command -v opencode >/dev/null 2>&1 || return 77
  XDG_CONFIG_HOME="$REPO_ROOT/opencode/.config" opencode --pure debug config >/dev/null || return 1
  XDG_CONFIG_HOME="$REPO_ROOT/opencode/.config" opencode --pure debug agent yolo >/dev/null || return 1
  XDG_CONFIG_HOME="$REPO_ROOT/opencode/.config" opencode --pure debug agent code-reviewer >/dev/null || return 1
}

check_opencode_progress_ui() {
  command -v python3 >/dev/null 2>&1 || return 77
  python3 opencode/.config/opencode/scripts/check_progress_ui.py
}

check_opencode_helper_packets() {
  command -v python3 >/dev/null 2>&1 || return 77

  local helpers=(
    opencode/.config/opencode/scripts/opencode_worktree_cleanup_packet.py
    opencode/.config/opencode/scripts/opencode_tmux_handoff.py
    opencode/.config/opencode/scripts/opencode_runtime_packet.py
    opencode/.config/opencode/scripts/opencode_repo_packet.py
    opencode/.config/opencode/scripts/opencode_disk_pressure.py
  )

  python3 -m py_compile "${helpers[@]}" || return 1

  local helper
  for helper in "${helpers[@]}"; do
    python3 "$helper" --help >/dev/null || return 1
  done

  python3 opencode/.config/opencode/scripts/opencode_worktree_cleanup_packet.py packet --repo . --format markdown >/dev/null || return 1
  python3 opencode/.config/opencode/scripts/opencode_tmux_handoff.py packet --path /tmp --format markdown --dry-run >/dev/null || return 1
  python3 opencode/.config/opencode/scripts/opencode_tmux_handoff.py packet --path /tmp --format markdown --copy-tmux --dry-run >/dev/null || return 1
  python3 opencode/.config/opencode/scripts/opencode_runtime_packet.py packet --repo . --format markdown --dry-run >/dev/null || return 1
  python3 opencode/.config/opencode/scripts/opencode_repo_packet.py packet --repo . --format markdown --no-gh >/dev/null || return 1
  python3 opencode/.config/opencode/scripts/opencode_disk_pressure.py report --repo . --format markdown --max-depth 1 --max-entries 500 >/dev/null || return 1
  python3 opencode/.config/opencode/scripts/opencode_disk_pressure.py report --repo . --format json --max-depth 1 --max-entries 500 >/dev/null || return 1
  python3 opencode/.config/opencode/scripts/opencode_disk_pressure.py report --repo . --format markdown --max-depth 1 --max-entries 500 --print-cleanup-plan >/dev/null || return 1
}

run_optional_check() {
  local label="$1"
  shift
  "$@"
  local status=$?
  case "$status" in
    0) pass "$label" ;;
    77) skip "$label (tool unavailable)" ;;
    *) fail "$label" ;;
  esac
}

run_check "Bash syntax" check_bash_syntax
run_optional_check "Fish syntax" check_fish_syntax
run_optional_check "JSON syntax" check_json
run_optional_check "Lua parse" check_lua_parse
run_optional_check "Stylua formatting" check_stylua
run_optional_check "Stow dry-run" check_stow_dry_run
run_check "Agent permission frontmatter" check_agent_permissions
run_check "Agent regression fixtures" check_agent_fixtures
run_optional_check "Skill anatomy frontmatter" check_skill_anatomy
run_optional_check "OpenCode progress UI regression" check_opencode_progress_ui
run_optional_check "OpenCode helper packet smoke" check_opencode_helper_packets
run_optional_check "OpenCode config smoke" check_opencode_smoke

if [ "$failures" -gt 0 ]; then
  printf '\nDotfiles validation failed: %s check(s) failed.\n' "$failures" >&2
  exit 1
fi

printf '\nDotfiles validation passed.\n'
