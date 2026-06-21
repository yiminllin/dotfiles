#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    repo_root = discover_repo_root()
    checks = (
        ("renderer stale filtering", lambda: check_renderer_stale_filtering(repo_root)),
        ("renderer empty fallback", lambda: check_renderer_empty_fallback(repo_root)),
        ("renderer refresh throttling", lambda: check_renderer_refresh_throttling(repo_root)),
        ("plugin state ingestion", lambda: check_plugin_state_ingestion(repo_root)),
        ("board bash syntax", lambda: check_board_bash_syntax(repo_root)),
        ("board progress gate", lambda: check_board_progress_gate(repo_root)),
        ("board empty progress smoke", lambda: check_board_empty_progress(repo_root)),
        ("board repaint cache", lambda: check_board_repaint_cache(repo_root)),
    )

    failures: list[str] = []
    for label, check in checks:
        try:
            check()
        except AssertionError as error:
            failures.append(f"{label}: {error}")

    if failures:
        print("OpenCode progress UI checks failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


def discover_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts/check_dotfiles.sh").is_file() and (parent / "tmux/.tmux/opencode-agent-board").is_file():
            return parent
    raise AssertionError("could not discover repo root from check_progress_ui.py")


def check_renderer_stale_filtering(repo_root: Path) -> None:
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="opencode-progress-check-") as temp_dir:
        state_dir = Path(temp_dir) / "state"
        state_dir.mkdir()
        state_file = state_dir / "stale-only.json"
        write_state(state_file, stale_tool_entries())

        default = run_renderer(repo_root, state_dir, state_file)
        assert default.stdout == "", failure_detail(
            "stale-only state should render empty by default",
            default,
        )
        assert "OC active=5 stale=5" not in default.stdout, failure_detail(
            "default render should not show stale-only historical counts",
            default,
        )

        explicit = run_renderer(repo_root, state_dir, state_file, "--show-stale")
        assert "active=5" in explicit.stdout and "stale=5" in explicit.stdout, failure_detail(
            "--show-stale should render explicit stale diagnostics",
            explicit,
        )


def check_renderer_empty_fallback(repo_root: Path) -> None:
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="opencode-progress-check-") as temp_dir:
        state_dir = Path(temp_dir) / "state"
        state_dir.mkdir()
        state_file = state_dir / "empty.json"
        write_state(state_file, [])

        result = run_renderer(repo_root, state_dir, state_file, "--show-empty")
        assert result.stdout == "OC idle", failure_detail(
            "--show-empty should render the calm idle fallback exactly",
            result,
        )


def run_renderer(
    repo_root: Path,
    state_dir: Path,
    state_file: Path,
    *extra_args: str,
) -> subprocess.CompletedProcess[str]:
    renderer = repo_root / "opencode/.config/opencode/scripts/opencode_progress_render.py"
    env = isolated_progress_env(state_dir)
    result = subprocess.run(
        [
            sys.executable,
            str(renderer),
            str(state_file),
            "--mode",
            "statusline",
            "--width",
            "76",
            *extra_args,
        ],
        cwd=repo_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, failure_detail("renderer exited non-zero", result)
    result.stdout = result.stdout.rstrip("\n")
    return result


def check_renderer_refresh_throttling(repo_root: Path) -> None:
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="opencode-progress-check-") as temp_dir:
        state_dir = Path(temp_dir) / "state"
        state_dir.mkdir()
        snapshot_file = state_dir / "agent-board-snapshot.json"
        stamp_file = state_dir / ".agent-board-snapshot-refresh.stamp"
        refresh_args = (
            "--show-empty",
            "--refresh",
            "--refresh-seconds",
            "60",
            "--snapshot-limit",
            "0",
        )

        first = run_renderer_without_target(repo_root, state_dir, *refresh_args)
        assert first.stdout == "OC idle", failure_detail("refresh render should keep the idle fallback", first)
        assert snapshot_file.is_file(), "refresh render should create the agent-board snapshot cache"
        first_mtime = snapshot_file.stat().st_mtime_ns

        second = run_renderer_without_target(repo_root, state_dir, *refresh_args)
        assert second.stdout == "OC idle", failure_detail("throttled refresh render should stay idle", second)
        assert snapshot_file.stat().st_mtime_ns == first_mtime, (
            "refresh render should not rewrite the snapshot inside the throttle interval"
        )

        old_time = time.time() - 120
        os.utime(snapshot_file, (old_time, old_time))
        if stamp_file.exists():
            os.utime(stamp_file, (old_time, old_time))
        old_mtime = snapshot_file.stat().st_mtime_ns
        third = run_renderer_without_target(repo_root, state_dir, *refresh_args)
        assert third.stdout == "OC idle", failure_detail("stale refresh render should stay idle", third)
        assert snapshot_file.stat().st_mtime_ns > old_mtime, "stale snapshot should refresh after the interval"


