[[ $- == *i* ]] || return

# Set -o
set -o vi 
set -o ignoreeof
set -o notify

# Keybinding and Aliases
alias ls="ls -G"
alias cp="cp -i"
alias mv="mv -i"
alias rm="rm -i"
alias ..="cd .."
alias ...="cd ../.."
alias ....="cd ../../.."
alias .....="cd ../../../.."
alias hist="history 20"
alias v='nvim'

# get current branch in git repo
function parse_git_branch() {
  BRANCH=`git branch 2> /dev/null | sed -e '/^[^*]/d' -e 's/* \(.*\)/\1/'`
  if [ ! "${BRANCH}" == "" ]
  then
    STAT=`parse_git_dirty`
    echo "[${BRANCH}${STAT}]"
  else
    echo ""
  fi
}

# get current status of git repo
function parse_git_dirty {
  status=`git status 2>&1 | tee`
  dirty=`echo -n "${status}" 2> /dev/null | grep "modified:" &> /dev/null; echo "$?"`
  untracked=`echo -n "${status}" 2> /dev/null | grep "Untracked files" &> /dev/null; echo "$?"`
  ahead=`echo -n "${status}" 2> /dev/null | grep "Your branch is ahead of" &> /dev/null; echo "$?"`
  newfile=`echo -n "${status}" 2> /dev/null | grep "new file:" &> /dev/null; echo "$?"`
  renamed=`echo -n "${status}" 2> /dev/null | grep "renamed:" &> /dev/null; echo "$?"`
  deleted=`echo -n "${status}" 2> /dev/null | grep "deleted:" &> /dev/null; echo "$?"`
  bits=''
  if [ "${renamed}" == "0" ]; then
    bits=">${bits}"
  fi
  if [ "${ahead}" == "0" ]; then
    bits="*${bits}"
  fi
  if [ "${newfile}" == "0" ]; then
    bits="+${bits}"
  fi
  if [ "${untracked}" == "0" ]; then
    bits="?${bits}"
  fi
  if [ "${deleted}" == "0" ]; then
    bits="x${bits}"
  fi
  if [ "${dirty}" == "0" ]; then
    bits="!${bits}"
  fi
  if [ ! "${bits}" == "" ]; then
    echo " ${bits}"
  else
    echo ""
  fi
}

source $HOME/.cargo/env
export PATH="$HOME/.juliaup/bin:$PATH"
export PATH="$HOME/.local/share/fnm:$PATH"
eval "$(fnm env --use-on-cd)"
export PATH="$HOME/.local/bin:$PATH"

export PS1="\[\e[30;47m\]\u\[\e[m\]\[\e[30;47m\]<\[\e[m\]\[\e[32;47m\]\w\[\e[m\]\[\e[30;47m\]>\[\e[m\]\[\e[33;47m\]\`parse_git_branch\`\[\e[m\] "
export VISUAL="nvim"
export EDITOR="nvim"
export LS_COLORS=$(vivid generate solarized-light)
export SHELL_PATH=$(which fish)
export EDITOR_PATH=$(which nvim)
export AICHAT_CONFIG_DIR="$HOME/.config/aichat"
export XDG_CONFIG_HOME="$HOME/.config"

# Execute fish shell
if [ -z "$STARTEDFISH" ];
then
    export STARTEDFISH=1;
    exec fish;
    exit;
fi
