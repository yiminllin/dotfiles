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
                "fd": "printf '/work/repo/.git\\n'",
                "git": "printf 'worktree /work/repo\\n\\nworktree /work/review tree\\n'",
                "tmux": 'test "$1" = -V || exit 99; printf "tmux 3.4\\n"',
                "fzf": 'printf "%s\\n" "$@" > "$FZF_ARGS"; cat > "$CANDIDATES"; printf "%s\\n" "$SELECTION"; exit "${FZF_STATUS:-0}"',
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
                ("~", f"{root}\n"),
                ("", ""),
            ]:
                result = subprocess.run(
                    ["bash", str(SOURCE), "--print"],
                    env={**env, "SELECTION": selection},
                    capture_output=True, text=True, check=True,
                )
                self.assertEqual(result.stdout, expected)
                self.assertEqual(candidates.read_text().splitlines(), ["~", "/work/repo", "/work/review tree"])
                args = (root / "fzf-args").read_text().splitlines()
                self.assertIn("--no-tmux", args)
                self.assertIn("--no-height", args)
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