def run_renderer_without_target(repo_root: Path, state_dir: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    renderer = repo_root / "opencode/.config/opencode/scripts/opencode_progress_render.py"
    result = subprocess.run(
        [
            sys.executable,
            str(renderer),
            "--mode",
            "statusline",
            "--width",
            "76",
            *extra_args,
        ],
        cwd=repo_root,
        env=isolated_progress_env(state_dir),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, failure_detail("renderer exited non-zero", result)
    result.stdout = result.stdout.rstrip("\n")
    return result


def check_plugin_state_ingestion(repo_root: Path) -> None:
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="opencode-progress-check-") as temp_dir:
        state_dir = Path(temp_dir) / "state"
        plugin_dir = state_dir / "plugins/progress-state"
        plugin_dir.mkdir(parents=True)
        write_plugin_entry(plugin_dir / "sample.json")

        status = run_progress_state_status(repo_root, state_dir)
        payload = json.loads(status.stdout)
        entries = payload.get("entries") or []
        encoded_payload = json.dumps(payload)
        assert payload.get("summary", {}).get("plugin") == 1, "state summary should count plugin entries"
        assert payload.get("summary", {}).get("active") == 1, "running plugin entry should count as active"
        assert entries and entries[0].get("source") == "plugin", "state helper should load plugin entries"
        assert "secret-token" not in encoded_payload and "hunter2" not in encoded_payload, (
            "plugin entry ingestion should scrub secret-like text"
        )
        assert "<redacted>" in entries[0].get("current", ""), "scrubbed plugin entry should keep redaction marker"

        rendered = run_renderer_without_target(repo_root, state_dir)
        assert "OC active=1" in rendered.stdout, failure_detail("renderer should show active plugin state", rendered)
        assert "secret-token" not in rendered.stdout and "hunter2" not in rendered.stdout, (
            "renderer should not leak scrubbed plugin fixture secrets"
        )


def run_progress_state_status(repo_root: Path, state_dir: Path) -> subprocess.CompletedProcess[str]:
    helper = repo_root / "opencode/.config/opencode/scripts/opencode_progress_state.py"
    result = subprocess.run(
        [
            sys.executable,
            str(helper),
            "status",
            "--state-dir",
            str(state_dir),
            "--format",
            "json",
        ],
        cwd=repo_root,
        env=isolated_progress_env(state_dir),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, failure_detail("progress state status exited non-zero", result)
    return result


def write_plugin_entry(path: Path) -> None:
    payload = {
        "schema_version": 1,
        "kind": "opencode_plugin_progress_entry",
        "updated_at": "2026-05-31T00:00:00+00:00",
        "entry": {
            "id": "plugin:tool:fixture-session:fixture-call",
            "source": "plugin",
            "label": "bash tool call",
            "goal": "bash tool call",
            "phase": "runtime tool",
            "current": "args: --token secret-token password=hunter2",
            "status": "running",
            "mode": "indeterminate",
            "updated_at": "2026-05-31T00:00:00+00:00",
            "started_at": "2026-05-31T00:00:00+00:00",
            "tool": {"name": "bash", "call_id": "fixture-call"},
            "session": {"id": "fixture-session", "location": "/tmp/opencode-progress-check"},
        },
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def isolated_progress_env(state_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["OPENCODE_PROGRESS_STATE_DIR"] = str(state_dir)
    env["OPENCODE_PROGRESS_DIR"] = str(state_dir)
    env["OPENCODE_DB_PATH"] = str(state_dir.parent / "missing-opencode.db")
    env["OPENCODE_LONGRUN_DIR"] = str(state_dir.parent / "missing-longrun")
    return env


def write_state(path: Path, entries: list[dict[str, object]]) -> None:
    payload = {
        "generated_at": "2026-05-31T00:00:00+00:00",
        "entries": entries,
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def stale_tool_entries() -> list[dict[str, object]]:
    return [
        {
            "id": f"stale-tool-{index}",
            "source": "stale_tools",
            "status": "stale",
            "stale": True,
            "goal": f"historical stale tool {index}",
            "current": "old runtime diagnostic",
            "updated_at": f"2026-05-31T00:0{index}:00+00:00",
        }
        for index in range(5)
    ]


def check_board_bash_syntax(repo_root: Path) -> None:
    board = repo_root / "tmux/.tmux/opencode-agent-board"
    result = subprocess.run(
        ["bash", "-n", str(board)],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, failure_detail("bash -n failed", result)


def check_board_empty_progress(repo_root: Path) -> None:
    board = repo_root / "tmux/.tmux/opencode-agent-board"
    board_text = board.read_text(encoding="utf-8")
    assert '[[ "${OPENCODE_AGENT_BOARD_SHOW_PROGRESS:-}" == 1 ]] || return 0' in board_text, (
        "progress_segment should be default-off unless OPENCODE_AGENT_BOARD_SHOW_PROGRESS=1"
    )
    assert "segment=$(" in board_text and 'python3 "$progress_renderer"' in board_text, (
        "progress_segment should tolerate renderer errors/empty output under set -e"
    )
    assert "--refresh" in board_text, "progress_segment should enable stale-cache refresh"
    assert "--refresh-seconds" in board_text, "progress_segment should pass the refresh throttle"
    assert "--snapshot-limit" in board_text, "progress_segment should pass the snapshot scan limit"
    assert "2>/dev/null || true" in board_text, "progress_segment should suppress renderer errors"
    assert '[[ -n "$segment" ]] || return 0' in board_text, "progress_segment should return success on empty output"

    timeout = shutil.which("timeout")
    if timeout is None:
        return

    with tempfile.TemporaryDirectory(dir="/tmp", prefix="opencode-progress-check-") as temp_dir:
        temp_path = Path(temp_dir)
        result = run_board_smoke(
            repo_root,
            temp_path,
            "#!/usr/bin/env python3\n",
            {"OPENCODE_AGENT_BOARD_SHOW_PROGRESS": "1"},
        )
        assert result.returncode == 124, failure_detail(
            "board should keep looping when the renderer emits empty output",
            result,
        )


def check_board_progress_gate(repo_root: Path) -> None:
    timeout = shutil.which("timeout")
    if timeout is None:
        return

    with tempfile.TemporaryDirectory(dir="/tmp", prefix="opencode-progress-check-") as temp_dir:
        temp_path = Path(temp_dir)
        called_file = temp_path / "renderer-called"
        renderer = (
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            f"Path({str(called_file)!r}).write_text('called', encoding='utf-8')\n"
            "print('OC active=1')\n"
        )

        default = run_board_smoke(repo_root, temp_path, renderer)
        assert default.returncode == 124, failure_detail("default board smoke should time out cleanly", default)
        assert not called_file.exists(), "board should not invoke the progress renderer by default"
        assert "OC active=1" not in default.stdout, failure_detail(
            "board should not append progress by default",
            default,
        )

        enabled = run_board_smoke(
            repo_root,
            temp_path,
            renderer,
            {"OPENCODE_AGENT_BOARD_SHOW_PROGRESS": "1"},
        )
        assert enabled.returncode == 124, failure_detail("enabled board smoke should time out cleanly", enabled)
        assert called_file.exists(), "board should invoke the progress renderer when explicitly enabled"
        assert "OC active=1" in enabled.stdout, failure_detail(
            "board should append progress when explicitly enabled",
            enabled,
        )


def run_board_smoke(
    repo_root: Path,
    temp_path: Path,
    renderer: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    board = repo_root / "tmux/.tmux/opencode-agent-board"
    fake_home = temp_path / "home"
    fake_bin = temp_path / "bin"
    fake_scripts = fake_home / ".config/opencode/scripts"
    fake_bin.mkdir(parents=True, exist_ok=True)
    fake_scripts.mkdir(parents=True, exist_ok=True)
    write_executable(fake_bin / "tmux", fake_tmux_script())
    write_executable(fake_scripts / "opencode_progress_render.py", renderer)

    env = os.environ.copy()
    env.pop("OPENCODE_AGENT_BOARD_SHOW_PROGRESS", None)
    env.update(
        {
            "HOME": str(fake_home),
            "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
            "TMUX_PANE": "%fixture",
        }
    )
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        ["timeout", "1s", "bash", str(board)],
        cwd=repo_root,
        env=env,
        text=True,
        input="",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def fake_tmux_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  display-message)
    printf '@fixture-window\n'
    ;;
  list-panes)
    exit 0
    ;;
  capture-pane)
    exit 0
    ;;
  switch-client|select-window|kill-pane)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
"""


def check_board_repaint_cache(repo_root: Path) -> None:
    board_text = (repo_root / "tmux/.tmux/opencode-agent-board").read_text(encoding="utf-8")
    assert 'last_rendered_content=""' in board_text, "missing repaint cache initialization"
    assert 'if [[ "$rendered_content" != "$last_rendered_content" ]]; then' in board_text, (
        "missing repaint-on-change conditional"
    )
    assert "last_rendered_content=$rendered_content" in board_text, "missing repaint cache assignment"


def failure_detail(message: str, result: subprocess.CompletedProcess[str]) -> str:
    stdout = concise(result.stdout)
    stderr = concise(result.stderr)
    return f"{message}; exit={result.returncode}; stdout={stdout!r}; stderr={stderr!r}"


def concise(value: str) -> str:
    value = value.strip()
    if len(value) <= 500:
        return value
    return value[:497] + "..."


if __name__ == "__main__":
    sys.exit(main())
