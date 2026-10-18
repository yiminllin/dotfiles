---
name: "preserve-upstream-during-git-spice-restack"
description: "Resolve FlightSystems git-spice restack conflicts without dropping newer develop changes"
version: 8
created: "2026-09-22"
updated: "2026-10-15"
---
## When to Use
Use when git-spice restacks an older FlightSystems branch onto newer develop and a conflicted file contains unrelated upstream changes that must be preserved.

## Procedure
1. Record the original branch head and each original commit/parent before restarting the restack; keep untracked files untouched.
2. Run the restack with git-spice and inspect all unmerged stages. Distinguish an active rebase from an autostash restoration conflict using `git status`, conflict labels, and the paths returned by `git rev-parse --git-path rebase-merge` and `git rev-parse --git-path rebase-apply`; do not assume `.git` is a directory because linked worktrees use a `.git` file and keep rebase state under the common repository. In rebase conflicts, treat `ours` as the new base plus already-replayed commits and `theirs` as the older commit being replayed.
3. If the rebase completed but autostash restoration conflicted (for example, labels show `Updated upstream`, `Stash base`, and `Stashed changes`, with no rebase directory), preserve both intended deltas, stage the resolved paths, and do not run `git-spice rebase continue`. Keep the autostash entry until the restored work is verified; deleting it is a separate destructive cleanup.
4. For a heavily conflicted file, start from `ours`, generate the exact original commit patch with `git diff <commit>^ <commit> -- <file>`, and apply it with rejects enabled so only non-applicable hunks need manual merging.
5. Resolve rejected hunks by preserving current develop behavior and adding only the original commit's intended delta. Never select an entire older file with `--theirs`.
6. When newer develop migrated Rust BUILD targets to automatic Cargo dependency discovery, preserve the new dependency-light BUILD structure. Apply package renames/removals in Cargo manifests and source without reintroducing the older commit's explicit Bazel dependency lists; retain only explicit dependencies that the new-base target still requires.
7. For modify/delete conflicts where the replayed commit removes an entire obsolete component, inspect the new-base edits, confirm their behavior is superseded or relocated, then accept the deletion rather than preserving dead files.
8. Stage only resolved tracked paths. Continue with `git-spice rebase continue` only when an active git-spice rebase still exists.
9. Compare original and rebased ranges with `git range-diff`; compare changed-file/status and deletion sets; verify no conflict markers, unmerged paths, or tracked worktree changes remain.
10. Run focused Bazel tests at the top of the restacked chain so automatic dependency discovery and cumulative branch compatibility are exercised before submission.
11. If git-spice submission reports a stale remote lease, inspect the live PR head and compare its patch before requesting explicit authorization for `git-spice upstack submit --force`; never force solely because the tool suggests it.
## Pitfalls
- During a rebase, theirs is the older replayed commit and can silently delete newer upstream behavior and tests.
- A conflict-free rebase is not sufficient evidence; audit aggregate diffs, deletion sets, and patch IDs before considering it resolved.
- A final-tree merge check is partial evidence. Commit-by-commit restacking can stop on intermediate historical conflicts that the net-tree check does not expose. At every stopped commit, inspect and preserve the required base-side and replayed-commit changes.
- Inspect every linked worktree before mutation. The root worktree can be clean while a cleanup branch is checked out elsewhere with staged fixes. Obtain explicit permission to include or preserve those edits.
- For an already-landed prerequisite represented by a closed bridge PR, inspect residual adaptations rather than dropping its entire patch blindly. Move required completion/fixture/lockfile changes into the owning active boundary, then use git-spice upstack onto to bypass the bridge. Untracking can preserve its branch and recovery refs without deleting history.
- Scan conflict markers anchored at line starts. Searching for any occurrence of repeated pipes falsely flags ASCII diagrams; a stale diff3 parent marker may also already exist in a prior commit and replay without conflict.
- Published upstream refs may have newer parents than local develop. Copying the exact published heads locally does not authorize rebasing or pushing the upstream author's stack, or modifying an unrelated sibling branch.
- For independent runtime lanes, validate a backed-up combined source overlay. Runtime imports can overlap even if functional hunks compose; derive imports from actual crate exports, and restore source in finally without adding a proof branch or commit.
- Remove task-created .rej files, and never stage unrelated untracked notes.
- An existing git-spice continuation can finish the current Git rebase, rebase the branch again onto a newer recorded base, and continue into downstream or collection branches. Inspect the pending operation scope before continuing; obtain approval for additional history changes rather than assuming only the currently conflicted branch will move.
- A passing proto_serde_support_test wrapper does not by itself prove the underlying library's Clippy aspect ran. For a gate failure in //ash/sil_sims:sil_sims, explicitly build that library with the normal +clippy_checks output group and check its .clippy.ok result, in addition to the focused tests.
## Verification
1. git range-diff <old-base>..<old-head> develop..HEAD shows only expected context adjustments.
2. Original and rebased changed-file/status sets match, and no unexpected deleted files appear.
3. git diff develop...HEAD does not remove upstream-only symbols, behavior, or tests.
4. For a single-file conflict, compare the resolved file against index stage 2 with only the replayed commit's intended patch applied. This proves unrelated upstream changes were retained.
5. If upstream split a framework into runtime and orchestration artifacts, apply runtime build flags only to the runtime artifact. Check framework expansion, both artifact argument lists, defaults/overrides, and retained metadata without publishing.
6. git diff --check passes; git diff --name-only --diff-filter=U is empty; git-spice reports the branch as needing only a push.
7. Compile and test the lowest changed branch as well as the stack tip. Newly added upstream scenarios can replay without textual conflicts while still referencing APIs removed by a cleanup branch; migrate those call sites and preserve former implicit behavior such as dock population.