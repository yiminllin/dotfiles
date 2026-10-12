function __review_lua_string --argument-names value
    set value (string replace -a '\\' '\\\\' -- "$value")
    set value (string replace -a "'" "\\'" -- "$value")
    printf "'%s'\n" "$value"
end

function __review_shell_string --argument-names value
    set value (string replace -a "'" "'\\''" -- "$value")
    printf "'%s'\n" "$value"
end

function __review_open_pi_pane --argument-names repo_root title bootstrap_path boundary refresh
    if not set -q TMUX; or test -z "$TMUX"; or not command -q tmux; or not command -q pi
        echo "review: Diffview is available; the visible review agent requires tmux and pi" >&2
        return 1
    end

    set -l caller "$TMUX_PANE"
    if test -z "$caller"
        set caller (command tmux display-message -p '#{pane_id}')
        or return 1
    end
    if test -z "$caller"
        echo 'review: could not identify the invoking tmux pane' >&2
        return 1
    end

    set -l guide_path (path dirname "$bootstrap_path")/guide.json
    set -l prompt "/skill:pr-human-review-guide The user explicitly authorizes creating and updating $guide_path and $guide_path.tmp, including outside $repo_root, for this review session. This is prior permission for those two files only; do not request it again. It does not authorize other writes, network access, authentication, or source/GitHub changes. Read and execute this review bootstrap, then stay in review assistant mode: $bootstrap_path"
    set -l panes (command tmux list-panes -s -t "$caller" -F '#{pane_id}|#{@pi_agent_name}|#{@pi_review_repo}|#{pane_current_command}|#{pane_start_command}|#{pane_current_path}')
    for pane in $panes
        set -l fields (string split '|' -- "$pane")
        if test "$fields[2]" = "$title"; and begin
                test "$fields[3]" = "$repo_root"; or begin
                    test -z "$fields[3]"; and test "$fields[6]" = "$repo_root"
                end
            end
            if test "$fields[4]" = pi; or begin
                    string match -q '*exec pi*' -- "$fields[5]"
                    and not contains -- "$fields[4]" fish bash zsh sh
                end
                if test "$fields[1]" != "$caller"
                    command tmux move-pane -d -v -l 40% -s "$fields[1]" -t "$caller"
                    or return 1
                end
                set -l previous (command tmux show-option -pqv -t "$fields[1]" @pi_review_boundary)
                if test "$previous" != "$boundary"; or test "$refresh" = 1
                    command tmux send-keys -t "$fields[1]" -l "$prompt"
                    and command tmux send-keys -t "$fields[1]" M-Enter
                    or return 1
                    command tmux set-option -pt "$fields[1]" @pi_review_boundary "$boundary"
                end
                command tmux set-option -pt "$fields[1]" @pi_review_repo "$repo_root"
                echo "review: reusing visible Pi pane $title"
                return 0
            end
        end
    end

    set -l title_arg (__review_shell_string "$title")
    set -l prompt_arg (__review_shell_string "$prompt")
    set -l launch "tmux set-option -pt \"\$TMUX_PANE\" allow-passthrough off; tmux set-option -pt \"\$TMUX_PANE\" @pi_agent_name $title_arg; tmux select-pane -t \"\$TMUX_PANE\" -T $title_arg; exec pi --name $title_arg $prompt_arg"
    set -l pane_id (command tmux split-window -t "$caller" -v -l 40% -d -P -F '#{pane_id}' -c "$repo_root" "$launch")
    or return 1
    command tmux set-option -pt "$pane_id" @pi_review_repo "$repo_root"
    command tmux set-option -pt "$pane_id" @pi_review_boundary "$boundary"
    echo "review: opened visible Pi pane $title"
end

