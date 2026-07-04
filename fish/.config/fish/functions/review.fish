function __review_vim_arg --argument-names value
    set value (string replace -a '\\' '\\\\' -- "$value")
    set value (string replace -a ' ' '\ ' -- "$value")
    set value (string replace -a '|' '\|' -- "$value")
    set value (string replace -a '"' '\"' -- "$value")
    printf '%s\n' "$value"
end

function __review_lua_single_quoted_string --argument-names value
    set value (string replace -a '\\' '\\\\' -- "$value")
    set value (string replace -a "'" "\\'" -- "$value")
    printf "'%s'\n" "$value"
end

function __review_shell_single_quoted_string --argument-names value
    set value (string replace -a "'" "'\\''" -- "$value")
    printf "'%s'\n" "$value"
end

function __review_open_opencode_pane --argument-names repo_root title bootstrap_path
    if not set -q TMUX; or test -z "$TMUX"
        echo "review: not inside tmux; skipping interactive OpenCode pane" >&2
        return 1
    end
    if not command -q tmux
        echo "review: tmux not found; skipping interactive OpenCode pane" >&2
        return 1
    end
    if not command -q opencode
        echo "review: opencode not found; skipping interactive OpenCode pane" >&2
        return 1
    end

    set -l prompt "Please read and execute this review bootstrap, then stay in review assistant mode: $bootstrap_path"
    set -l repo_root_arg (__review_shell_single_quoted_string "$repo_root")
    set -l prompt_arg (__review_shell_single_quoted_string "$prompt")
    set -l title_arg (__review_shell_single_quoted_string "$title")
    set -l fish_command (__review_shell_single_quoted_string "exec opencode $repo_root_arg --agent orchestrator --prompt $prompt_arg")
    set -l launch_command "tmux set-option -pt \"\$TMUX_PANE\" allow-passthrough off; tmux set-option -pt \"\$TMUX_PANE\" @opencode_agent_name $title_arg; tmux select-pane -t \"\$TMUX_PANE\" -T $title_arg; exec fish -l -c $fish_command"
    set -l pane_id (command tmux split-window -h -p 33 -d -P -F '#{pane_id}' -c "$repo_root" "$launch_command" 2>&1)
    if test $status -ne 0
        echo "review: could not open interactive OpenCode pane: $pane_id" >&2
        return 1
    end

    command tmux set-option -pt "$pane_id" @opencode_agent_name "$title" >/dev/null 2>/dev/null
    command tmux select-pane -t "$pane_id" -T "$title" >/dev/null 2>/dev/null
    echo "review: opened interactive OpenCode pane: $title" >&2
    printf '%s\n' "$pane_id"
end

function __review_guides_are_valid --argument-names guide_md_path guide_json_path min_mtime
    test -s "$guide_md_path"; and test -f "$guide_json_path"; and command python3 -m json.tool "$guide_json_path" >/dev/null 2>/dev/null
    or return 1

    if test -z "$min_mtime"
        return 0
    end

    command python3 -c 'import os, sys
min_mtime = float(sys.argv[1])
paths = sys.argv[2:]
sys.exit(0 if all(os.path.getmtime(path) >= min_mtime for path in paths) else 1)' "$min_mtime" "$guide_md_path" "$guide_json_path" >/dev/null 2>/dev/null
end

function __review_guide_status_line --argument-names guide_md_path guide_json_path min_mtime
    set -l markdown_status missing
    if test -s "$guide_md_path"
        set markdown_status non-empty
    else if test -f "$guide_md_path"
        set markdown_status empty
    end

    set -l json_status missing
    if test -f "$guide_json_path"
        if command python3 -m json.tool "$guide_json_path" >/dev/null 2>/dev/null
            set json_status valid
        else
            set json_status invalid
        end
    end

    set -l freshness_status
    if test -n "$min_mtime"
        if __review_guides_are_valid "$guide_md_path" "$guide_json_path" "$min_mtime"
            set freshness_status '; freshness: current'
        else
            set freshness_status '; freshness: stale'
        end
    end

    printf 'Markdown: %s; JSON: %s%s' "$markdown_status" "$json_status" "$freshness_status"
end

