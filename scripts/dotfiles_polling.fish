#!/usr/bin/env fish

function dotfiles_check_update --description "Check if dotfiles has updates"
    cd ~/dotfiles
    git fetch >/dev/null 2>&1
    set branch (git rev-parse --abbrev-ref HEAD)
    if not git diff --quiet HEAD origin/$branch
        fish ~/dotfiles/scripts/dotfiles_auto_update.fish
    end
    cd -
end

function dotfiles_auto_poll --description "Poll dotfiles repo every 30 minutes"
    set lockfile /tmp/dotfiles_auto_poll.lock
    if test -e $lockfile
        return
    end
    touch $lockfile
    trap "rm -f $lockfile" EXIT INT TERM
    while true
        dotfiles_check_update
        sleep 1800
    end
    rm -f $lockfile
end
