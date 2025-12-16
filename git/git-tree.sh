#!/bin/bash
set -euo pipefail

# ANSI codes for formatting
BOLD=""
RESET=""
GREEN=""
RED=""
YELLOW=""
if [ -t 1 ]; then
    BOLD=$'\e[1m'
    RESET=$'\e[0m'
    GREEN=$'\e[32m'
    RED=$'\e[31m'
    YELLOW=$'\e[33m'
fi

# Fetch all PR info in one API call (the main speedup)
declare -A PR_TITLES
declare -A PR_STATES
declare -A PR_CI
fetch_all_prs() {
    # Fetch all PRs (open, closed, merged) for local branches
    while IFS=$'\t' read -r branch title state; do
        # Only store if not already set (prefer open over closed)
        if [[ -z "${PR_TITLES[$branch]:-}" ]] || [[ "$state" == "OPEN" ]]; then
            PR_TITLES["$branch"]="$title"
            PR_STATES["$branch"]="$state"
        fi
    done < <(gh pr list --state all --limit 500 --json headRefName,title,state --jq '.[] | [.headRefName, .title, .state] | @tsv' 2>/dev/null || true)
}

# Fetch CI status for open PRs (separate call to avoid timeout)
fetch_ci_status() {
    local branch="$1"
    if [[ -n "${PR_CI[$branch]:-}" ]]; then
        echo "${PR_CI[$branch]}"
        return
    fi
    
    # Use timeout to avoid hanging on branches without PRs
    local ci_status
    ci_status=$(timeout 10 gh pr view "$branch" --json statusCheckRollup --jq '[.statusCheckRollup[]? | .conclusion // .state] | if length == 0 then "NONE" elif any(. == "FAILURE") then "FAIL" elif any(. == "PENDING") then "PENDING" elif all(. == "SUCCESS" or . == "SKIPPED" or . == "NEUTRAL" or . == "CANCELLED") then "PASS" else "UNKNOWN" end' 2>/dev/null || echo "NONE")
    
    PR_CI["$branch"]="$ci_status"
    echo "$ci_status"
}

# Cache for git operations
declare -A REV_CACHE
declare -A PARENT_CACHE

get_rev() {
    local branch="$1"
    if [[ -z "${REV_CACHE[$branch]:-}" ]]; then
        REV_CACHE["$branch"]=$(git rev-parse "$branch" 2>/dev/null || echo "")
    fi
    echo "${REV_CACHE[$branch]}"
}

# Determine parent branch (cached)
get_parent_branch() {
    local branch="$1"
    shift
    local all_branches=("$@")
    
    if [[ -n "${PARENT_CACHE[$branch]:-}" ]]; then
        echo "${PARENT_CACHE[$branch]}"
        return
    fi
    
    local branch_tip=$(get_rev "$branch")
    if [ -z "$branch_tip" ]; then
        PARENT_CACHE["$branch"]="develop"
        echo "develop"
        return
    fi
    
    local best_parent="develop"
    local best_distance=999999
    
    # Find the closest ancestor branch (fewest commits between them)
    for candidate in "${all_branches[@]}"; do
        if [ "$candidate" = "$branch" ] || [ "$candidate" = "develop" ]; then
            continue
        fi
        
        local candidate_tip=$(get_rev "$candidate")
        if [ -z "$candidate_tip" ]; then
            continue
        fi
        
        # Skip if candidate is NOT an ancestor of this branch
        if ! git merge-base --is-ancestor "$candidate_tip" "$branch_tip" 2>/dev/null; then
            continue
        fi
        
        # Skip if this branch is an ancestor of candidate (would create cycle)
        if git merge-base --is-ancestor "$branch_tip" "$candidate_tip" 2>/dev/null; then
            continue
        fi
        
        # Count commits between candidate and this branch (fewer = closer parent)
        local distance=$(git rev-list --count "$candidate_tip".."$branch_tip" 2>/dev/null || echo "999999")
        if [ "$distance" -lt "$best_distance" ]; then
            best_parent="$candidate"
            best_distance=$distance
        fi
    done
    
    PARENT_CACHE["$branch"]="$best_parent"
    echo "$best_parent"
}

# Calculate ahead/behind relative to parent (with colors)
get_ahead_behind() {
    local branch="$1"
    local parent="$2"
    
    local counts=$(git rev-list --left-right --count "$parent"..."$branch" 2>/dev/null || echo "0	0")
    local behind=$(echo "$counts" | cut -f1)
    local ahead=$(echo "$counts" | cut -f2)
    
    echo "${GREEN}${ahead}${RESET}|${RED}${behind}${RESET}"
}

