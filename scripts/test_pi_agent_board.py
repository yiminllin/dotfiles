#!/usr/bin/env python3
"""Offline Agent Board grid and isolated tmux slot checks."""

from contextlib import contextmanager
import fcntl
import importlib.util
import io
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


class StatusTests(unittest.TestCase):
    def test_direct_launch_uses_live_extension_status(self):
        pane = dict.fromkeys(board.FIELDS, "")
        pane.update({"pane_id": "%1", "@pi_session_owner": str(os.getpid())})
        with patch.object(board, "tmux", return_value="────") as capture:
            for state in ("WAIT", "RUN", "WAIT"):
                pane["@pi_agent_run_state"] = state
                self.assertEqual(board.agent_state(pane), state)
            pane["@pi_agent_input_wait"] = str(os.getpid())
            self.assertEqual(board.agent_state(pane), "BLOCKED")
            capture.assert_not_called()
            pane.update({"@pi_agent_input_wait": "", "@pi_session_owner": "", "@pi_agent_run_state": "RUN"})
            self.assertEqual(board.agent_state(pane), "WAIT")
            capture.assert_called_once_with("capture-pane", "-p", "-t", "%1")


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
            for code, text in (("1;32", "✓ Inspect"), ("1;33", "▶ Implement"), ("1;90", "○ Verify"), ("31", "! Blocked: Input")):
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
            for code in ("1;32", "1;33", "1;90", "31"):
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

    def test_selection_follows_session_when_slots_compact(self):
        snapshots = [
            [agent(1), agent(2), agent(3)],
            [agent(1, pane="%2"), agent(2, pane="%3")],
            [agent(1, pane="%2"), agent(2, pane="%3")],
        ]
        with patch.dict(os.environ, TMUX_PANE="%3"), \
                patch.object(board, "context", return_value=("client", "@0")), \
                patch.object(board, "collect_agents", side_effect=snapshots), \
                patch.object(board, "read_key", side_effect=["", "A", "q"]), \
                patch.object(board, "render_grid", return_value=([], 1)) as render, \
                patch.object(board, "tmux") as tmux, \
                patch.object(board.os, "get_terminal_size", return_value=(126, 35)), \
                patch.object(board.signal, "signal"), \
                patch.object(board.sys, "stdin", io.StringIO()), \
                tempfile.TemporaryFile(mode="w+") as output, \
                patch.object(board.sys, "stdout", output):
            board.main()
        self.assertEqual([call.args[2] for call in render.call_args_list], [3, 2, 2])
        tmux.assert_called_once_with("set-option", "-pt", "%3", "@pi_agent_dimmed", "1")

    def test_empty_slots_do_not_move_later_blocks(self):
        lines, height = board.render_grid([agent(1), agent(4), agent(5)], 126, 1, "@0")
        self.assertIn("[4]", ANSI.sub("", lines[1])[96:])
        self.assertTrue(ANSI.sub("", lines[height + 1]).startswith("┃ [5]"))


class SelectionTests(unittest.TestCase):
    def test_selection_returns_identity_without_jumping_or_dimming(self):
        class TerminalOutput(io.StringIO):
            def fileno(self):
                return 2

        for session_id, owner, expected in [
            ("pi-session", str(os.getpid()), {"session_id": "pi-session", "worktree": "/work/tree", "name": "Existing agent"}),
            ("", str(os.getpid()), None),
            ("pi-session", "999999999", None),
        ]:
            output, stdout = TerminalOutput(), io.StringIO()
            selected = agent(12, name="Existing agent", pi_id=session_id, worktree="/work/tree", owner=owner)
            keys = ["A", "g", "1", "2", "\r"] + (["\x1b"] if expected is None else [])
            with patch.dict(os.environ, TMUX_PANE="%1"), \
                 patch.object(board, "context", return_value=("client", "@0")), \
                 patch.object(board, "collect_agents", return_value=[selected]), \
                 patch.object(board, "read_key", side_effect=keys), \
                 patch.object(board, "jump") as jump, patch.object(board, "tmux") as tmux, \
                 patch.object(board.signal, "signal"), \
                 patch.object(board.os, "get_terminal_size", return_value=os.terminal_size((120, 30))), \
                 patch.object(sys, "stdin", io.StringIO()), \
                 patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", output):
                self.assertEqual(board.main(select_session=True), expected)
                jump.assert_not_called()
                tmux.assert_not_called()
            self.assertEqual(stdout.getvalue(), "")
            if expected is None:
                self.assertIn("Run /reload", output.getvalue())


