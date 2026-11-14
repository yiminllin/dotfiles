#!/usr/bin/env python3
"""Offline Agent Board grid and isolated tmux slot checks."""

from contextlib import contextmanager
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "tmux/.tmux/pi-agent-board.py"
spec = importlib.util.spec_from_file_location("pi_agent_board", SOURCE)
board = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = board
spec.loader.exec_module(board)
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def agent(slot, **changes):
    values = dict(pane=f"%{slot}", session="$0", window="@0", slot=slot,
                  name=f"Named agent {slot}", state="RUN", dimmed=False,
                  pin=[f"Goal {slot}", "✓ Inspect", "▶ Implement", "  ▶ Current task", "○ Verify"])
    return board.Agent(**(values | changes))


@contextmanager
def isolated_tmux():
    base = ["tmux", "-L", f"pi-board-test-{os.getpid()}"]

    def tmux(*args):
        return subprocess.check_output(base + list(args), text=True, stderr=subprocess.DEVNULL).rstrip("\n")

    with tempfile.TemporaryDirectory(prefix="pi-board-test-") as directory:
        command = Path(directory) / "pi"
        command.write_text("#!/bin/sh\nexec sleep 300\n")
        command.chmod(0o755)
        tmux("-f", "/dev/null", "new-session", "-d", "-s", "test", "-x", "160", "-y", "35", str(command))
        try:
            yield tmux, base, str(command)
        finally:
            subprocess.run(base + ["kill-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class GridTests(unittest.TestCase):
    def test_equal_blocks_fill_four_columns_then_rows(self):
        for count in (1, 4, 5, 8, 9, 12):
            agents = [agent(i) for i in range(1, count + 1)]
            agents[0].pin.append("! Blocked: Input")
            agents[-1].pin += ["An extra long milestone that needs wrapping " * 3]
            lines, height = board.render_grid(agents, 126, 1, "@0")
            plain = [ANSI.sub("", line) for line in lines]
            self.assertEqual(len(lines), ((count + 3) // 4) * height)
            self.assertEqual({board.width(line) for line in plain}, {126})
            for i in range(1, count + 1):
                row, column = divmod(i - 1, 4)
                self.assertTrue(plain[row * height + 1][column * 32:].startswith(f"┃ [{i}] RUN Named agent {i}"))
                self.assertTrue(plain[row * height][column * 32:].startswith("┏"))
                self.assertIn("▶ Current task", "\n".join(plain[row * height:row * height + height]))
            self.assertIn("\x1b[1;7m[1]", lines[1])
            self.assertIn("\x1b[1;38;5;235;48;2;238;220;182;4m", lines[1])
            self.assertIn("\x1b[1;4;38;5;24mGoal 1", lines[3])
            for code, text in (("32", "✓ Inspect"), ("33", "▶ Implement"), ("90", "○ Verify"), ("31", "! Blocked: Input")):
                self.assertIn(f"\x1b[{code}m{text}", "\n".join(lines))
            self.assertIn("┗", plain[height - 2])

    def test_popup_height_fits_grid_rows_and_caps_long_content(self):
        one = [agent(i) for i in range(1, 5)]
        two = [agent(i) for i in range(1, 9)]
        one_width, one_height = board.popup_size(one, 160, 57)
        two_width, two_height = board.popup_size(two, 160, 57)
        self.assertEqual(one_width, two_width)
        self.assertEqual(one_height, 13)
        self.assertEqual(two_height, 23)
        self.assertLess(two_height, int(57 * 0.85))
        two[-1].pin *= 30
        self.assertEqual(board.popup_size(two, 160, 57)[1], int(57 * 0.85))

    def test_unicode_width_wrapping_and_dimmed_selection(self):
        self.assertEqual(board.width("检查 e\u0301 👩‍💻 👋🏽 🇺🇸"), 15)
        for columns in (54, 80, 121, 180):
            lines, _ = board.render_grid([agent(1, name="检查 👩‍💻 long title", dimmed=True)], columns, 1, "@0")
            self.assertTrue(all(board.width(ANSI.sub("", line)) <= columns for line in lines))
            self.assertIn("\x1b[1;7m[1]", lines[1])
            self.assertNotIn("\x1b[1;31m", "\n".join(lines))
            self.assertNotIn("\x1b[1;4;38;5;24m", "\n".join(lines))
            self.assertNotIn("48;2;238;220;182", "\n".join(lines))
            for code in ("32", "33", "31"):
                self.assertNotIn(f"\x1b[{code}m", "\n".join(lines))
        self.assertTrue(all(board.width(line) <= 8 for line in board.wrap("检查 👩‍💻 e\u0301 " * 8, 8)))
        self.assertTrue(board.wrap("  ▶ Nested task", 12)[0].startswith("  ▶"))
        self.assertNotIn("\x1b", "".join(board.wrap("bad\x1b[31m title", 12)))

    def test_missing_and_full_pins_are_distinct(self):
        self.assertEqual(board.pin_lines(json.dumps({"pid": os.getpid(), "plan": None})), ["No pinned progress"])
        for raw in ("", "broken", json.dumps({"pid": 999999999, "plan": None})):
            self.assertIn("Progress unavailable", board.pin_lines(raw))
        plan = {"goal": "Full plan", "milestones": [
            {"label": "One", "status": "done", "tasks": [{"label": "Hidden", "status": "done"}]},
            {"label": "Two", "status": "current", "tasks": [{"label": "Visible", "status": "current"}]},
            {"label": "Three", "status": "pending"},
        ], "blocker": "A decision"}
        lines = board.pin_lines(json.dumps({"pid": os.getpid(), "plan": plan}))
        self.assertEqual(lines, ["Full plan", "✓ One", "▶ Two", "  ▶ Visible", "○ Three", "! Blocked: A decision"])

    def test_arrow_sequence_does_not_consume_the_next_key(self):
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b"\x1b[CAq")
            with os.fdopen(read_fd) as stream, patch.object(board.sys, "stdin", stream):
                self.assertEqual(board.read_key(), "\x1b[C")
                self.assertEqual(board.read_key(), "A")
                self.assertEqual(board.read_key(), "q")
        finally:
            os.close(write_fd)

    def test_empty_slots_do_not_move_later_blocks(self):
        lines, height = board.render_grid([agent(1), agent(4), agent(5)], 126, 1, "@0")
        self.assertIn("[4]", ANSI.sub("", lines[1])[96:])
        self.assertTrue(ANSI.sub("", lines[height + 1]).startswith("┃ [5]"))


class SlotTests(unittest.TestCase):
    def test_actual_binding_highlights_non_first_agent_in_one_and_two_rows(self):
        binding = shlex.split(next(line for line in (SOURCE.parent.parent / ".tmux.conf").read_text().splitlines()
                                  if line.startswith("bind-key a ")))
        client = None
        fd = None
        try:
            with isolated_tmux() as (tmux, base, command):
                first = tmux("display-message", "-p", "#{pane_id}")
                original_pid = int(tmux("display-message", "-p", "#{pane_pid}"))
                panes = [first]
                for _ in range(2):
                    panes.append(tmux("new-window", "-d", "-P", "-F", "#{pane_id}", str(command)))
                tmux(*binding)
                tmux("select-window", "-t", "test:2")
                client, fd = pty.fork()
                if client == 0:
                    os.environ["TERM"] = "xterm-256color"
                    os.environ["TMUX_PANE"] = first
                    os.execvp("tmux", base + ["attach", "-t", "test"])
                fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 35, 160, 0, 0))
                def drain(seconds):
                    output, end = b"", time.monotonic() + seconds
                    while time.monotonic() < end:
                        if select.select([fd], [], [], 0.05)[0]:
                            output += os.read(fd, 65536)
                    return output
                drain(0.3)
                for count in (3, 5):
                    while len(panes) < count:
                        panes.append(tmux("new-window", "-d", "-P", "-F", "#{pane_id}", str(command)))
                    target = panes[-1]
                    window = tmux("display-message", "-p", "-t", target, "#{window_id}")
                    tmux("select-window", "-t", window)
                    os.write(fd, b"\x02a")
                    self.assertIn(b"Progress unavailable", drain(1.0))
                    os.write(fd, b"A")
                    drain(0.4)
                    self.assertEqual(tmux("show-options", "-pqv", "-t", target, "@pi_agent_dimmed"), "1")
                    self.assertEqual(tmux("show-options", "-pqv", "-t", first, "@pi_agent_dimmed"), "")
                    os.write(fd, b"q")
                    drain(0.2)
                    os.kill(original_pid, 0)
        finally:
            if client:
                os.waitpid(client, 0)
            if fd is not None:
                os.close(fd)

    def test_status_dimming_removal_and_new_agents_preserve_slots(self):
        with isolated_tmux() as (tmux, _base, command):
            first = tmux("display-message", "-p", "#{pane_id}")
            second = tmux("new-window", "-d", "-P", "-F", "#{pane_id}", command)
            third = tmux("new-window", "-d", "-P", "-F", "#{pane_id}", command)
            with patch.object(board, "tmux", tmux):
                original = {a.pane: a.slot for a in board.collect_agents()}
                self.assertEqual(list(original.values()), [1, 2, 3])
                tmux("set-option", "-pt", third, "@pi_agent_input_wait", str(os.getpid()))
                tmux("set-option", "-pt", second, "@pi_agent_dimmed", "1")
                self.assertEqual({a.pane: a.slot for a in board.collect_agents()}, original)
                tmux("kill-pane", "-t", first)
                remaining = {a.pane: a.slot for a in board.collect_agents()}
                self.assertEqual(remaining, {second: 2, third: 3})
                added = tmux("new-window", "-d", "-P", "-F", "#{pane_id}", command)
                self.assertEqual({a.pane: a.slot for a in board.collect_agents()}, {added: 1, second: 2, third: 3})


if __name__ == "__main__":
    unittest.main()
