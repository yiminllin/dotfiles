function prdv --description "Open a GitHub PR in Diffview"
    if test (count $argv) -gt 1
        echo "usage: prdv [pr-number-or-url]" >&2
        return 2
    end

    if test (count $argv) -eq 1
        command nvim "+DiffviewPrOpen $argv[1]"
    else
        command nvim "+DiffviewPrOpen"
    end
end