class SlotTests(unittest.TestCase):
    def test_actual_popup_highlights_source_and_jumps_to_numbered_slots(self):
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
                tmux("set-option", "-s", "escape-time", "0")
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
                for count in (3, 5, 8):
                    while len(panes) < count:
                        panes.append(tmux("new-window", "-d", "-P", "-F", "#{pane_id}", str(command)))
                    target = panes[4] if count == 8 else panes[-1]
                    tmux("set-option", "-pt", target, "-u", "@pi_agent_dimmed")
                    window = tmux("display-message", "-p", "-t", target, "#{window_id}")
                    tmux("select-window", "-t", window)
                    if count == 8:
                        # Opening from a sibling shell must select this window's Pi.
                        shell = tmux("split-window", "-t", target, "-P", "-F", "#{pane_id}", "sleep 300")
                        tmux("select-pane", "-t", shell)
                    os.write(fd, b"\x02a")
                    self.assertIn(b"Progress unavailable", drain(1.0))
                    os.write(fd, b"A")
                    drain(0.4)
                    self.assertEqual(tmux("show-options", "-pqv", "-t", target, "@pi_agent_dimmed"), "1")
                    self.assertEqual(tmux("show-options", "-pqv", "-t", first, "@pi_agent_dimmed"), "")
                    os.write(fd, b"q")
                    drain(0.2)
                    os.kill(original_pid, 0)

                while len(panes) < 12:
                    panes.append(tmux("new-window", "-d", "-P", "-F", "#{pane_id}", command))
                os.write(fd, b"\x02a")
                self.assertIn(b"g slot Enter", drain(1.0))
                os.write(fd, b"g99\r")
                self.assertIn(b"No agent in slot 99", drain(0.4))
                os.write(fd, b"g1")
                self.assertIn(b"Jump to slot: 1", drain(0.4))
                os.write(fd, b"\x1b")
                self.assertIn(b"g slot Enter", drain(1.2))
                os.write(fd, b"g19\x7f0\r")
                drain(0.4)
                self.assertEqual(tmux("display-message", "-p", "#{pane_id}"), panes[9])
                os.write(fd, b"\x02a")
                self.assertIn(b"g slot Enter", drain(1.0))
                os.write(fd, b"9")
                drain(0.4)
                self.assertEqual(tmux("display-message", "-p", "#{pane_id}"), panes[8])
                os.kill(original_pid, 0)
        finally:
            if client:
                os.waitpid(client, 0)
            if fd is not None:
                os.close(fd)

    def test_idle_agent_auto_dims_and_can_be_restored(self):
        with isolated_tmux() as (tmux, _base, _command):
            pane = tmux("display-message", "-p", "#{pane_id}")
            now = 1700000000
            old = str(now * 1000 - board.STALE_AFTER_MS - 1)
            with patch.object(board, "tmux", tmux), \
                    patch.object(board.time, "time", return_value=now), \
                    patch.object(board, "agent_state", return_value="WAIT") as state:
                def dimmed():
                    return board.collect_agents()[0].dimmed

                tmux("set-option", "-pt", pane, "@pi_agent_last_message", old)
                self.assertFalse(dimmed(), "An unowned timestamp is ignored")
                tmux("set-option", "-pt", pane, "@pi_session_owner", str(os.getpid()))
                self.assertTrue(dimmed())
                for status in ("RUN", "BLOCKED", "ERR"):
                    state.return_value = status
                    self.assertFalse(dimmed(), status)
                state.return_value = "WAIT"
                board.toggle_pane_dim(pane)
                self.assertFalse(dimmed())
                board.toggle_pane_dim(pane)
                self.assertTrue(dimmed())
                board.toggle_pane_dim(pane)
                tmux("set-option", "-pt", pane, "@pi_agent_last_message", str(int(old) - 1))
                self.assertTrue(dimmed(), "A bright override does not carry over to another timestamp")
                tmux("set-option", "-pt", pane, "@pi_agent_last_message", str(int(old) + 1))
                self.assertFalse(dimmed(), "Exactly 24 hours old is not stale")
                board.toggle_pane_dim(pane)
                self.assertTrue(dimmed(), "Manual dimming still works on fresh conversations")

    def test_status_and_dimming_preserve_order_but_removal_compacts_slots(self):
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
                self.assertEqual(remaining, {second: 1, third: 2})
                self.assertEqual(tmux("show-options", "-pqv", "-t", third, "@pi_agent_slot"), "2")
                added = tmux("new-window", "-d", "-P", "-F", "#{pane_id}", command)
                self.assertEqual({a.pane: a.slot for a in board.collect_agents()}, {second: 1, third: 2, added: 3})
                tmux("kill-pane", "-t", third)
                self.assertEqual({a.pane: a.slot for a in board.collect_agents()}, {second: 1, added: 2})


if __name__ == "__main__":
    unittest.main()
