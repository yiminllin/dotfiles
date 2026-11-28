#!/usr/bin/env python3
"""Check picker-only selection without opening workspace sessions."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "tmux/.tmux/tmux-session-finder"


class SessionFinderTests(unittest.TestCase):
    def test_print_mode_includes_worktrees_and_never_opens_a_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = {
                "fd": "printf '/work/repo/.git\\n/work/review tree/.git\\n/work/workspace-tools/.git\\n'",
                "git": 'if test "$2" = /work/workspace-tools; then '
                       "printf 'worktree /work/workspace-tools\\nbranch refs/heads/dev\\n'; else "
                       "printf 'worktree /work/repo\\nbranch refs/heads/main\\n\\n"
                       "worktree /work/review tree\\nbranch refs/heads/review/setup\\n\\n"
                       "worktree /work/detached\\nHEAD 1234567890\\ndetached\\n'; fi",
                "tmux": 'test "$1" = -V || exit 99; printf "tmux 3.4\\n"',
                "fzf": 'printf "%s\\n" "$@" > "$FZF_ARGS"; cat > "$CANDIDATES"; '
                       'if test -n "$SELECTION"; then awk -F "\\t" \'$1 == ENVIRON["SELECTION"]\' "$CANDIDATES"; fi; '
                       'exit "${FZF_STATUS:-0}"',
            }
            for name, body in commands.items():
                path = root / name
                path.write_text("#!/bin/sh\n" + body + "\n")
                path.chmod(0o755)
            candidates = root / "candidates"
            env = {
                **os.environ,
                "HOME": str(root),
                "PATH": f"{root}:{os.environ['PATH']}",
                "CANDIDATES": str(candidates),
                "FZF_ARGS": str(root / "fzf-args"),
            }
            for selection, expected in [
                ("/work/review tree", "/work/review tree\n"),
                (str(root), f"{root}\n"),
                ("", ""),
            ]:
                result = subprocess.run(
                    ["bash", str(SOURCE), "--print"],
                    env={**env, "SELECTION": selection},
                    capture_output=True, text=True, check=True,
                )
                self.assertEqual(result.stdout, expected)
                self.assertEqual(candidates.read_text().splitlines(), [
                    f"\t{'Path':21} │ {'Repo':15} │ Branch",
                    f"{root}\t{'~':21} │ {'Home':15} │",
                    f"/work/repo\t{'/work/repo':21} │ {'repo':15} │ main",
                    f"/work/review tree\t{'  /work/review tree':21} │ {'':15} │ review/setup",
                    f"/work/detached\t{'  /work/detached':21} │ {'':15} │ detached @ 12345678",
                    f"/work/workspace-tools\t{'/work/workspace-tools':21} │ workspace-tools │ dev",
                ])
                args = (root / "fzf-args").read_text().splitlines()
                self.assertIn("--no-tmux", args)
                self.assertIn("--no-height", args)
                self.assertIn("--no-sort", args)
                self.assertIn("--with-nth=2..", args)
                self.assertIn("--header-lines=1", args)
            for status, expected in [(130, 0), (2, 2)]:
                result = subprocess.run(
                    ["bash", str(SOURCE), "--print"],
                    env={**env, "SELECTION": "", "FZF_STATUS": str(status)},
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, expected)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
