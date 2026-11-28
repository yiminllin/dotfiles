#!/usr/bin/env python3
"""Exercise task-agent controls inside the real td tmux popup, without model calls."""

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
import uuid
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "td/target/debug/td"
FINDER = ROOT / "tmux/.tmux/tmux-session-finder"
SESSIONIZER = ROOT / "tmux/.tmux/tmux-sessionizer"


@unittest.skipUnless(shutil.which("tmux") and shutil.which("fzf") and BINARY.exists(),
                     "requires tmux, fzf, and cargo build --manifest-path td/Cargo.toml")
class AgentPopupTests(unittest.TestCase):
    def test_task_linked_agent_lifecycle(self):
        base = ["tmux", "-L", f"td-popup-test-{os.getpid()}"]
        client = fd = None
        with tempfile.TemporaryDirectory(prefix="td-popup-test-") as directory:
            root = Path(directory)
            home, bindir, worktree = (root / name for name in ("home", "bin", "chosen-worktree"))
            events, launch = root / "events.jsonl", root / "launch"
            for path in (home, bindir, worktree, home / ".tmux"):
                path.mkdir()
            (home / ".tmux/tmux-session-finder").symlink_to(FINDER)
            (home / ".tmux/tmux-sessionizer").symlink_to(SESSIONIZER)
            for name in ("pi-agent-board", "pi-agent-board.py"):
                (home / ".tmux" / name).symlink_to(ROOT / "tmux/.tmux" / name)
            scripts = {
                "fd": "printf '/work/repo/.git\\n'",
                "git": "printf 'worktree %s\\n' " + shlex.quote(str(worktree)),
                "gh": "exit 1",
                "fish": 'printf "%s\\n" "$@" > ' + shlex.quote(str(root / "review-call"))
                        + '; exec pi --session-id "$TD_PI_SESSION_ID" --name "$TD_PI_AGENT_NAME"',
                "pi": 'printf "%s\\n" "$@" > ' + shlex.quote(str(launch))
                      + '; tmux set-option -pt "$TMUX_PANE" @pi_session_id "$2"'
                      + '; tmux set-option -pt "$TMUX_PANE" @pi_agent_name "$4"'
                      + '; tmux set-option -pt "$TMUX_PANE" @pi_session_owner "$$"'
                      + '; tmux set-option -pt "$TMUX_PANE" @pi_session_cwd "$PWD"'
                      + '; if test -n "$TD_PI_SESSION_ID"; then tmux set-option -pt "$TMUX_PANE" @pi_review_repo "$PWD"; fi; sleep 60',
            }
            for name, script in scripts.items():
                path = bindir / name
                path.write_text("#!/bin/sh\n" + script + "\n")
                path.chmod(0o755)
            env = {**os.environ, "HOME": str(home), "PATH": f"{bindir}:{os.environ['PATH']}"}
            for key in ("TMUX", "TMUX_PANE", "FZF_DEFAULT_OPTS", "FZF_DEFAULT_OPTS_FILE"):
                env.pop(key, None)

            def tmux(*args):
                return subprocess.check_output(base + list(args), env=env, text=True).strip()

            task = subprocess.check_output(
                [str(BINARY), "--events", str(events), "add", "Review a very long PR title for agent naming", "--project", "work"],
                env=env, text=True,
            ).strip()
            with events.open("a") as stream:
                stream.write(json.dumps({
                    "schema_version": 1, "event_id": str(uuid.uuid4()), "task_id": task,
                    "at": "2026-11-15T00:00:00Z", "source": "test",
                    "event": {"type": "task_updated", "work": {
                        "category": "review", "prs": "https://github.com/example/example/pull/123",
                    }},
                }) + "\n")
            chunks = []

            def drain(seconds):
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    if select.select([fd], [], [], .04)[0]:
                        data = os.read(fd, 65536)
                        chunks.append(data)
                        if b"\x1b[6n" in data:
                            os.write(fd, b"\x1b[1;1R")

            def wait_for(text):
                end = time.monotonic() + 8
                while time.monotonic() < end:
                    drain(.1)
                    data = b"".join(chunks)
                    if (text.search(data) if isinstance(text, re.Pattern) else text in data):
                        return
                self.fail(f"Not rendered: {text!r}; terminal tail: {b''.join(chunks)[-400:]!r}")

            def wait_for_agent(active):
                color, icon = (b"75;105;77", "●") if active else (b"150;105;40", "○")
                wait_for(re.compile(rb"\x1b\[38;2;" + color + rb"m(?:\x1b\[[0-9;]*m)*" + icon.encode() + rb"(?= |\x1b)"))

            def wait_for_settings():
                tmux("refresh-client")  # Unchanged popup cells may not be sent again.
                wait_for(b"Save settings")

            def wait_for_dashboard():
                drain(.15)  # Let a standalone Esc resolve before reading the dashboard behind a popup.
                tmux("refresh-client")
                wait_for(b"Pending")

            def send(keys):
                chunks.clear()
                os.write(fd, keys)

            try:
                tmux("-f", "/dev/null", "new-session", "-d", "-s", "test")
                tmux("set-option", "-g", "default-shell", "/bin/bash")
                tmux("set-option", "-s", "escape-time", "0")
                client, fd = pty.fork()
                if client == 0:
                    os.environ.pop("TMUX", None)
                    os.environ["TERM"] = "xterm-256color"
                    os.execvp("tmux", base + ["attach", "-t", "test"])
                fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
                drain(.4)
                command = shlex.join(["env", "TD_POPUP=1", f"HOME={home}", f"PATH={env['PATH']}", str(BINARY), "--events", str(events)])

                def open_popup():
                    chunks.clear()
                    return subprocess.Popen(base + ["display-popup", "-E", "-w", "75%", "-h", "65%", command], env=env)

                popup = open_popup()
                wait_for_dashboard()
                send(b"pw")
                wait_for_dashboard()
                wait_for(b"Agent")
                send(b"c")
                wait_for(b"review-123")
                self.assertNotIn(b"Session Finder", b"".join(chunks), "first c must not open a picker")
                self.assertFalse(launch.exists())
                send(b"\r")  # Worktree picker is opt-in.
                wait_for(b"chosen-worktree")
                send(b"chosen-worktree\r")
                wait_for(b"review-123")
                self.assertFalse(launch.exists())
                send(b"\x10")  # Ctrl-P from the agent form, not the underlying shell.
                wait_for(b"Session Finder")
                send(b"\x1b")
                wait_for_settings()
                send(b"\x1b[Z\r")  # BackTab to Worktree, then Enter to browse.
                wait_for(b"Session Finder")
                send(b"\x1b")
                wait_for_settings()
                send(b"\t\r")  # Continue from Name to Save settings.
                drain(.2)
                self.assertFalse(launch.exists())
                send(b"\r")
                wait_for_dashboard()
                wait_for_agent(False)
                self.assertIsNone(popup.poll(), "saving settings must keep td open")
                self.assertFalse(launch.exists(), "saving settings must not launch Pi")
                send(b"c")
                end = time.monotonic() + 5
                while not launch.exists() and time.monotonic() < end:
                    drain(.1)
                self.assertTrue(launch.exists())
                arguments = launch.read_text().splitlines()
                self.assertEqual(arguments[::2], ["--session-id", "--name"])
                self.assertEqual(arguments[3], "review-123")
                self.assertEqual((root / "review-call").read_text().splitlines(),
                                 ["-c", "review $argv[1]", "--", "https://github.com/example/example/pull/123"])
                self.assertEqual(popup.wait(timeout=5), 0)
                agent_pane = tmux("display-message", "-p", "#{pane_id}")
                self.assertEqual(tmux("display-message", "-p", "#{session_name}"), worktree.name)
                self.assertEqual(tmux("show-option", "-qv", "@workspace_path"), str(worktree))

                popup = open_popup()
                wait_for_dashboard()
                send(b"pw")
                wait_for_agent(True)
                send(b"c")
                self.assertEqual(popup.wait(timeout=5), 0)
                self.assertEqual(tmux("display-message", "-p", "#{pane_id}"), agent_pane)
                self.assertEqual(launch.read_text().splitlines(), arguments)

                popup = open_popup()
                wait_for_dashboard()
                send(b"pw")
                wait_for_agent(True)
                chunks.clear()
                tmux("kill-pane", "-t", agent_pane)
                wait_for_agent(False)
                send(b"c")
                self.assertEqual(popup.wait(timeout=5), 0)
                self.assertEqual(launch.read_text().splitlines(), arguments)
                owned_pane = tmux("display-message", "-p", "#{pane_id}")
                owned_window = tmux("display-message", "-pt", owned_pane, "#{window_id}")

                external = root / "external-worktree"
                external.mkdir()
                target = tmux("new-window", "-d", "-P", "-F", "#{pane_id}", "-c", str(external),
                              "pi", "--session-id", "external-session", "--name", "external")
                end = time.monotonic() + 5
                while tmux("show-option", "-pqv", "-t", target, "@pi_session_id") != "external-session" and time.monotonic() < end:
                    drain(.1)
                sibling = tmux("split-window", "-d", "-P", "-F", "#{pane_id}", "-t", target, "sleep 60")
                target_pid = tmux("display-message", "-pt", target, "#{pane_pid}")
                current_pane = tmux("display-message", "-p", "#{pane_id}")
                before_launch = launch.read_text()
                before_events = events.read_bytes()
                board_spec = importlib.util.spec_from_file_location("td_popup_board", ROOT / "tmux/.tmux/pi-agent-board.py")
                board = importlib.util.module_from_spec(board_spec)
                sys.modules[board_spec.name] = board
                board_spec.loader.exec_module(board)
                with patch.object(board, "tmux", tmux):
                    slot = next(agent.slot for agent in board.collect_agents() if agent.pi_id == "external-session")
                popup = open_popup()
                wait_for_dashboard()
                send(b"pw")
                wait_for_dashboard()
                send(b"C")
                wait_for_settings()
                send(b"\t\t\r")  # Session ID opens the Board, not Pi.
                wait_for(b"Enter link")
                send(b"\x1b")
                wait_for_settings()
                self.assertEqual(events.read_bytes(), before_events)
                send(b"\r")
                wait_for(b"Enter link")
                send(str(slot).encode())
                wait_for_settings()
                self.assertIsNone(popup.poll(), "linking must stay in td, not jump")
                self.assertEqual(tmux("display-message", "-p", "#{pane_id}"), current_pane)
                saved = json.loads(subprocess.check_output(
                    [str(BINARY), "--events", str(events), "show", task], env=env, text=True,
                ))["agent"]
                self.assertEqual(saved, {"session_id": "external-session", "worktree": str(external), "name": "external"})
                self.assertEqual(launch.read_text(), before_launch, "linking must not launch Pi")
                self.assertEqual(tmux("display-message", "-pt", target, "#{pane_pid}"), target_pid)
                send(b"dd")
                wait_for(b"New session")
                self.assertIsNone(popup.poll(), "unlinking must stay in td")
                unlinked = json.loads(subprocess.check_output(
                    [str(BINARY), "--events", str(events), "show", task], env=env, text=True,
                ))
                self.assertIsNone(unlinked["agent"])
                self.assertEqual(tmux("display-message", "-pt", target, "#{pane_pid}"), target_pid)
                self.assertEqual(launch.read_text(), before_launch, "unlinking must not launch or stop Pi")
                send(b"\r")
                wait_for(b"Enter link")
                send(str(slot).encode())
                wait_for_settings()
                relinked = json.loads(subprocess.check_output(
                    [str(BINARY), "--events", str(events), "show", task], env=env, text=True,
                ))["agent"]
                self.assertEqual(relinked, saved)
                send(b"\t\r")  # Save settings and return to the dashboard.
                wait_for_dashboard()
                send(b"c")
                end = time.monotonic() + 5
                while popup.poll() is None and time.monotonic() < end:
                    drain(.1)
                self.assertEqual(popup.poll(), 0, b"".join(chunks)[-2000:])
                self.assertEqual(tmux("display-message", "-p", "#{pane_id}"), target)
                self.assertEqual(tmux("display-message", "-pt", target, "#{pane_pid}"), target_pid)

                def task_data():
                    return json.loads(subprocess.check_output(
                        [str(BINARY), "--events", str(events), "show", task], env=env, text=True,
                    ))

                def finish_from_popup(expected_target):
                    nonlocal popup
                    popup = open_popup()
                    wait_for_dashboard()
                    send(b"pw")
                    wait_for_dashboard()
                    before = events.read_bytes()
                    send(b"sd")
                    wait_for(b"Complete item and close agent?")
                    wait_for(expected_target)
                    send(b"n")
                    wait_for_dashboard()
                    self.assertEqual(events.read_bytes(), before, "cancel must not complete the item")
                    send(b"sd")
                    drain(.2)
                    tmux("refresh-client")
                    wait_for(b"y complete and close")
                    send(b"y")
                    end = time.monotonic() + 5
                    while task_data()["status"] != "completed" and time.monotonic() < end:
                        drain(.1)
                    self.assertEqual(task_data()["status"], "completed")
                    if popup.poll() is None:
                        send(b"q")
                    popup.wait(timeout=5)

                finish_from_popup(b"Pi pane")
                remaining = tmux("list-panes", "-a", "-F", "#{pane_id}").splitlines()
                self.assertNotIn(target, remaining)
                self.assertIn(sibling, remaining, "an imported session must not close other panes")
                subprocess.check_call([str(BINARY), "--events", str(events), "agent", task,
                    "--worktree", str(worktree), "--session", arguments[1], "--name", "review-123", "--link-only"], env=env)
                tmux("switch-client", "-t", owned_window)
                editor = tmux("split-window", "-d", "-P", "-F", "#{pane_id}", "-t", owned_pane, "sleep 60")
                popup = open_popup()
                wait_for_dashboard()
                send(b"pw")
                wait_for_dashboard()
                send(b"ss")
                drain(.2)
                send(b"q")
                popup.wait(timeout=5)
                self.assertEqual(task_data()["status"], "pending")
                finish_from_popup(b"tmux window")
                self.assertNotIn(owned_window, tmux("list-windows", "-a", "-F", "#{window_id}").splitlines())
                self.assertNotIn(editor, tmux("list-panes", "-a", "-F", "#{pane_id}").splitlines())
                self.assertEqual(task_data()["agent"]["session_id"], arguments[1], "Done must preserve session history linkage")
            finally:
                subprocess.run(base + ["kill-server"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if fd is not None:
                    os.close(fd)
                if client:
                    os.waitpid(client, 0)
                if "popup" in locals():
                    popup.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
