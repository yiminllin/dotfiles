#!/usr/bin/env python3
"""Offline checks for tmux file hints. Run with python3 scripts/test_tmux_file_hints.py."""

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest

import tmux_file_hints as hints


class FileHintsTest(unittest.TestCase):
    def test_existing_files_and_source_locations(self):
        with tempfile.TemporaryDirectory() as cwd:
            path = Path(cwd) / "design.md"
            path.touch()
            for token in (str(path), "./design.md", "design.md", f"file://{path}"):
                self.assertEqual(hints.resolve_file_target(token, cwd), str(path))
            self.assertEqual(hints.resolve_file_target("design.md:12:3", cwd), f"{path}:12:3")
            self.assertIsNone(hints.resolve_file_target("missing.md", cwd))
            self.assertIsNone(hints.resolve_file_target(cwd, cwd))
            self.assertIsNone(hints.resolve_file_target("https://example.com/design.md", cwd))

    def test_wrapped_paths_keep_unicode_screen_positions(self):
        with tempfile.TemporaryDirectory() as cwd:
            path = Path(cwd) / "design.md"
            path.touch()
            text = f"文档 `{path}:12:3` and missing.md"
            file_positions = hints.find_file_positions(["", text], cwd, 20)
            self.assertEqual(file_positions, [(1, 6, f"{path}:12:3")])

    def test_multikey_labels_backspace_and_cancel(self):
        paths = [f"/tmp/note-{number}.md" for number in range(10)]
        file_positions = [(row, 0, path) for row, path in enumerate(paths)]
        keys = iter(["a", "\x7f", "s", "a"])
        emitted = []
        # Ten paths require two-letter labels: aa, as, ..., al, sa.
        self.assertEqual(
            hints.select_file(paths, file_positions, 100, 30, lambda: next(keys), emitted.append),
            paths[9],
        )
        self.assertIsNone(
            hints.select_file(paths, file_positions, 100, 30, lambda: "\x1b", emitted.append)
        )
        self.assertIsNone(
            hints.select_file(paths, file_positions, 100, 30, lambda: None, emitted.append)
        )
        self.assertIsNone(hints.select_file(paths, [], 100, 30, lambda: "a", emitted.append))


