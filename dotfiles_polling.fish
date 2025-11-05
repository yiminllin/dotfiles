################################################################################
# Dotfiles polling
################################################################################
function dotfiles_check_update --description "Check if dotfiles has updates"
    cd ~/dotfiles
    git fetch
    set branch (git rev-parse --abbrev-ref HEAD)
    if not git diff --quiet HEAD origin/$branch
        echo "Dotfiles update available! Run `fish ~/dotfiles/dotfiles_auto_update.fish` to sync."
    end
    cd -
end

# Background polling function 
function dotfiles_auto_poll --description "Poll dotfiles repo every 30 minutes"
    echo "Poll dotfiles repo every 30 minutes"
    set lockfile /tmp/dotfiles_auto_poll.lock
    if test -e $lockfile
        echo "/tmp/dotfiles_auto_poll.lock exists!"
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

dotfiles_auto_poll
