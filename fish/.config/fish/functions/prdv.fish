function prdv --description "Generate an OpenCode PR guide, then open the PR in Diffview"
    set -l guide 1
    set -l selector

    for arg in $argv
        switch $arg
            case --no-guide --plain
                set guide 0
            case -h --help
                echo "usage: prdv [--no-guide|--plain] [pr-number-or-url]"
                return 0
            case '-*'
                echo "prdv: unknown option: $arg" >&2
                echo "usage: prdv [--no-guide|--plain] [pr-number-or-url]" >&2
                return 2
            case '*'
                if set -q selector[1]
                    echo "prdv: expected at most one PR number or URL" >&2
                    echo "usage: prdv [--no-guide|--plain] [pr-number-or-url]" >&2
                    return 2
                end
                set selector $arg
        end
    end

    if test $guide -eq 1
        if not command -q git
            echo "prdv: git is required" >&2
            return 127
        end
        if not command -q gh
            echo "prdv: gh is required for guide generation; use --no-guide to open Diffview directly" >&2
            return 127
        end
        if not command -q opencode
            echo "prdv: opencode is required for guide generation; use --no-guide to open Diffview directly" >&2
            return 127
        end

        set -l repo_root (command git rev-parse --show-toplevel 2>/dev/null)
        if test $status -ne 0 -o -z "$repo_root"
            echo "prdv: not inside a git repository" >&2
            return 1
        end

        set -l pr_json
        if set -q selector[1]
            set pr_json (command gh pr view $selector --json number,title,url,baseRefName,headRefName 2>&1)
        else
            set pr_json (command gh pr view --json number,title,url,baseRefName,headRefName 2>&1)
        end
        if test $status -ne 0
            echo "prdv: gh PR lookup failed:" >&2
            printf '%s\n' $pr_json >&2
            return 1
        end

        set -l pr_fields (printf '%s' "$pr_json" | command python3 -c 'import json, sys
pr = json.load(sys.stdin)
for key in ("number", "title", "url", "baseRefName", "headRefName"):
    print(pr.get(key) or "")')
        if test $status -ne 0 -o (count $pr_fields) -lt 5
            echo "prdv: could not parse gh PR metadata" >&2
            return 1
        end

        set -l pr_number $pr_fields[1]
        set -l pr_title $pr_fields[2]
        set -l pr_url $pr_fields[3]
        set -l pr_base $pr_fields[4]
        set -l pr_head $pr_fields[5]
        set -l remote (command git -C "$repo_root" remote get-url origin 2>/dev/null)
        set -l repo_key (string replace -r '\.git/?$' '' -- "$remote")
        set repo_key (string replace -r '/+$' '' -- "$repo_key")
        set repo_key (string replace -r '^.*[:/]' '' -- "$repo_key")
        if test -z "$repo_key"
            set repo_key (basename "$repo_root")
        end
        if test -z "$repo_key"
            echo "prdv: could not determine repo key for guide path" >&2
            return 1
        end
        set -l guide_dir "$HOME/notes/projects/$repo_key/pr-reviews/$pr_number"
        set -l guide_path "$guide_dir/guide.md"
        set -l guide_tmp "$guide_dir/guide.md.tmp"

        command mkdir -p "$guide_dir"

        set -l prompt "Prepare a concise local Diffview review guide for GitHub PR #$pr_number.

PR metadata:
- Title: $pr_title
- URL: $pr_url
- Base branch: $pr_base
- Head branch: $pr_head
- Repository root: $repo_root
- Guide artifact path: $guide_path

Instructions:
- Do read-only review/context gathering only.
- Do not edit files.
- Do not post comments, approve, request changes, resolve threads, or mutate GitHub state.
- If the guide artifact already exists, read it first and refresh it against the current PR state. Preserve still-relevant observations, remove stale ones, and add new findings.
- Produce Markdown for a human doing local review in Diffview.
- Include: one-paragraph summary, recommended file review order, high-risk areas, concrete questions/comments to consider, and validation focus.
- Keep the output concise and actionable."

        echo "prdv: generating OpenCode PR guide..."
        echo "prdv: guide target: $guide_path"
        if not command env -u FORCE_COLOR NO_COLOR=1 opencode run --agent orchestrator --title "PR #$pr_number Diffview review guide" --dir "$repo_root" "$prompt" > "$guide_tmp"
            set -l opencode_status $status
            echo "prdv: OpenCode guide generation failed with status $opencode_status" >&2
            read -l -P "Open plain Diffview anyway? [y/N] " answer
            if not string match -qr '^[Yy]' -- $answer
                return $opencode_status
            end
        else
            command mv "$guide_tmp" "$guide_path"
            echo "prdv: guide saved: $guide_path"
        end
    end

    if set -q selector[1]
        command nvim "+DiffviewPrOpen $selector"
    else
        command nvim "+DiffviewPrOpen"
    end
end
