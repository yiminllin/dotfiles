"""Offline launcher checks: python3 fish/.config/fish/tests/review_cli.py."""
import ast
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "fish/.config/fish/functions/review.fish"
BASE, HEAD = "a" * 40, "b" * 40
STUB = '''#!/usr/bin/env python3
import json, os, shutil, sys
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as out:
    out.write(json.dumps([name, *args]) + "\\n")
if name == "git":
    if args[:1] == ["-C"]: args = args[2:]
    if args == ["rev-parse", "--show-toplevel"]: print(os.environ["REVIEW_ROOT"])
    elif args[:2] == ["remote", "get-url"]: print("git@github.com:owner/repo.git")
    elif args == ["branch", "--show-current"]: print("feature/review")
    elif args[:1] == ["merge-base"]: print("a" * 40)
    elif args[:1] == ["rev-parse"]: print("b" * 40)
elif name == "gh":
    print(json.dumps(dict(number=42, title="Review", body="Author's claim", url="https://github.com/owner/repo/pull/42", baseRefName="main", headRefName="feature/review")))
elif name == "git-spice": sys.exit(1)
elif name == "tmux":
    if args[0] == "list-panes": print(os.environ.get("PANES", ""))
    elif args[0] == "show-option": print(os.environ.get("BOUNDARY", ""))
    elif args[0] == "split-window": print("%2")
    elif args[0] == "display-message":
        if args[-1] == "#{window_id}":
            pane = args[args.index("-t") + 1]
            print("@1" if os.environ.get("SAME_WINDOW") or pane != "%9" else "@2")
        elif args[-1] == "#{session_id}": print("$0")
        else: print("%1")
    elif args[0] == "move-pane" and os.environ.get("MOVE_FAIL"): sys.exit(1)
elif name == "pi": sys.exit("Pi must not run synchronously")
elif name == "nvim" and os.environ.get("CHECK_CARGO"): print(shutil.which("cargo"))
'''