function __review_guide_status --argument-names guide_md_path guide_json_path refresh_guide
    set -l guide_json_status missing
    if test -f "$guide_json_path"
        if command python3 -m json.tool "$guide_json_path" >/dev/null 2>/dev/null
            set guide_json_status valid
        else
            set guide_json_status invalid
        end
    end

    set -l guide_md_status missing
    if test -s "$guide_md_path"
        set guide_md_status valid
    else if test -f "$guide_md_path"
        set guide_md_status empty
    end

    set -l guides_need_generation 1
    if test $refresh_guide -eq 0 -a "$guide_json_status" = valid -a "$guide_md_status" = valid
        set guides_need_generation 0
    end

    printf '%s\n%s\n%s\n' "$guide_md_status" "$guide_json_status" "$guides_need_generation"
end

function __review_run_interactive_guide_flow --argument-names repo_root opencode_title assistant_bootstrap_path guide_dir guide_md_path guide_json_path guides_need_generation assistant_bootstrap
    set -g __review_interactive_pane_id

    if set -q TMUX; and test -n "$TMUX"; and command -q tmux; and command -q opencode
        command mkdir -p "$guide_dir"
        printf '%s\n' "$assistant_bootstrap" > "$assistant_bootstrap_path"

        set -l guide_generation_started_at
        if test $guides_need_generation -eq 1
            set guide_generation_started_at (command python3 -c 'import time; print(time.time())')
        end

        set -l pane_id (__review_open_opencode_pane "$repo_root" "$opencode_title" "$assistant_bootstrap_path")
        if test $status -eq 0 -a -n "$pane_id"
            set -g __review_interactive_pane_id "$pane_id"
            echo "review: passed OpenCode startup prompt: $assistant_bootstrap_path"
            if test $guides_need_generation -eq 1
                echo "review: waiting for interactive OpenCode guide generation..."
                if not __review_wait_for_guides "$guide_md_path" "$guide_json_path" "$guide_generation_started_at"
                    return 1
                end
                echo "review: guides are ready: $guide_md_path and $guide_json_path"
            else
                echo "review: reusing existing guides: $guide_md_path and $guide_json_path"
            end
        end
    else if test $guides_need_generation -eq 0
        echo "review: reusing existing guides: $guide_md_path and $guide_json_path"
    end

    return 0
end

function __review_generate_guides_noninteractive --argument-names repo_root refresh_guide mode_label guide_md_status guide_json_status guide_md_path guide_json_path guide_md_tmp guide_json_tmp markdown_title json_title markdown_prompt json_prompt
    if not command -q opencode
        echo "review: opencode is required to generate or refresh the guide" >&2
        return 127
    end

    command mkdir -p (dirname "$guide_md_path")

    if test $refresh_guide -eq 1
        echo "review: refreshing OpenCode $mode_label guides..."
    else
        echo "review: regenerating OpenCode $mode_label guides (Markdown: $guide_md_status, JSON: $guide_json_status)..."
    end
    echo "review: Markdown guide target: $guide_md_path"
    echo "review: JSON guide target: $guide_json_path"

    if not command env -u FORCE_COLOR NO_COLOR=1 opencode run --agent orchestrator --title "$markdown_title" --dir "$repo_root" "$markdown_prompt" > "$guide_md_tmp"
        set -l opencode_status $status
        echo "review: OpenCode Markdown guide generation failed with status $opencode_status" >&2
        return $opencode_status
    else if not test -s "$guide_md_tmp"
        echo "review: OpenCode Markdown guide output was empty" >&2
        return 1
    else if not command env -u FORCE_COLOR NO_COLOR=1 opencode run --agent orchestrator --title "$json_title" --dir "$repo_root" "$json_prompt" > "$guide_json_tmp"
        set -l opencode_status $status
        echo "review: OpenCode JSON guide generation failed with status $opencode_status" >&2
        return $opencode_status
    else if not command python3 -m json.tool "$guide_json_tmp" >/dev/null
        set -l json_status $status
        echo "review: OpenCode JSON guide output was not valid JSON" >&2
        return $json_status
    else
        command mv "$guide_md_tmp" "$guide_md_path"
        command mv "$guide_json_tmp" "$guide_json_path"
        echo "review: Markdown guide saved: $guide_md_path"
        echo "review: JSON guide saved: $guide_json_path"
    end
end

