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
      case "$file" in */node_modules/*|*/.git/*|*/.ruff_cache/*|pi/.pi/agent/auth.json|pi/.pi/agent/sessions/*) continue ;; esac
      python3 -m json.tool "$file" >/dev/null || return 1
    done
  elif command -v jq >/dev/null 2>&1; then
    for file in **/*.json; do
      case "$file" in */node_modules/*|*/.git/*|*/.ruff_cache/*|pi/.pi/agent/auth.json|pi/.pi/agent/sessions/*) continue ;; esac
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
  stow --no --target "$target" bash bat fish flightsystems git kitty nvim pi task tmux tmux-powerline tmuxinator visidata >/dev/null
  local status=$?
  rm -rf "$target"
  return "$status"
}

check_pi_install_sources() {
  grep -q '^npm install -g --ignore-scripts @earendil-works/pi-coding-agent$' install.sh || return 1
  grep -q '^npm install -g --ignore-scripts @earendil-works/pi-coding-agent >/dev/null 2>&1$' scripts/system_update.fish || return 1
  grep -q '^[[:space:]]*pi$' install.sh || return 1
}

check_pi_config() {
  command -v python3 >/dev/null 2>&1 || return 77
  python3 - <<'PY'
import json
from pathlib import Path

root = Path("pi/.pi/agent")
for name in ("settings.json", "keybindings.json"):
    value = json.loads((root / name).read_text())
    if not isinstance(value, dict):
        raise SystemExit(f"{root / name} must contain a JSON object")

append_system = root / "APPEND_SYSTEM.md"
if not append_system.is_file() or not append_system.read_text().strip():
    raise SystemExit(f"missing or empty {append_system}")
PY
}

check_pi_resources() {
  command -v python3 >/dev/null 2>&1 || return 77
  python3 - <<'PY'
import re
from pathlib import Path

agent_root = Path("pi/.pi/agent")
name_pattern = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
resource_pattern = re.compile(r"(?:\]\(|`)((?:references|scripts)/[^)`]+)")

def frontmatter(path):
    lines = path.read_text().splitlines()
    if not lines or lines[0] != "---":
        raise SystemExit(f"missing frontmatter: {path}")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise SystemExit(f"unterminated frontmatter: {path}")
    fields = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    return fields

skills = sorted((agent_root / "skills").rglob("SKILL.md"))
if not skills:
    raise SystemExit("no Pi skills discovered")

names = set()
for skill in skills:
    fields = frontmatter(skill)
    name = fields.get("name", "")
    if not name_pattern.fullmatch(name) or name != skill.parent.name:
        raise SystemExit(f"invalid skill name or directory mismatch: {skill}: {name!r}")
    if not fields.get("description"):
        raise SystemExit(f"missing skill description: {skill}")
    if name in names:
        raise SystemExit(f"duplicate skill name: {name}")
    names.add(name)
    for reference in resource_pattern.findall(skill.read_text()):
        if not (skill.parent / reference).is_file():
            raise SystemExit(f"missing skill resource: {skill.parent / reference}")

prompts = sorted((agent_root / "prompts").rglob("*.md"))
prompt_names = {prompt.stem for prompt in prompts}
if "insights" not in prompt_names:
    raise SystemExit("Pi prompt template 'insights' was not discovered")
for prompt in prompts:
    if not name_pattern.fullmatch(prompt.stem):
        raise SystemExit(f"invalid prompt template name: {prompt}")
    if not frontmatter(prompt).get("description"):
        raise SystemExit(f"missing prompt template description: {prompt}")
PY
}

check_pi_safeguards() {
  git check-ignore -q pi/.pi/agent/auth.json || return 1
  git check-ignore -q pi/.pi/agent/sessions/example.json || return 1
  ! git ls-files --error-unmatch pi/.pi/agent/auth.json >/dev/null 2>&1 || return 1
  grep -q '^\^\\\.pi/agent/auth\\\.json\$$' pi/.stow-local-ignore || return 1
  grep -q '^\^\\\.pi/agent/sessions' pi/.stow-local-ignore || return 1
}

check_pi_source_references() {
  [ -f scripts/phoenix_inspector.py ] || return 1
  grep -q '\$HOME/dotfiles/scripts/phoenix_inspector.py' pi/.pi/agent/skills/phoenix-inspector/SKILL.md || return 1
  grep -q '\$HOME/dotfiles/scripts/phoenix_inspector.py' pi/.pi/agent/skills/phoenix-workflows/SKILL.md || return 1

  local board_files=(
    tmux/.tmux/pi-agent-board
    tmux/.tmux/pi-agent-board-ensure
    tmux/.tmux/pi-agent-board-resize
    tmux/.tmux/pi-agent-board-resurrect
    tmux/.tmux/pi-agent-board-toggle
    tmux/.tmux/pi-pane-focus-main
  )
  local file
  for file in "${board_files[@]}"; do
    [ -f "$file" ] || return 1
  done
  grep -q 'pi-agent-board-ensure' tmux/.tmux.conf || return 1
  grep -q '@pi_agent_board' nvim/.config/nvim/lua/utils/pi.lua || return 1
  grep -q '@pi_agent_name' fish/.config/fish/config.fish || return 1
}

check_pi_offline() {
  command -v pi >/dev/null 2>&1 || return 77
  local output
  local status
  pi --offline --version >/dev/null || return 1
  output="$(pi --offline --list-models 2>&1)"
  status=$?
  [ "$status" -eq 0 ] || return 1
  ! grep -Eqi 'warning|error|diagnostic' <<<"$output" || return 1
  grep -Eq '^openai-codex[[:space:]]+gpt-5\.6-sol[[:space:]]' <<<"$output" || return 1
  grep -Eq '^openai-codex[[:space:]]+gpt-5\.6-luna[[:space:]]' <<<"$output" || return 1
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
run_check "Pi install and update sources" check_pi_install_sources
run_optional_check "Pi config and APPEND_SYSTEM" check_pi_config
run_optional_check "Pi skills and prompt templates" check_pi_resources
run_check "Pi auth and session safeguards" check_pi_safeguards
run_check "Pi helper and Agent Board references" check_pi_source_references
run_optional_check "Pi offline config discovery" check_pi_offline

if [ "$failures" -gt 0 ]; then
  printf '\nDotfiles validation failed: %s check(s) failed.\n' "$failures" >&2
  exit 1
fi

printf '\nDotfiles validation passed.\n'