@unittest.skipUnless(shutil.which("tmux") and shutil.which("nvim"), "requires tmux and Neovim")
class OverlayTest(unittest.TestCase):
    def test_colors_positions_cancel_and_open(self):
        # An outer tmux pane is the terminal emulator for an attached inner client.
        # Unlike capture-pane on the source, this captures the rendered popup too.
        display_server = ["tmux", "-L", f"hints-display-test-{os.getpid()}"]
        hint_server = ["tmux", "-L", f"hints-inner-test-{os.getpid()}"]
        env = {**os.environ, "TERM": "xterm-256color"}
        env.pop("TMUX", None)
        env.pop("TMUX_PANE", None)

        def run(server, *args):
            return subprocess.check_output([*server, *args], env=env, text=True).removesuffix("\n")

        def wait(check):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                result = check()
                if result:
                    return result
                time.sleep(0.05)
            self.fail("Timed out waiting for tmux")

        def plain(text):
            return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)

        try:
            with tempfile.TemporaryDirectory() as cwd:
                path = Path(cwd) / "a-long-design-document-directory" / "design.md"
                path.parent.mkdir()
                path.write_text("# Real hint test\n\nThird line.\n")
                run(
                    hint_server, "-f", "/dev/null", "new-session", "-d",
                    "-x", "110", "-y", "31", "sleep 120",
                )
                run(hint_server, "set-option", "-g", "status-position", "top")
                run(hint_server, "set-option", "-g", "status-right", "fixture")
                run(hint_server, "set-window-option", "automatic-rename", "off")
                run(hint_server, "rename-window", "fixture")
                run(hint_server, "set-option", "-g", "pane-border-status", "top")
                right_pane = run(
                    hint_server, "split-window", "-h", "-P", "-F", "#{pane_id}", "sleep 120"
                )
                source_pane = run(
                    hint_server, "split-window", "-v", "-t", right_pane,
                    "-P", "-F", "#{pane_id}", "sleep 120",
                )
                text = (
                    "\x1b[2J\x1b[H\x1b[38;2;12;34;56mCOLOR PRESERVED\x1b[0m\r\n"
                    f"\r\nRead `{path}:3`\r\n\r\nBOTTOM MARKER"
                )
                code = f"import sys,time;sys.stdout.write({text!r});sys.stdout.flush();time.sleep(120)"
                run(
                    hint_server, "respawn-pane", "-k", "-t", source_pane,
                    shlex.join(["python3", "-c", code]),
                )
                launcher = shlex.join(["python3", str(Path(hints.__file__).resolve()), source_pane])
                run(hint_server, "bind-key", "e", "run-shell", "-b", launcher)
                attach = shlex.join(["env", "-u", "TMUX", *hint_server, "attach-session"])
                display_pane = run(
                    display_server, "-f", "/dev/null", "new-session", "-d",
                    "-x", "110", "-y", "32", "-P", "-F", "#{pane_id}", attach,
                )
                run(display_server, "set-option", "-g", "status", "off")

                def capture():
                    return run(display_server, "capture-pane", "-p", "-e", "-N", "-t", display_pane)

                def hinted_capture():
                    text = capture()
                    return text if "Read `a" in plain(text) else None

                wait(lambda: "BOTTOM MARKER" in capture())
                before = capture()
                run(display_server, "send-keys", "-t", display_pane, "C-b", "e")
                after = wait(hinted_capture)
                original_rows, hint_rows = plain(before).splitlines(), plain(after).splitlines()
                self.assertEqual(len(original_rows), len(hint_rows))
                changed_rows = [
                    (original, hinted)
                    for original, hinted in zip(original_rows, hint_rows)
                    if original != hinted
                ]
                self.assertEqual(len(changed_rows), 1)
                original, hinted = changed_rows[0]
                column = original.index("Read `") + len("Read `")
                self.assertEqual(original[:column] + "a" + original[column + 1:], hinted)
                original_color = next(row for row in before.splitlines() if "COLOR PRESERVED" in row)
                hint_color = next(row for row in after.splitlines() if "COLOR PRESERVED" in row)
                self.assertEqual(original_color, hint_color)
                self.assertIn("38;2;12;34;56", hint_color)

                run(display_server, "send-keys", "-t", display_pane, "Escape")
                wait(lambda: plain(capture()) == plain(before))
                restored = capture()
                self.assertEqual(restored.splitlines(), before.splitlines())
                self.assertEqual(len(run(hint_server, "list-panes").splitlines()), 3)

                # Explicit pane defaults must survive too, not just terminal defaults.
                run(
                    hint_server, "set-option", "-p", "-t", source_pane,
                    "window-style", "fg=#234567,bg=#fdf6e3",
                )
                wait(lambda: "48;2;253;246;227" in capture())
                before = capture()
                run(display_server, "send-keys", "-t", display_pane, "C-b", "e")
                after = wait(hinted_capture)
                original_color = next(row for row in before.splitlines() if "COLOR PRESERVED" in row)
                hint_color = next(row for row in after.splitlines() if "COLOR PRESERVED" in row)
                self.assertEqual(original_color, hint_color)

                run(display_server, "send-keys", "-t", display_pane, "a")
                wait(lambda: len(run(hint_server, "list-panes").splitlines()) == 4)
                editor_pane = run(hint_server, "list-panes", "-F", "#{pane_id}").splitlines()[-1]
                wait(lambda: "Real hint test" in run(
                    hint_server, "capture-pane", "-p", "-t", editor_pane,
                ))
        finally:
            for server in (display_server, hint_server):
                subprocess.run(
                    [*server, "kill-server"], env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )


if __name__ == "__main__":
    unittest.main()