function __review_wait_for_guides --argument-names guide_md_path guide_json_path min_mtime
    set -l timeout_seconds 900
    set -l progress_seconds 5
    set -l stable_seconds 1
    set -l start_time (command date +%s)
    set -l next_progress $start_time

    while true
        set -l now (command date +%s)
        if test $now -ge $next_progress
            echo "review: waiting for interactive assistant guides... "(__review_guide_status_line "$guide_md_path" "$guide_json_path" "$min_mtime") >&2
            set next_progress (math $now + $progress_seconds)
        end

        if __review_guides_are_valid "$guide_md_path" "$guide_json_path" "$min_mtime"
            command sleep $stable_seconds
            if __review_guides_are_valid "$guide_md_path" "$guide_json_path" "$min_mtime"
                return 0
            end
        end

        if test (math $now - $start_time) -ge $timeout_seconds
            echo "review: timed out waiting for interactive assistant guide generation" >&2
            echo "review: Markdown guide: $guide_md_path" >&2
            echo "review: JSON guide: $guide_json_path" >&2
            echo "review: last status: "(__review_guide_status_line "$guide_md_path" "$guide_json_path" "$min_mtime") >&2
            echo "review: the OpenCode pane may still be writing; fix/regenerate there, then rerun review --refresh-guide if needed" >&2
            return 1
        end

        command sleep 1
    end
end

