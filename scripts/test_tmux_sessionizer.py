#!/usr/bin/env python3
"""Verify workspace creation/reuse without starting any agents."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "tmux/.tmux/tmux-sessionizer"


@unittest.skipUnless(shutil.which("tmux"), "requires tmux")
class SessionizerTests(unittest.TestCase):
    def test_ensure_reuses_paths_and_separates_colliding_names(self):
        base = ["tmux", "-L", f"sessionizer-test-{os.getpid()}"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "one/workspace", root / "two/workspace"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            env = dict(os.environ)
            env.pop("TMUX", None)
            env.pop("TMUX_PANE", None)

            def tmux(*args):
                return subprocess.check_output(base + list(args), env=env, text=True).strip()

            try:
                original = tmux("-f", "/dev/null", "new-session", "-d", "-P", "-F", "#{session_id}",
                                "-s", "workspace", "-c", str(first))
                env["TMUX"] = tmux("display-message", "-p", "#{socket_path},#{pid},0")

                def ensure(path):
                    return subprocess.check_output(["bash", str(SOURCE), "--ensure", str(path)], env=env, text=True).strip()

                self.assertEqual(ensure(first), original)
                self.assertEqual(tmux("show-option", "-t", original, "-qv", "@workspace_path"), str(first))
                other = ensure(second)
                self.assertNotEqual(original, other)
                self.assertEqual(tmux("display-message", "-pt", other, "#{session_name}"), "workspace-2")
                tmux("rename-session", "-t", original, "workspace-custom")
                self.assertEqual(ensure(first), original)
                self.assertEqual(ensure(second), other)
                self.assertEqual(tmux("show-option", "-t", other, "-qv", "@workspace_path"), str(second))
                self.assertEqual(len(tmux("list-sessions").splitlines()), 2)
                for session in (original, other):
                    self.assertEqual(len(tmux("list-windows", "-t", session).splitlines()), 1)
                self.assertEqual(tmux("list-windows", "-t", other, "-F", "#{window_name}"), " shell")
            finally:
                subprocess.run(base + ["kill-server"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