function review --description "Open Diffview immediately with a visible Pi review assistant"
    set -l refresh 0
    set -l no_agent 0
    set -l selector
    for arg in $argv
        switch $arg
            case --refresh-guide
                set refresh 1
            case --no-agent
                set no_agent 1
            case -h --help
                echo 'usage: review [--no-agent] [--refresh-guide] [pr-number-or-url]'
                return 0
            case '-*'
                echo "review: unknown option: $arg" >&2
                return 2
            case '*'
                if set -q selector[1]
                    echo 'review: expected at most one PR number or URL' >&2
                    return 2
                end
                set selector "$arg"
        end
    end
    if test $refresh = 1 -a $no_agent = 1
        echo 'review: --refresh-guide requires the agent; omit --no-agent' >&2
        return 2
    end

    if test $no_agent = 0; and begin
            not set -q TMUX; or test -z "$TMUX"; or not command -q tmux; or not command -q pi
        end
        echo "review: opening Diffview only; the visible agent requires tmux and pi" >&2
        set no_agent 1
    end

    set -l root (command git rev-parse --show-toplevel 2>/dev/null)
    or begin
        echo 'review: not inside a git repository' >&2
        return 1
    end
    set -l remote (command git -C "$root" remote get-url origin 2>/dev/null)
    set -l repo_key (string replace -r '\.git/?$' '' -- "$remote")
    set repo_key (string replace -r '/+$' '' -- "$repo_key")
    set repo_key (string replace -r '^.*[:/]' '' -- "$repo_key")
    test -n "$repo_key"; or set repo_key (basename "$root")

    set -l kind branch
    set -l metadata '{}'
    set -l label (command git -C "$root" branch --show-current)
    test -n "$label"; or set label HEAD
    set -l base_ref
    set -l head_ref HEAD
    if set -q selector[1]
        set kind pr
        echo "review: looking up PR $selector..."
        set metadata (command gh pr view "$selector" --json number,title,url,body,baseRefName,headRefName)
        or return 1
        set -l fields (printf '%s' "$metadata" | command python3 -c 'import json,sys; p=json.load(sys.stdin); print(p["number"]); print(p["baseRefName"])')
        or return 1
        set label "$fields[1]"
        set base_ref "refs/remotes/origin/$fields[2]"
        set head_ref "refs/remotes/origin/pr/$label"
        echo "review: fetching PR $label and its base..."
        command git -C "$root" fetch origin "+refs/heads/$fields[2]:$base_ref" "+refs/pull/$label/head:$head_ref"
        or return 1
    else
        set -l candidates
        if command -q git-spice
            set -l spice_lines (command git-spice --no-prompt down --dry-run 2>/dev/null)
            if test $status = 0
                for line in $spice_lines
                    set -l trimmed (string trim -- "$line")
                    set -l token (string match -r -g '^(\S+)' -- "$trimmed")
                    if not contains -- "$token" WRN INF ERR FTL; and test -n "$trimmed"
                        set -a candidates "$trimmed"
                        break
                    end
                end
            end
        end
        if string match -q '*FlightSystems*' -- "$remote"
            set -a candidates origin/develop develop
        else
            set -a candidates origin/main main
        end
        for candidate in $candidates
            if command git -C "$root" rev-parse --verify --quiet "$candidate^{commit}" >/dev/null
                set base_ref "$candidate"
                break
            end
        end
        if test -z "$base_ref"
            echo 'review: no usable local base; fetch/update the base ref, then retry' >&2
            return 1
        end
    end

    set -l head (command git -C "$root" rev-parse "$head_ref^{commit}")
    or return 1
    set -l base (command git -C "$root" merge-base "$base_ref" "$head")
    or return 1
    set -l boundary "$base..$head"
    set -l safe_label (string replace -ra '[^A-Za-z0-9._-]+' '-' -- "$label")
    set -l guide_dir "$HOME/notes/projects/$repo_key/branch-reviews/$safe_label"
    if test "$kind" = pr
        set guide_dir "$HOME/notes/projects/$repo_key/pr-reviews/$label"
    end
    set -l title "review-$label"
    set -l guide "$guide_dir/guide.json"
    set -l bootstrap "$guide_dir/assistant-bootstrap.md"
    set -l source_path (path resolve (status filename))
    set -l context (command python3 -c 'import json,sys
root,key,kind,label,base,head,guide,title,metadata,no_agent=sys.argv[1:]
p=json.loads(metadata)
url=p.get("url", "")
parts=url.split("/")
print(json.dumps(dict(repo=root,repo_key=key,context_kind=kind,pr_number=p.get("number"),pr_title=p.get("title"),pr_body=p.get("body"),pr_url=url,owner=parts[3] if len(parts)>4 else None,repo_name=parts[4] if len(parts)>4 else None,base_oid=base,head_oid=head,diffview_rev_arg=base+".."+head,path=guide,assistant_name=title if no_agent=="0" else None)))' "$root" "$repo_key" "$kind" "$label" "$base" "$head" "$guide" "$title" "$metadata" "$no_agent")
    or return 1

    set -l diff_args "$boundary"
    if string match -qr '/Systems[^/]*(/|$)' -- "$root"
        set -a diff_args -- . ':!notes' ':!.pi/skills'
    end
    set -l diff_json (command python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' $diff_args)
    if test $no_agent = 0
        command mkdir -p "$guide_dir"
        or return 1
        printf '%s\n' "# Persistent Diffview review assistant

Review context (use these exact immutable revisions, not the checked-out branch):
$context

Refresh requested: $refresh
Guide: $guide
Local comments: $guide_dir/diffview-review.json

Read the pr-human-review-guide skill and its output templates. Review only git diff $boundary with the same path exclusions as Diffview: $diff_json. Use the supplied PR body as claims to verify against code. Keep source inspection within $root; do not use network, authentication, or mutate GitHub or source files.

Artifact write permission: the user invoked review and explicitly authorizes creating and updating $guide and $guide.tmp throughout this review session, even though their directory may be outside $root. This is the approved exception to the source-directory boundary, not permission for arbitrary external writes. Use $guide.tmp for atomic replacement of $guide. Do not ask for this permission again. Never edit $guide_dir/diffview-review.json.

Follow the persistent diagram-first Diffview contract in references/output-templates.md. Include context.base_oid=$base and context.head_oid=$head. Stay available for Diffview questions and direct conversation; update this same guide as understanding changes. Neovim owns local comments, reviewed-file progress, and ownership scope.

Each Diffview request includes exact comment/request IDs and an agent-replies JSON path. Write a raw JSON reply there with comment_id, request_id, author, body, created_at, status/error, atomically via rename. Never edit diffview-review.json; Neovim owns it. Your visible answer and thread reply must agree. Do not post or resolve anything on GitHub." >"$bootstrap"
    end

    set -l context_lua (__review_lua_string "$context")
    set -l diff_lua (__review_lua_string "$diff_json")
    set -l startup "lua require('utils.diffview_review').set_active_guide_context(vim.json.decode($context_lua)); vim.api.nvim_cmd({cmd='DiffviewOpen',args=vim.json.decode($diff_lua)}, {})"
    set -l agent_command "lua vim.defer_fn(function() require('utils.diffview_review').jump_to_initial_guide_file() end, 200)"
    if test $no_agent = 0
        set -l command_json (command python3 -c 'import json,sys; print(json.dumps(["fish","-c","source \"$argv[1]\"; __review_open_pi_pane $argv[2..-1]","--"]+sys.argv[1:]))' "$source_path" "$root" "$title" "$bootstrap" "$boundary" "$refresh")
        set -l command_lua (__review_lua_string "$command_json")
        set agent_command "lua vim.defer_fn(function() vim.system(vim.json.decode($command_lua), {text=true}, function(result) vim.schedule(function() vim.notify(vim.trim(result.stdout .. result.stderr), result.code == 0 and vim.log.levels.INFO or vim.log.levels.WARN, {title='Review agent'}) end) end) end, 200)"
    end
    command nvim "+$startup" "+$agent_command"
end