function review --description "Open a PR or local branch in Diffview with a reusable OpenCode guide"
    set -l refresh_guide 0
    set -l selector

    for arg in $argv
        switch $arg
            case --refresh-guide
                set refresh_guide 1
            case -h --help
                echo "usage: review [--refresh-guide] [pr-number-or-url]"
                return 0
            case '-*'
                echo "review: unknown option: $arg" >&2
                echo "usage: review [--refresh-guide] [pr-number-or-url]" >&2
                return 2
            case '*'
                if set -q selector[1]
                    echo "review: expected at most one PR number or URL" >&2
                    echo "usage: review [--refresh-guide] [pr-number-or-url]" >&2
                    return 2
                end
                set selector $arg
        end
    end

    if not command -q git
        echo "review: git is required" >&2
        return 127
    end

    set -l repo_root (command git rev-parse --show-toplevel 2>/dev/null)
    if test $status -ne 0 -o -z "$repo_root"
        echo "review: not inside a git repository" >&2
        return 1
    end

    set -l remote (command git -C "$repo_root" remote get-url origin 2>/dev/null)
    set -l repo_key (string replace -r '\.git/?$' '' -- "$remote")
    set repo_key (string replace -r '/+$' '' -- "$repo_key")
    set repo_key (string replace -r '^.*[:/]' '' -- "$repo_key")
    if test -z "$repo_key"
        set repo_key (basename "$repo_root")
    end
    if test -z "$repo_key"
        echo "review: could not determine repo key for guide path" >&2
        return 1
    end

    set -l mode branch
    set -l pr_json
    if set -q selector[1]
        if not command -q gh
            echo "review: gh is required for explicit PR metadata lookup" >&2
            return 127
        end
        set pr_json (command gh pr view $selector --json number,title,url,baseRefName,headRefName 2>&1)
        if test $status -ne 0
            echo "review: gh PR lookup failed:" >&2
            printf '%s\n' $pr_json >&2
            return 1
        end
        set mode pr
    end

    if test "$mode" = pr
        set -l pr_fields (printf '%s' "$pr_json" | command python3 -c 'import json, sys
pr = json.load(sys.stdin)
for key in ("number", "title", "url", "baseRefName", "headRefName"):
    print(pr.get(key) or "")')
        if test $status -ne 0 -o (count $pr_fields) -lt 5
            echo "review: could not parse gh PR metadata" >&2
            return 1
        end

        set -l pr_number $pr_fields[1]
        set -l pr_title $pr_fields[2]
        set -l pr_url $pr_fields[3]
        set -l pr_base $pr_fields[4]
        set -l pr_head $pr_fields[5]
        set -l guide_dir "$HOME/notes/projects/$repo_key/pr-reviews/$pr_number"
        set -l guide_md_path "$guide_dir/guide.md"
        set -l guide_json_path "$guide_dir/guide.json"
        set -l guide_md_tmp "$guide_dir/guide.md.tmp"
        set -l guide_json_tmp "$guide_dir/guide.json.tmp"

        set -l guide_status (__review_guide_status "$guide_md_path" "$guide_json_path" $refresh_guide)
        set -l guide_md_status $guide_status[1]
        set -l guide_json_status $guide_status[2]
        set -l guides_need_generation $guide_status[3]

        set -l opencode_title "review-$pr_number"
        set -l assistant_bootstrap_path "$guide_dir/assistant-bootstrap.md"
        set -l diffview_state_path "$guide_dir/diffview-review.json"

        set -l generation_instruction "Existing guides are valid and --refresh-guide was not passed. Do not regenerate guide.md or guide.json. Read the paths and context below, then remain in review assistant mode."
        if test $guides_need_generation -eq 1
            set generation_instruction "Generate or refresh both artifacts now. Write raw Markdown to the exact guide.md path and valid raw JSON to the exact guide.json path. Report READY when both artifacts are written and valid."
        end

        set -l assistant_bootstrap "# Review assistant bootstrap for PR #$pr_number

You are the persistent local review assistant for this Diffview session. Use the pr-human-review-guide skill and contract.

PR metadata:
- Number: $pr_number
- Title: $pr_title
- URL: $pr_url
- Base branch: $pr_base
- Head branch: $pr_head
- Repository root: $repo_root

Artifact paths:
- Markdown guide.md: $guide_md_path
- Structured guide.json: $guide_json_path
- Diffview local state: $diffview_state_path
- Bootstrap file: $assistant_bootstrap_path

Existing artifact status:
- Markdown guide status: $guide_md_status
- JSON guide status: $guide_json_status
- Refresh requested: $refresh_guide

Initial task:
- $generation_instruction
- Do read-only context gathering only.
- Do not post comments, approve, request changes, resolve threads, edit PR bodies, or otherwise mutate GitHub state.
- Stay within the repository root above for local file discovery; do not broad-search /, /home, /home/vscode, or sibling worktrees unless explicitly asked.
- Prefer bounded read-only PR context from existing local git state and authenticated read-only gh commands such as gh pr view, gh pr diff, and gh pr checks when needed.
- If blocked by missing permissions, auth, PR context, or incomplete local refs, capture the blocker in the artifacts instead of mutating external state.

Artifact contract when generation or refresh is needed:
- guide.md must be raw Markdown only: no preface, no save-status/meta prose, and no wrapping fenced code block.
- guide.json must be raw valid JSON only: no preface, no Markdown, no save-status prose, and no wrapping fenced code block.
- Read pr-human-review-guide references/output-templates.md if you need the exact schema or examples.
- Use this JSON shape: {\"schema_version\":1,\"pr\":{\"number\":$pr_number,\"title\":\"...\",\"url\":\"...\",\"base\":\"...\",\"head\":\"...\"},\"summary\":\"...\",\"change_map\":[\"optional concise ASCII/plain-text relationship map line\"],\"high_risk\":[\"...\"],\"validation_focus\":[\"...\"],\"review_strategy\":[\"optional review step\"],\"files\":[{\"path\":\"path/from/diff\",\"depth\":\"read carefully\",\"notes\":[\"file-level guide note\"],\"suggestions\":[{\"severity\":\"Medium\",\"line\":10,\"end_line\":12,\"body\":\"suggested local comment/question\",\"why\":\"why it matters\"}]}]}.
- Include one files entry for every changed Diffview file so <leader>gdg can navigate the full changed-file set.
- Order files as the recommended human/Diffview review order, not alphabetically unless that is genuinely best.
- Use exact Diffview file paths from the PR diff. Use null for approximate line anchors rather than inventing exact line numbers.

Completion and follow-up mode:
- When generation or refresh is needed, report READY after guide.md is non-empty and guide.json is valid JSON. The shell completion gate is the artifact files, not your message.
- Stay alive after READY as review assistant $opencode_title.
- Read guide.md, guide.json, and diffview-review.json when present.
- Help answer/address local review comments, TODOs, and guide refinements without posting to GitHub unless a future user explicitly requests a public mutation through the proper workflow."

        __review_run_interactive_guide_flow "$repo_root" "$opencode_title" "$assistant_bootstrap_path" "$guide_dir" "$guide_md_path" "$guide_json_path" $guides_need_generation "$assistant_bootstrap"
        if test $status -ne 0
            return 1
        end

        if test $guides_need_generation -eq 1 -a -z "$__review_interactive_pane_id"
            set -l markdown_prompt "Prepare a concise manual human review guide for GitHub PR #$pr_number.
Use the pr-human-review-guide skill contract in default raw Markdown manual-output mode.

PR metadata:
- Title: $pr_title
- URL: $pr_url
- Base branch: $pr_base
- Head branch: $pr_head
- Repository root: $repo_root
- Markdown guide artifact path: $guide_md_path
- Existing Markdown guide status: $guide_md_status
- Existing JSON guide status: $guide_json_status

Instructions:
- Do read-only review/context gathering only.
- Do not edit files.
- Do not post comments, approve, request changes, resolve threads, or mutate GitHub state.
- Stay within the repository root above for local file discovery.
- Do not broad-search `/`, `/home`, `/home/vscode`, or sibling worktrees unless explicitly asked.
- Use bounded read-only inspection. When a review subagent needs PR context, prefer authenticated read-only `gh pr view`, `gh pr diff`, `gh pr checks`, or local git diff/status/log context over webfetch or broad filesystem discovery.
- If the existing Markdown guide status is valid, read the existing Markdown guide first and treat it as prior context, not truth. Refresh it against the current PR state: preserve still-relevant observations, remove stale ones, and add new findings/questions.
- If the existing Markdown guide status is missing or empty, generate a fresh guide from the current PR state.
- Return raw Markdown only: no preface, no save-status/meta prose, and no wrapping fenced code block.
- The first content must be the review guide itself.
- Keep the guide concise, reviewer-friendly, and actionable."

            set -l json_prompt "Prepare a concise local Diffview review guide for GitHub PR #$pr_number.
Use the pr-human-review-guide skill contract in structured JSON artifact mode.

PR metadata:
- Title: $pr_title
- URL: $pr_url
- Base branch: $pr_base
- Head branch: $pr_head
- Repository root: $repo_root
- JSON guide artifact path: $guide_json_path
- Markdown guide artifact path: $guide_md_path
- Existing JSON guide status: $guide_json_status
- Existing Markdown guide status: $guide_md_status

Instructions:
- Do read-only review/context gathering only.
- Do not edit files.
- Do not post comments, approve, request changes, resolve threads, or mutate GitHub state.
- Stay within the repository root above for local file discovery.
- Do not broad-search `/`, `/home`, `/home/vscode`, or sibling worktrees unless explicitly asked.
- Use bounded read-only inspection. When a review subagent needs PR context, prefer authenticated read-only `gh pr view`, `gh pr diff`, `gh pr checks`, or local git diff/status/log context over webfetch or broad filesystem discovery.
- If blocked by missing permissions, missing PR context, or incomplete local refs, return valid raw JSON with the blocker captured in the summary or high-risk fields instead of continuing broad discovery.
- Read pr-human-review-guide references/output-templates.md if you need the full JSON schema/example.
- If the existing JSON guide status is valid, read the existing JSON guide first and treat it as prior context, not truth. Refresh it against the current PR state: preserve still-relevant observations, remove stale ones, and add new findings/questions.
- If the existing JSON guide status is missing or invalid, generate a fresh guide from the current PR state.
- Produce a structured JSON artifact for a human doing local review in Diffview, compatible with the saved guide artifact refresh contract.
- Return raw JSON only: no preface, no save-status/meta prose, no Markdown, and no wrapping fenced code block.
- Use this schema exactly: {\"schema_version\":1,\"pr\":{\"number\":123,\"title\":\"...\",\"url\":\"...\",\"base\":\"...\",\"head\":\"...\"},\"summary\":\"...\",\"change_map\":[\"optional concise ASCII/plain-text relationship map line\"],\"high_risk\":[\"...\"],\"validation_focus\":[\"...\"],\"review_strategy\":[\"optional review step\"],\"files\":[{\"path\":\"path/from/diff\",\"depth\":\"read carefully\",\"notes\":[\"file-level guide note\"],\"suggestions\":[{\"severity\":\"Medium\",\"line\":10,\"end_line\":12,\"body\":\"suggested local comment/question\",\"why\":\"why it matters\"}]}]}.
- Fill `pr` from the PR metadata above. `change_map` is optional; include it only when a concise relationship figure, dataflow, or ownership map helps orient the reviewer. Use short ASCII/plain-text strings only, with no Mermaid/images, ideally no more than 8-12 lines. `review_strategy` is optional and may be a string or array; `depth`, `end_line`, and `why` are optional.
- Order `files` as the recommended human/Diffview review order. Future Diffview <Tab>/<S-Tab> navigation may use this order, so do not sort alphabetically unless that is the recommended review order.
- Include one `files` entry for every changed Diffview file so <leader>gdg can navigate the full changed-file set.
- Use exact Diffview file paths from the PR diff. Keep notes and suggestions concise and high-signal.
- For approximate anchors, set `line` and `end_line` to null rather than inventing exact line numbers.
- Use [] for empty arrays and omit optional suggestion fields only when they are not known.
- Keep the output concise and actionable."

            __review_generate_guides_noninteractive "$repo_root" $refresh_guide PR "$guide_md_status" "$guide_json_status" "$guide_md_path" "$guide_json_path" "$guide_md_tmp" "$guide_json_tmp" "PR #$pr_number Markdown review guide" "PR #$pr_number Diffview JSON review guide" "$markdown_prompt" "$json_prompt"
            set -l generate_status $status
            if test $generate_status -ne 0
                return $generate_status
            end
        end

        set -l selector_arg (__review_vim_arg "$selector")
        command nvim "+DiffviewPrOpen $selector_arg"
        return $status
    end

    set -l base_ref_candidates
    if command -q git-spice
        set -l spice_lines (command git-spice --no-prompt down --dry-run 2>/dev/null)
        if test $status -eq 0
            for line in $spice_lines
                set -l trimmed (string trim -- "$line")
                set -l first_token (string match -r -g '^(\S+)' -- "$trimmed")
                switch "$first_token"
                    case WRN INF ERR FTL
                        continue
                end
                if test -n "$trimmed"
                    set -a base_ref_candidates "$trimmed"
                    break
                end
            end
        end
    end
    set -l fallback_base_refs origin/main main
    if string match -q '*FlightSystems*' -- "$remote"
        set fallback_base_refs origin/develop develop
    end
    for fallback_base_ref in $fallback_base_refs
        if not contains -- "$fallback_base_ref" $base_ref_candidates
            set -a base_ref_candidates "$fallback_base_ref"
        end
    end

    set -l base_ref
    for candidate in $base_ref_candidates
        if command git -C "$repo_root" rev-parse --verify --quiet "$candidate^{commit}" >/dev/null 2>/dev/null
            set base_ref "$candidate"
            break
        end
    end
    if test -z "$base_ref"
        echo "review: no usable local base ref found for branch mode" >&2
        echo "review: attempted: "(string join ', ' -- $base_ref_candidates) >&2
        echo "review: fetch or update local refs, then retry" >&2
        return 1
    end

    set -l branch_label (command git -C "$repo_root" branch --show-current 2>/dev/null)
    if test -z "$branch_label"
        echo "review: detached HEAD; using HEAD as the branch label" >&2
        set branch_label HEAD
    end
    set -l safe_branch (string replace -ra '[^A-Za-z0-9._-]+' '-' -- "$branch_label")
    set safe_branch (string replace -ra '(^-+|-+$)' '' -- "$safe_branch")
    if test -z "$safe_branch"
        set safe_branch HEAD
    end

    set -l guide_dir "$HOME/notes/projects/$repo_key/branch-reviews/$safe_branch"
    set -l guide_md_path "$guide_dir/guide.md"
    set -l guide_json_path "$guide_dir/guide.json"
    set -l guide_md_tmp "$guide_dir/guide.md.tmp"
    set -l guide_json_tmp "$guide_dir/guide.json.tmp"

    set -l guide_status (__review_guide_status "$guide_md_path" "$guide_json_path" $refresh_guide)
    set -l guide_md_status $guide_status[1]
    set -l guide_json_status $guide_status[2]
    set -l guides_need_generation $guide_status[3]

    set -l opencode_title "review-$safe_branch"
    set -l assistant_bootstrap_path "$guide_dir/assistant-bootstrap.md"
    set -l diffview_state_path "$guide_dir/diffview-review.json"

    set -l generation_instruction "Existing guides are valid and --refresh-guide was not passed. Do not regenerate guide.md or guide.json. Read the paths and context below, then remain in review assistant mode."
    if test $guides_need_generation -eq 1
        set generation_instruction "Generate or refresh both artifacts now. Write raw Markdown to the exact guide.md path and valid raw JSON to the exact guide.json path. Report READY when both artifacts are written and valid."
    end

    set -l assistant_bootstrap "# Review assistant bootstrap for branch $branch_label

You are the persistent local review assistant for this Diffview session. Use the pr-human-review-guide skill and contract in local branch/range review mode.

Branch metadata:
- Branch label: $branch_label
- Base ref: $base_ref
- Head ref: HEAD
- Diff range: $base_ref...HEAD
- Repository root: $repo_root

Artifact paths:
- Markdown guide.md: $guide_md_path
- Structured guide.json: $guide_json_path
- Diffview local state: $diffview_state_path
- Bootstrap file: $assistant_bootstrap_path

Existing artifact status:
- Markdown guide status: $guide_md_status
- JSON guide status: $guide_json_status
- Refresh requested: $refresh_guide

Initial task:
- $generation_instruction
- Do read-only local context gathering only.
- Do not edit repository files; only write the guide artifacts above when generation or refresh is needed.
- Do not use gh, GitHub APIs, webfetch, or network access.
- Do not post comments, approve, request changes, resolve threads, or mutate any external state.
- Stay within the repository root above for local file discovery; do not broad-search /, /home, /home/vscode, or sibling worktrees unless explicitly asked.
- Prefer bounded local inspection: git diff --stat $base_ref...HEAD, git diff $base_ref...HEAD, git status, git log --oneline $base_ref...HEAD, and local file reads.
- Treat this as local branch/range self-review before a PR exists, using local git diff context only.
- If blocked by missing local refs or incomplete local context, capture the blocker in the artifacts instead of continuing broad discovery.

Artifact contract when generation or refresh is needed:
- guide.md must be raw Markdown only: no preface, no save-status/meta prose, and no wrapping fenced code block.
- guide.json must be raw valid JSON only: no preface, no Markdown, no save-status prose, and no wrapping fenced code block.
- Read pr-human-review-guide references/output-templates.md if you need the exact schema or examples.
- Use this JSON shape: {\"schema_version\":1,\"branch\":{\"label\":\"...\",\"base\":\"...\",\"head\":\"HEAD\"},\"summary\":\"...\",\"change_map\":[\"optional concise ASCII/plain-text relationship map line\"],\"high_risk\":[\"...\"],\"validation_focus\":[\"...\"],\"review_strategy\":[\"optional review step\"],\"files\":[{\"path\":\"path/from/diff\",\"depth\":\"read carefully\",\"notes\":[\"file-level guide note\"],\"suggestions\":[{\"severity\":\"Medium\",\"line\":10,\"end_line\":12,\"body\":\"suggested local comment/question\",\"why\":\"why it matters\"}]}]}.
- Fill branch from the branch metadata above.
- Include one files entry for every changed Diffview file so <leader>gdg can navigate the full changed-file set.
- Order files as the recommended human/Diffview review order, not alphabetically unless that is genuinely best.
- Use exact Diffview file paths from the branch diff. Use null for approximate line anchors rather than inventing exact line numbers.

Completion and follow-up mode:
- When generation or refresh is needed, report READY after guide.md is non-empty and guide.json is valid JSON. The shell completion gate is the artifact files, not your message.
- Stay alive after READY as review assistant $opencode_title.
- Read guide.md, guide.json, and diffview-review.json when present.
- Help answer/address local review comments, TODOs, and guide refinements without posting to GitHub or mutating external state unless a future user explicitly requests a different workflow."

    __review_run_interactive_guide_flow "$repo_root" "$opencode_title" "$assistant_bootstrap_path" "$guide_dir" "$guide_md_path" "$guide_json_path" $guides_need_generation "$assistant_bootstrap"
    if test $status -ne 0
        return 1
    end

    if test $guides_need_generation -eq 1 -a -z "$__review_interactive_pane_id"
        set -l markdown_prompt "Prepare a concise manual human review guide for the current branch before a PR exists.
Use the pr-human-review-guide skill contract in default raw Markdown manual-output mode.

Branch metadata:
- Branch label: $branch_label
- Base ref: $base_ref
- Head ref: HEAD
- Repository root: $repo_root
- Markdown guide artifact path: $guide_md_path
- Existing Markdown guide status: $guide_md_status
- Existing JSON guide status: $guide_json_status

Instructions:
- Do read-only review/context gathering only.
- Do not edit files.
- Do not use gh, GitHub APIs, webfetch, or network access.
- Do not post comments, approve, request changes, resolve threads, or mutate any external state.
- Stay within the repository root above for local file discovery.
- Do not broad-search `/`, `/home`, `/home/vscode`, or sibling worktrees unless explicitly asked.
- Use bounded local inspection. Prefer `git diff --stat $base_ref...HEAD`, `git diff $base_ref...HEAD`, `git status`, and local file reads.
- Treat this as local branch/range self-review before a PR exists, using local git diff context only.
- If the existing Markdown guide status is valid, read the existing Markdown guide first and treat it as prior context, not truth. Refresh it against the current branch diff: preserve still-relevant observations, remove stale ones, and add new findings/questions.
- If the existing Markdown guide status is missing or empty, generate a fresh guide from the current branch diff.
- Return raw Markdown only: no preface, no save-status/meta prose, and no wrapping fenced code block.
- The first content must be the review guide itself.
- Keep the guide concise, reviewer-friendly, and actionable."

        set -l json_prompt "Prepare a concise local Diffview review guide for the current branch before a PR exists.
Use the pr-human-review-guide skill contract in structured JSON artifact mode.

Branch metadata:
- Branch label: $branch_label
- Base ref: $base_ref
- Head ref: HEAD
- Repository root: $repo_root
- JSON guide artifact path: $guide_json_path
- Markdown guide artifact path: $guide_md_path
- Existing JSON guide status: $guide_json_status
- Existing Markdown guide status: $guide_md_status

Instructions:
- Do read-only review/context gathering only.
- Do not edit files.
- Do not use gh, GitHub APIs, webfetch, or network access.
- Do not post comments, approve, request changes, resolve threads, or mutate any external state.
- Stay within the repository root above for local file discovery.
- Do not broad-search `/`, `/home`, `/home/vscode`, or sibling worktrees unless explicitly asked.
- Use bounded local inspection. Prefer `git diff --stat $base_ref...HEAD`, `git diff $base_ref...HEAD`, `git status`, and local file reads.
- If blocked by missing local refs or incomplete local context, return valid raw JSON with the blocker captured in the summary or high-risk fields instead of continuing broad discovery.
- Read pr-human-review-guide references/output-templates.md if you need the full JSON schema/example.
- Treat this as local branch/range self-review before a PR exists, using local git diff context only.
- If the existing JSON guide status is valid, read the existing JSON guide first and treat it as prior context, not truth. Refresh it against the current branch diff: preserve still-relevant observations, remove stale ones, and add new findings/questions.
- If the existing JSON guide status is missing or invalid, generate a fresh guide from the current branch diff.
- Produce a structured JSON artifact for a human doing local review in Diffview, compatible with the saved guide artifact refresh contract.
- Return raw JSON only: no preface, no save-status/meta prose, no Markdown, and no wrapping fenced code block.
- Use this schema exactly: {\"schema_version\":1,\"branch\":{\"label\":\"...\",\"base\":\"...\",\"head\":\"HEAD\"},\"summary\":\"...\",\"change_map\":[\"optional concise ASCII/plain-text relationship map line\"],\"high_risk\":[\"...\"],\"validation_focus\":[\"...\"],\"review_strategy\":[\"optional review step\"],\"files\":[{\"path\":\"path/from/diff\",\"depth\":\"read carefully\",\"notes\":[\"file-level guide note\"],\"suggestions\":[{\"severity\":\"Medium\",\"line\":10,\"end_line\":12,\"body\":\"suggested local comment/question\",\"why\":\"why it matters\"}]}]}.
- Fill `branch` from the branch metadata above. `change_map` is optional; include it only when a concise relationship figure, dataflow, or ownership map helps orient the reviewer. Use short ASCII/plain-text strings only, with no Mermaid/images, ideally no more than 8-12 lines. `review_strategy` is optional and may be a string or array; `depth`, `end_line`, and `why` are optional.
- Order `files` as the recommended human/Diffview review order. Future Diffview <Tab>/<S-Tab> navigation may use this order, so do not sort alphabetically unless that is the recommended review order.
- Include one `files` entry for every changed Diffview file so <leader>gdg can navigate the full changed-file set.
- Use exact Diffview file paths from the branch diff. Keep notes and suggestions concise and high-signal.
- For approximate anchors, set `line` and `end_line` to null rather than inventing exact line numbers.
- Use [] for empty arrays and omit optional suggestion fields only when they are not known.
- Keep the output concise and actionable."

        __review_generate_guides_noninteractive "$repo_root" $refresh_guide branch "$guide_md_status" "$guide_json_status" "$guide_md_path" "$guide_json_path" "$guide_md_tmp" "$guide_json_tmp" "Branch $branch_label Markdown review guide" "Branch $branch_label Diffview JSON review guide" "$markdown_prompt" "$json_prompt"
        set -l generate_status $status
        if test $generate_status -ne 0
            return $generate_status
        end
    end

    set -l guide_lua (__review_lua_single_quoted_string "$guide_json_path")
    set -l guide_md_lua (__review_lua_single_quoted_string "$guide_md_path")
    set -l repo_lua (__review_lua_single_quoted_string "$repo_root")
    set -l diff_arg (__review_vim_arg "$base_ref...HEAD")
    set -l diffview_command "DiffviewOpen $diff_arg"
    if string match -qr '/Systems[^/]*(/|$)' -- (pwd)
        set diffview_command "$diffview_command -- . :!.opencode/skills :!notes"
    else if string match -qr '/Systems[^/]*(/|$)' -- "$repo_root"
        set diffview_command "$diffview_command -- . :!.opencode/skills :!notes"
    end

    command nvim "+lua require('utils.diffview_review').set_active_guide_context({ path = $guide_lua, markdown_path = $guide_md_lua, repo = $repo_lua })" "+$diffview_command"
end