class ReviewCLI(unittest.TestCase):
    def setUp(self):
        # SETUP: Stub commands and artifacts are isolated from user sessions and data.
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".pi")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        bin_dir = self.directory / "bin"
        bin_dir.mkdir()
        for command in ("git", "gh", "git-spice", "tmux", "pi", "nvim"):
            script = bin_dir / command
            script.write_text(STUB)
            script.chmod(0o755)
        self.calls = self.directory / "calls.jsonl"
        self.env = dict(os.environ, HOME=str(self.directory),
                        PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                        REVIEW_ROOT=str(ROOT), CALLS=str(self.calls), TMUX="fixture", TMUX_PANE="%1")
        for key in ("TD_PI_SESSION_ID", "TD_PI_AGENT_NAME"):
            self.env.pop(key, None)

    def run_fish(self, command, *args):
        # TEST: Exercise the real Fish function, not a reimplementation.
        result = subprocess.run(["fish", "-c", 'source "$argv[1]"; ' + command,
                                 "--", str(SOURCE), *args], cwd=ROOT, env=self.env,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)  # VERIFY: The requested path completed.
        return result

    def recorded(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def context(self):
        nvim = next(call for call in self.recorded() if call[0] == "nvim")
        match = re.search(r"set_active_guide_context\(vim.json.decode\('((?:\\.|[^'])*)'\)", nvim[1])
        return json.loads(ast.literal_eval("'" + match[1] + "'")), nvim

    def test_local_opens_before_agent_and_pins_boundary(self):
        self.run_fish("review")
        context, nvim = self.context()
        self.assertEqual(context["base_oid"], BASE)
        self.assertEqual(context["head_oid"], HEAD)
        self.assertEqual(context["diffview_rev_arg"], BASE + ".." + HEAD)
        self.assertEqual(context["assistant_name"], "review-feature/review")
        self.assertIn("table.insert(args, 1, '--imply-local=false')", nvim[1])
        self.assertIn("vim.system", nvim[2])
        self.assertIn(str(SOURCE), nvim[2])
        self.assertFalse(any(call[0] in ("pi", "tmux") for call in self.recorded()))
        guide_dir = self.directory / "notes/projects/repo/branch-reviews/feature-review"
        bootstrap = (guide_dir / "assistant-bootstrap.md").read_text()
        self.assertIn(BASE + ".." + HEAD, bootstrap)
        self.assertNotIn("--imply-local", bootstrap)
        self.assertIn("persistent code-centered Diffview contract in references/output-templates.md", bootstrap)
        self.assertIn("code-diagram and core-code-extractor", bootstrap)
        self.assertIn("representative core code changes with source anchors", bootstrap)
        self.assertIn("iterate on this same guide as understanding changes", bootstrap)
        self.assertIn("explicitly authorizes creating and updating", bootstrap)
        self.assertIn(str(guide_dir / "guide.json.tmp"), bootstrap)
        self.assertIn("Do not ask for this permission again", bootstrap)
        self.assertNotIn("Stay within", bootstrap)

    def test_pr_uses_fetched_revision_not_checked_out_branch(self):
        self.run_fish("review 42")
        context, _ = self.context()
        self.assertEqual(context["pr_number"], 42)
        self.assertEqual(context["assistant_name"], "review-42")
        self.assertEqual(context["pr_body"], "Author's claim")
        self.assertTrue(any("+refs/pull/42/head:refs/remotes/origin/pr/42" in call for call in self.recorded()))

    def test_no_agent_needs_no_artifacts(self):
        self.run_fish("review --no-agent")
        context, nvim = self.context()
        self.assertIsNone(context["assistant_name"])
        self.assertNotIn("vim.system", nvim[2])
        self.assertFalse((self.directory / "notes").exists())

    def test_prefers_standard_cargo_only_for_bazel_wrapper(self):
        standard_cargo = self.directory / ".cargo/bin/cargo"
        original_path = self.env["PATH"]
        self.env["CHECK_CARGO"] = "1"
        for cargo_dir, use_standard in (("bazel/tools/bazel_env/bin", True), ("custom/bin", False)):
            with self.subTest(cargo_dir=cargo_dir):
                original_cargo = self.directory / cargo_dir / "cargo"
                for cargo in (original_cargo, standard_cargo):
                    cargo.parent.mkdir(parents=True, exist_ok=True)
                    cargo.write_text("#!/bin/sh\nexit 1\n")
                    cargo.chmod(0o755)
                self.env["PATH"] = str(original_cargo.parent) + os.pathsep + original_path
                result = self.run_fish("review --no-agent; command -s cargo")
                self.assertEqual(result.stdout.splitlines(), [
                    str(standard_cargo if use_standard else original_cargo),
                    str(original_cargo),
                ])

    def test_outside_tmux_opens_without_agent_or_generation(self):
        self.env.pop("TMUX", None)
        result = self.run_fish("review")
        context, nvim = self.context()
        self.assertIsNone(context["assistant_name"])
        self.assertNotIn("vim.system", nvim[2])
        self.assertIn("Diffview only", result.stderr)
        self.assertFalse((self.directory / "notes").exists())

    def test_td_review_preserves_session_identity_and_name(self):
        self.env.update(TD_PI_SESSION_ID="td-session", TD_PI_AGENT_NAME="camera")
        self.run_fish("review 42")
        context, _ = self.context()
        self.assertEqual(context["assistant_name"], "camera")
        self.calls.write_text("")
        self.env["PANES"] = f"%9|camera|{ROOT}|pi|exec pi|{ROOT}|another-session"
        self.run_fish('__review_start_pi $argv[2..-1]', str(ROOT), "camera",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
        calls = self.recorded()
        launch = next(call[-1] for call in calls if "split-window" in call)
        self.assertIn("--session-id 'td-session'", launch)
        self.calls.write_text("")
        self.env.update(PANES=f"%9|camera|{ROOT}|node|pi --session-id td-session|{ROOT}|td-session",
                        BOUNDARY=BASE + ".." + HEAD, SAME_WINDOW="1")
        self.run_fish('__review_start_pi $argv[2..-1]', str(ROOT), "camera",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
        self.assertFalse(any("split-window" in call for call in self.recorded()))

    def test_existing_agent_is_reused_and_refresh_is_explicit(self):
        # SETUP: The running agent already owns this pinned comparison.
        self.env["SAME_WINDOW"] = "1"
        self.env["PANES"] = "%9|review-42|" + str(ROOT) + "|pi|exec pi --name review-42"
        self.env["BOUNDARY"] = BASE + ".." + HEAD
        # TEST: Reconnect without requesting new guidance.
        self.run_fish('__review_start_pi $argv[2..-1]', str(ROOT), "review-42",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
        # VERIFY: Reconnect without restarting, moving or prompting Pi.
        self.assertFalse(any("split-window" in call for call in self.recorded()))
        self.assertIn(["tmux", "send-keys", "-t", "%9", "-l", "/review-service /fixture"], self.recorded())
        self.assertFalse(any("/skill:pr-human-review-guide" in part for call in self.recorded() for part in call))
        self.assertFalse(any("move-pane" in call or "new-window" in call or "select-pane" in call for call in self.recorded()))
        listing = next(call for call in self.recorded() if call[:2] == ["tmux", "list-panes"])
        self.assertEqual(listing[2:6], ["-s", "-t", "%1", "-F"])
        # TEST: Request a refresh and inspect only its calls.
        self.calls.write_text("")
        self.run_fish('__review_start_pi $argv[2..-1]', str(ROOT), "review-42",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "1")
        # VERIFY: Refresh sends the guide prompt, not just the service command.
        self.assertTrue(any("/skill:pr-human-review-guide" in part for call in self.recorded() for part in call))
        self.assertFalse(any("split-window" in call for call in self.recorded()))

    def test_reuse_from_another_invoking_pane(self):
        self.env["TMUX_PANE"] = "%7"
        self.env["PANES"] = "%9|review-42|" + str(ROOT) + "|pi|exec pi --name review-42"
        self.env["BOUNDARY"] = BASE + ".." + HEAD
        self.run_fish('__review_start_pi $argv[2..-1]', str(ROOT), "review-42",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
        self.assertIn(["tmux", "move-pane", "-d", "-v", "-l", "40%", "-s", "%9", "-t", "%7"], self.recorded())
        self.assertFalse(any("split-window" in call for call in self.recorded()))

    def test_move_failure_does_not_create_a_duplicate_agent(self):
        self.env["PANES"] = "%9|review-42|" + str(ROOT) + "|pi|exec pi --name review-42"
        self.env["MOVE_FAIL"] = "1"
        self.run_fish('__review_start_pi $argv[2..-1]; test $status -eq 1', str(ROOT), "review-42",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
        self.assertFalse(any("split-window" in call or "send-keys" in call for call in self.recorded()))

    def test_missing_pane_environment_uses_tmux_context(self):
        self.env.pop("TMUX_PANE", None)
        self.run_fish('__review_start_pi $argv[2..-1]', str(ROOT), "review-42",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
        self.assertIn(["tmux", "display-message", "-p", "#{pane_id}"], self.recorded())
        split = next(call for call in self.recorded() if "split-window" in call)
        self.assertEqual(split[2:8], ["-d", "-v", "-l", "40%", "-t", "%1"])

    @unittest.skipUnless(shutil.which("tmux"), "real tmux is not installed")
    def test_real_tmux_moves_the_same_process_to_the_invoking_pane(self):
        actual_tmux = shutil.which("tmux")
        socket = self.directory / "tmux.sock"
        env = dict(self.env)
        env.pop("TMUX", None)
        env.pop("TMUX_PANE", None)
        env["SHELL"] = "/bin/sh"
        env["XDG_CONFIG_HOME"] = str(self.directory / "config")
        def tmux(*args):
            result = subprocess.run([actual_tmux, "-S", str(socket), "-f", "/dev/null", *args],
                                    env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()
        # A private server with self-expiring dummy processes; no live Pi or user panes.
        first = tmux("new-session", "-d", "-s", "review-fixture", "-x", "120", "-y", "40",
                     "-P", "-F", "#{pane_id}", "exec sleep 6")
        try:
            session = tmux("display-message", "-p", "-t", first, "#{session_id}")
            agent = tmux("new-window", "-t", session + ":", "-d", "-P", "-F", "#{pane_id}",
                         "exec sleep 6 # exec pi")
            caller = tmux("split-window", "-t", first, "-h", "-d", "-P", "-F", "#{pane_id}", "exec sleep 6")
            tmux("set-option", "-pt", agent, "@pi_agent_name", "review-42")
            tmux("set-option", "-pt", agent, "@pi_review_repo", str(ROOT))
            tmux("set-option", "-pt", agent, "@pi_review_boundary", BASE + ".." + HEAD)
            pid = tmux("display-message", "-p", "-t", agent, "#{pane_pid}")
            wrapper = self.directory / "bin/tmux"
            wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(actual_tmux) + " -S " + shlex.quote(str(socket)) + ' "$@"\n')
            focused = tmux("display-message", "-p", "#{pane_id}")
            self.env["TMUX_PANE"] = caller
            self.run_fish('__review_start_pi $argv[2..-1]', str(ROOT), "review-42",
                          "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
            self.assertEqual(tmux("display-message", "-p", "-t", agent, "#{pane_pid}"), pid)
            def geometry(pane):
                return tmux("display-message", "-p", "-t", pane,
                            "#{window_id}|#{pane_left}|#{pane_top}|#{pane_height}").split("|")
            def assert_beside():
                agent_position, caller_position = geometry(agent), geometry(caller)
                self.assertEqual(agent_position[:2], caller_position[:2])
                self.assertEqual(int(agent_position[2]), int(caller_position[2]) + int(caller_position[3]) + 1)
            assert_beside()
            self.assertEqual(tmux("display-message", "-p", "#{pane_id}"), focused, "startup does not steal focus")
            before = geometry(agent)
            self.run_fish('__review_start_pi $argv[2..-1]', str(ROOT), "review-42",
                          "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
            assert_beside()
            self.assertEqual(geometry(agent), before, "reuse preserves the existing layout")
            self.assertEqual(tmux("display-message", "-p", "#{pane_id}"), focused)
            self.assertEqual(tmux("display-message", "-p", "-t", agent, "#{pane_pid}"), pid)
            # The same session's other windows must also reuse, not duplicate, the agent.
            caller = tmux("new-window", "-t", "review-fixture", "-d", "-P", "-F", "#{pane_id}", "exec sleep 6")
            self.env["TMUX_PANE"] = caller
            self.run_fish('__review_start_pi $argv[2..-1]', str(ROOT), "review-42",
                          "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
            assert_beside()
            self.assertEqual(tmux("display-message", "-p", "-t", agent, "#{pane_pid}"), pid)
        finally:
            # Wait for the private fixture to exit naturally before removing its socket directory.
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = subprocess.run([actual_tmux, "-S", str(socket), "list-sessions"], env=env,
                                        capture_output=True, timeout=5)
                if result.returncode != 0:
                    break
                time.sleep(0.1)
            else:
                self.fail("private tmux fixture did not exit")

    def test_new_agent_registers_board_identity(self):
        self.run_fish('__review_start_pi $argv[2..-1]', str(ROOT), "review-42",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
        split = next(call for call in self.recorded() if "split-window" in call)
        self.assertIn("@pi_agent_name", split[-1])
        self.assertIn("--review-dir", split[-1])
        self.assertEqual(split[2:9], ["-d", "-v", "-l", "40%", "-t", "%1", "-P"])
        self.assertFalse(any("new-window" in call for call in self.recorded()))
        self.assertIn("review-42", split[-1])
        self.assertIn("explicitly authorizes creating and updating /fixture/guide.json and /fixture/guide.json.tmp", split[-1])
        self.assertIn("two files only", split[-1])
        self.assertTrue(any("@pi_review_repo" in call for call in self.recorded()))


    def test_start_does_not_reuse_another_repository(self):
        self.env["PANES"] = "%9|review-42|/another/repository|pi|exec pi --name review-42"
        self.run_fish('__review_start_pi $argv[2..-1]', str(ROOT), "review-42",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
        self.assertTrue(any("split-window" in call for call in self.recorded()))
        self.assertFalse(any("move-pane" in call or "send-keys" in call for call in self.recorded()))

if __name__ == "__main__":
    unittest.main()
