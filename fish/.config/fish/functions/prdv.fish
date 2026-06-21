function prdv --description "Open a PR in Diffview with a reusable OpenCode guide"
    set -l refresh_guide 0
    set -l selector

    for arg in $argv
        switch $arg
            case --refresh-guide
                set refresh_guide 1
            case -h --help
                echo "usage: prdv [--refresh-guide] [pr-number-or-url]"
                return 0
            case '-*'
                echo "prdv: unknown option: $arg" >&2
                echo "usage: prdv [--refresh-guide] [pr-number-or-url]" >&2
                return 2
            case '*'
                if set -q selector[1]
                    echo "prdv: expected at most one PR number or URL" >&2
                    echo "usage: prdv [--refresh-guide] [pr-number-or-url]" >&2
                    return 2
                end
                set selector $arg
        end
    end

    if not command -q git
        echo "prdv: git is required" >&2
        return 127
    end
    if not command -q gh
        echo "prdv: gh is required for PR metadata lookup" >&2
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
    set -l guide_path "$guide_dir/guide.json"
    set -l guide_tmp "$guide_dir/guide.json.tmp"

    set -l guide_status missing
    if test -f "$guide_path"
        if command python3 -m json.tool "$guide_path" >/dev/null 2>/dev/null
            set guide_status valid
        else
            set guide_status invalid
        end
    end

    if test $refresh_guide -eq 0 -a "$guide_status" = valid
        echo "prdv: reusing existing valid guide: $guide_path"
    else
        if not command -q opencode
            echo "prdv: opencode is required to generate or refresh the guide" >&2
            return 127
        end

        command mkdir -p "$guide_dir"

        set -l prompt "Prepare a concise local Diffview review guide for GitHub PR #$pr_number.

PR metadata:
- Title: $pr_title
- URL: $pr_url
- Base branch: $pr_base
- Head branch: $pr_head
- Repository root: $repo_root
- Guide artifact path: $guide_path
- Existing guide status: $guide_status

Instructions:
- Do read-only review/context gathering only.
- Do not edit files.
- Do not post comments, approve, request changes, resolve threads, or mutate GitHub state.
- Stay within the repository root above for local file discovery.
- Do not broad-search `/`, `/home`, `/home/vscode`, or sibling worktrees unless explicitly asked.
- Use bounded read-only inspection. When a review subagent needs PR context, prefer authenticated read-only `gh pr view`, `gh pr diff`, `gh pr checks`, or local git diff/status/log context over webfetch or broad filesystem discovery.
- If blocked by missing permissions, missing PR context, or incomplete local refs, return valid raw JSON with the blocker captured in the summary or high-risk fields instead of continuing broad discovery.
- If the existing guide status is valid, read it first and refresh it against the current PR state. Preserve still-relevant observations, remove stale ones, and add new findings.
- If the existing guide status is missing or invalid, generate a fresh guide from the current PR state.
- Produce a structured JSON guide for a human doing local review in Diffview.
- Return raw JSON only: no preface, no save-status/meta prose, no Markdown, and no wrapping fenced code block.
- Use this schema exactly: {\"schema_version\":1,\"pr\":{\"number\":123,\"title\":\"...\",\"url\":\"...\",\"base\":\"...\",\"head\":\"...\"},\"summary\":\"...\",\"change_map\":[\"optional concise ASCII/plain-text relationship map line\"],\"high_risk\":[\"...\"],\"validation_focus\":[\"...\"],\"review_strategy\":[\"optional review step\"],\"files\":[{\"path\":\"path/from/diff\",\"depth\":\"read carefully\",\"notes\":[\"file-level guide note\"],\"suggestions\":[{\"severity\":\"Medium\",\"line\":10,\"end_line\":12,\"body\":\"suggested local comment/question\",\"why\":\"why it matters\"}]}]}.
- Fill `pr` from the PR metadata above. `change_map` is optional; include it only when a concise relationship figure, dataflow, or ownership map helps orient the reviewer. Use short ASCII/plain-text strings only, with no Mermaid/images, ideally no more than 8-12 lines. `review_strategy` is optional and may be a string or array; `depth`, `end_line`, and `why` are optional.
- Order `files` as the recommended human/Diffview review order. Future Diffview <Tab>/<S-Tab> navigation may use this order, so do not sort alphabetically unless that is the recommended review order.
- Use exact Diffview file paths from the PR diff. Keep notes and suggestions concise and high-signal.
- For approximate anchors, set `line` and `end_line` to null rather than inventing exact line numbers.
- Use [] for empty arrays and omit optional suggestion fields only when they are not known.
- Keep the output concise and actionable."

        switch $guide_status
            case valid
                echo "prdv: refreshing OpenCode PR guide..."
            case invalid
                echo "prdv: existing guide is invalid; regenerating: $guide_path"
            case '*'
                echo "prdv: generating OpenCode PR guide..."
        end
        echo "prdv: guide target: $guide_path"
        if not command env -u FORCE_COLOR NO_COLOR=1 opencode run --agent orchestrator --title "PR #$pr_number Diffview review guide" --dir "$repo_root" "$prompt" > "$guide_tmp"
            set -l opencode_status $status
            echo "prdv: OpenCode guide generation failed with status $opencode_status" >&2
            return $opencode_status
        else if not command python3 -m json.tool "$guide_tmp" >/dev/null
            set -l json_status $status
            echo "prdv: OpenCode guide output was not valid JSON" >&2
            return $json_status
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
