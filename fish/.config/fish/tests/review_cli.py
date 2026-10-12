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
import json, os, sys
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
    elif args[0] == "display-message": print("%1")
    elif args[0] == "move-pane" and os.environ.get("MOVE_FAIL"): sys.exit(1)
elif name == "pi": sys.exit("Pi must not run synchronously")
'''


class ReviewCLI(unittest.TestCase):
    def setUp(self):
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

    def run_fish(self, command, *args):
        result = subprocess.run(["fish", "-c", 'source "$argv[1]"; ' + command,
                                 "--", str(SOURCE), *args], cwd=ROOT, env=self.env,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
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
        self.assertIn("vim.system", nvim[2])
        self.assertIn(str(SOURCE), nvim[2])
        self.assertFalse(any(call[0] in ("pi", "tmux") for call in self.recorded()))
        guide_dir = self.directory / "notes/projects/repo/branch-reviews/feature-review"
        bootstrap = (guide_dir / "assistant-bootstrap.md").read_text()
        self.assertIn(BASE + ".." + HEAD, bootstrap)
        self.assertIn("persistent diagram-first Diffview contract in references/output-templates.md", bootstrap)
        self.assertIn("update this same guide as understanding changes", bootstrap)
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

    def test_outside_tmux_opens_without_agent_or_generation(self):
        self.env.pop("TMUX", None)
        result = self.run_fish("review")
        context, nvim = self.context()
        self.assertIsNone(context["assistant_name"])
        self.assertNotIn("vim.system", nvim[2])
        self.assertIn("Diffview only", result.stderr)
        self.assertFalse((self.directory / "notes").exists())

    def test_existing_agent_is_reused_and_refresh_is_explicit(self):
        self.env["PANES"] = "%9|review-42|" + str(ROOT) + "|pi|exec pi --name review-42"
        self.env["BOUNDARY"] = BASE + ".." + HEAD
        self.run_fish('__review_open_pi_pane $argv[2..-1]', str(ROOT), "review-42",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
        self.assertFalse(any("split-window" in call or "send-keys" in call for call in self.recorded()))
        self.assertIn(["tmux", "move-pane", "-d", "-v", "-l", "40%", "-s", "%9", "-t", "%1"], self.recorded())
        listing = next(call for call in self.recorded() if call[:2] == ["tmux", "list-panes"])
        self.assertEqual(listing[2:6], ["-s", "-t", "%1", "-F"])
        self.run_fish('__review_open_pi_pane $argv[2..-1]', str(ROOT), "review-42",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "1")
        self.assertTrue(any("send-keys" in call for call in self.recorded()))
        self.assertFalse(any("split-window" in call for call in self.recorded()))

    def test_reuse_from_another_invoking_pane(self):
        self.env["TMUX_PANE"] = "%7"
        self.env["PANES"] = "%9|review-42|" + str(ROOT) + "|pi|exec pi --name review-42"
        self.env["BOUNDARY"] = BASE + ".." + HEAD
        self.run_fish('__review_open_pi_pane $argv[2..-1]', str(ROOT), "review-42",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
        self.assertIn(["tmux", "move-pane", "-d", "-v", "-l", "40%", "-s", "%9", "-t", "%7"], self.recorded())
        self.assertFalse(any("split-window" in call or "send-keys" in call for call in self.recorded()))

    def test_move_failure_does_not_create_a_duplicate_agent(self):
        self.env["PANES"] = "%9|review-42|" + str(ROOT) + "|pi|exec pi --name review-42"
        self.env["MOVE_FAIL"] = "1"
        self.run_fish('__review_open_pi_pane $argv[2..-1]; test $status -eq 1', str(ROOT), "review-42",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
        self.assertFalse(any("split-window" in call or "send-keys" in call for call in self.recorded()))

    def test_missing_pane_environment_uses_tmux_context(self):
        self.env.pop("TMUX_PANE", None)
        self.run_fish('__review_open_pi_pane $argv[2..-1]', str(ROOT), "review-42",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
        self.assertIn(["tmux", "display-message", "-p", "#{pane_id}"], self.recorded())
        split = next(call for call in self.recorded() if "split-window" in call)
        self.assertEqual(split[2:4], ["-t", "%1"])

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
            agent = tmux("split-window", "-t", first, "-v", "-d", "-P", "-F", "#{pane_id}",
                         "exec sleep 6 # exec pi")
            caller = tmux("split-window", "-t", first, "-h", "-d", "-P", "-F", "#{pane_id}", "exec sleep 6")
            tmux("set-option", "-pt", agent, "@pi_agent_name", "review-42")
            tmux("set-option", "-pt", agent, "@pi_review_repo", str(ROOT))
            tmux("set-option", "-pt", agent, "@pi_review_boundary", BASE + ".." + HEAD)
            pid = tmux("display-message", "-p", "-t", agent, "#{pane_pid}")
            wrapper = self.directory / "bin/tmux"
            wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(actual_tmux) + " -S " + shlex.quote(str(socket)) + ' "$@"\n')
            self.env["TMUX_PANE"] = caller
            self.run_fish('__review_open_pi_pane $argv[2..-1]', str(ROOT), "review-42",
                          "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
            self.assertEqual(tmux("display-message", "-p", "-t", agent, "#{pane_pid}"), pid)
            def geometry(pane):
                return tmux("display-message", "-p", "-t", pane,
                            "#{window_id}|#{pane_left}|#{pane_top}|#{pane_height}").split("|")
            def assert_beside():
                a, c = geometry(agent), geometry(caller)
                self.assertEqual(a[:2], c[:2])
                self.assertEqual(int(a[2]), int(c[2]) + int(c[3]) + 1)
            assert_beside()
            # The same session's other windows must also reuse, not duplicate, the agent.
            caller = tmux("new-window", "-t", "review-fixture", "-d", "-P", "-F", "#{pane_id}", "exec sleep 6")
            self.env["TMUX_PANE"] = caller
            self.run_fish('__review_open_pi_pane $argv[2..-1]', str(ROOT), "review-42",
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
        self.run_fish('__review_open_pi_pane $argv[2..-1]', str(ROOT), "review-42",
                      "/fixture/bootstrap.md", BASE + ".." + HEAD, "0")
        split = next(call for call in self.recorded() if "split-window" in call)
        self.assertIn("@pi_agent_name", split[-1])
        self.assertEqual(split[2:8], ["-t", "%1", "-v", "-l", "40%", "-d"])
        self.assertIn("review-42", split[-1])
        self.assertIn("explicitly authorizes creating and updating /fixture/guide.json and /fixture/guide.json.tmp", split[-1])
        self.assertIn("two files only", split[-1])
        self.assertTrue(any("@pi_review_repo" in call for call in self.recorded()))


if __name__ == "__main__":
    unittest.main()