# Build and print the tree
main() {
    local current_branch=$(git branch --show-current)
    
    # Get all local branches
    local branches=($(git branch --list | sed 's/^[* ] //'))
    
    # Fetch all PRs in one call
    fetch_all_prs
    
    # Pre-compute all parent relationships and depths
    declare -A DEPTH_CACHE
    DEPTH_CACHE["develop"]=0
    
    for br in "${branches[@]}"; do
        if [ "$br" != "develop" ]; then
            get_parent_branch "$br" "${branches[@]}" > /dev/null
        fi
    done
    
    # Calculate depths recursively
    calc_depth() {
        local branch="$1"
        if [[ -n "${DEPTH_CACHE[$branch]:-}" ]]; then
            echo "${DEPTH_CACHE[$branch]}"
            return
        fi
        local parent="${PARENT_CACHE[$branch]:-develop}"
        local parent_depth=$(calc_depth "$parent")
        DEPTH_CACHE["$branch"]=$((parent_depth + 1))
        echo "${DEPTH_CACHE[$branch]}"
    }
    
    for br in "${branches[@]}"; do
        calc_depth "$br" > /dev/null
    done
    
    # Calculate max branch column width (indent + indicator + branch name + [a|b])
    # [a|b] is roughly 7 chars max like [99|99]
    local max_branch_width=0
    for br in "${branches[@]}"; do
        local depth="${DEPTH_CACHE[$br]}"
        local indent_width=$((depth * 2))
        local indicator_width=2  # "◯ " or empty but reserve space
        local ab_width=8  # " [a|b]" space + brackets
        local total_width=$((indent_width + indicator_width + ${#br} + ab_width))
        if [ "$total_width" -gt "$max_branch_width" ]; then
            max_branch_width=$total_width
        fi
    done
    
    # Print tree recursively with alignment
    print_tree() {
        local branch="$1"
        local depth="${DEPTH_CACHE[$branch]}"
        local indent=""
        for ((i=0; i<depth; i++)); do indent+="  "; done
        
        local pr_title="${PR_TITLES[$branch]:-}"
        local pr_state="${PR_STATES[$branch]:-}"
        local parent=""
        
        if [ "$branch" = "develop" ]; then
            parent="origin/develop"
        else
            parent="${PARENT_CACHE[$branch]}"
        fi
        
        local ahead_behind="[$(get_ahead_behind "$branch" "$parent")]"
        
        # PR state indicator (yellow=open, green=merged, red=closed)
        local state_indicator="  "  # 2 chars placeholder
        local ci_indicator=""
        case "$pr_state" in
            "OPEN")
                state_indicator="${YELLOW}◯${RESET} "
                # Get CI status for open PRs
                if [ -n "$pr_title" ]; then
                    local ci_status=$(fetch_ci_status "$branch")
                    case "$ci_status" in
                        "PASS")    ci_indicator="${GREEN}✓${RESET}" ;;
                        "FAIL")    ci_indicator="${RED}✗${RESET}" ;;
                        "PENDING") ci_indicator="${YELLOW}⋯${RESET}" ;;
                    esac
                fi
                ;;
            "MERGED") state_indicator="${GREEN}✓${RESET} " ;;
            "CLOSED") state_indicator="${RED}✗${RESET} " ;;
        esac
        
        # Bold for current branch
        local bold_start=""
        local bold_end=""
        if [ "$branch" = "$current_branch" ]; then
            bold_start="$BOLD"
            bold_end="$RESET"
        fi
        
        # Get ahead/behind raw numbers for width calculation
        local counts=$(git rev-list --left-right --count "${parent:-origin/develop}"..."$branch" 2>/dev/null || echo "0	0")
        local behind_num=$(echo "$counts" | cut -f1)
        local ahead_num=$(echo "$counts" | cut -f2)
        local ab_plain="[${ahead_num}|${behind_num}]"
        
        # Calculate padding for branch + [a|b] column
        local branch_col_plain_len=$((${#indent} + 2 + ${#branch} + 1 + ${#ab_plain}))  # indent + indicator(2) + branch + space + [a|b]
        local branch_padding=$((max_branch_width - branch_col_plain_len))
        local pad=""
        for ((i=0; i<branch_padding; i++)); do pad+=" "; done
        
        # PR title column
        local pr_col=""
        if [ -n "$pr_title" ]; then
            pr_col=" - ${pr_title}"
        fi
        
        # CI indicator suffix
        local ci_suffix=""
        if [ -n "$ci_indicator" ]; then
            ci_suffix=" ${ci_indicator}"
        fi
        
        # Print aligned: branch [a|b] <padding> - PR title [CI]
        printf "%s%s%s%s%s %s%s%s%s\n" \
            "$indent" "$state_indicator" "$bold_start" "$branch" "$bold_end" \
            "$ahead_behind" "$pad" "$pr_col" "$ci_suffix"
        
        # Print children
        for child in "${branches[@]}"; do
            if [ "$child" != "develop" ] && [ "${PARENT_CACHE[$child]}" = "$branch" ]; then
                print_tree "$child"
            fi
        done
    }
    
    # Print header
    echo "┌──────────────────────┐"
    echo "│       GIT TREE       │"
    echo "└──────────────────────┘"
    
    # Start from develop
    if [[ " ${branches[*]} " =~ " develop " ]]; then
        print_tree "develop"
    else
        echo "develop (not checked out)"
    fi

    echo "┌──────────────────────┐"
    echo "│       GIT TREE       │"
    echo "└──────────────────────┘"
}

main "$@"
