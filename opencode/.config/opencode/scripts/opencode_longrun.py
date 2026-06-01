#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DIR = Path("/tmp/opencode-longrun")
DEFAULT_HEARTBEAT_SECONDS = 5.0
DEFAULT_STATUS_LIMIT = 10
TAIL_LINES = 40


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run commands with combined log capture and heartbeat status JSON.",
        epilog=(
            "Timeouts use start_new_session=True on POSIX so termination targets the "
            "child process group; non-POSIX falls back to direct process termination."
        ),
    )
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    run_parser = subparsers.add_parser("run", help="Run a command and track it in a log/status pair")
    run_parser.add_argument("--name", required=True, help="Human-readable run name")
    run_parser.add_argument("--cwd", help="Working directory; defaults to the current directory")
    run_parser.add_argument("--log", help="Log path; defaults under /tmp/opencode-longrun")
    run_parser.add_argument("--status", help="Status JSON path; defaults under /tmp/opencode-longrun")
    run_parser.add_argument(
        "--heartbeat-seconds",
        type=positive_float,
        default=DEFAULT_HEARTBEAT_SECONDS,
        help=f"Seconds between status updates; defaults to {DEFAULT_HEARTBEAT_SECONDS:g}",
    )
    run_parser.add_argument(
        "--timeout-seconds",
        type=positive_float,
        help="Terminate the command after this many seconds",
    )
    run_parser.add_argument("command", nargs=argparse.REMAINDER, help="Command argv after --")

    status_parser = subparsers.add_parser("status", help="Show status JSON files")
    status_parser.add_argument(
        "target",
        nargs="?",
        default=str(DEFAULT_DIR),
        help="Status JSON file or directory; defaults to /tmp/opencode-longrun",
    )
    status_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format; defaults to text",
    )
    status_parser.add_argument(
        "--limit",
        type=positive_int,
        default=DEFAULT_STATUS_LIMIT,
        help=f"Maximum statuses to show for directories; defaults to {DEFAULT_STATUS_LIMIT}",
    )

    tail_parser = subparsers.add_parser("tail", help="Print the tail of a tracked log")
    tail_parser.add_argument("target", help="Status JSON path or log path")
    tail_parser.add_argument(
        "--lines",
        type=positive_int,
        default=TAIL_LINES,
        help=f"Lines to print; defaults to {TAIL_LINES}",
    )

    return parser.parse_args()


def positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def positive_float(raw: str) -> float:
    value = float(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return value


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip()).strip("-._")
    return cleaned or "command"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_paths(name: str) -> tuple[Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    base = f"{safe_name(name)}-{stamp}"
    return DEFAULT_DIR / f"{base}.log", DEFAULT_DIR / f"{base}.json"


def expand_path(raw: str | None) -> Path | None:
    if raw is None:
        return None
    return Path(os.path.expanduser(raw)).resolve()


def write_status(status_path: Path, status: dict) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = status_path.with_name(f".{status_path.name}.tmp")
    tmp_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(status_path)


def read_status(status_path: Path) -> dict:
    with status_path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"status file is not a JSON object: {status_path}")
    return loaded


def elapsed_seconds(start_time: float) -> float:
    return round(time.monotonic() - start_time, 3)


def status_snapshot(
    status: dict,
    state: str,
    start_time: float,
    output_lines: deque[str],
    lock: threading.Lock,
) -> dict:
    with lock:
        lines = list(output_lines)
    last_log_line = lines[-1] if lines else None
    status.update(
        {
            "state": state,
            "status": state,
            "updated_at": utc_now(),
            "elapsed_seconds": elapsed_seconds(start_time),
            "last_log_line": last_log_line,
            "last_output_sample": "\n".join(lines) if lines else None,
        }
    )
    return status


def read_process_output(
    process: subprocess.Popen[str],
    log_path: Path,
    output_lines: deque[str],
    lock: threading.Lock,
) -> None:
    assert process.stdout is not None
    with log_path.open("a", encoding="utf-8", buffering=1, errors="replace") as log_file:
        for line in process.stdout:
            log_file.write(line)
            clean_line = line.rstrip("\r\n")
            if clean_line:
                with lock:
                    output_lines.append(clean_line)


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()


def run_command(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("run requires a command after --")

    cwd = expand_path(args.cwd) or Path.cwd()
    log_path, status_path = default_paths(args.name)
    log_path = expand_path(args.log) or log_path
    status_path = expand_path(args.status) or status_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.parent.mkdir(parents=True, exist_ok=True)

    started_at = utc_now()
    start_time = time.monotonic()
    output_lines: deque[str] = deque(maxlen=20)
    output_lock = threading.Lock()
    status = {
        "name": args.name,
        "command": command,
        "cwd": str(cwd),
        "log_path": str(log_path),
        "status_path": str(status_path),
        "state": "starting",
        "status": "starting",
        "started_at": started_at,
        "updated_at": started_at,
        "elapsed_seconds": 0.0,
        "pid": None,
        "heartbeat_seconds": args.heartbeat_seconds,
        "timeout_seconds": args.timeout_seconds,
        "returncode": None,
        "timed_out": False,
        "last_log_line": None,
        "last_output_sample": None,
    }

    write_status(status_path, status)
    print(f"launched {args.name}: log={log_path} status={status_path}", flush=True)

    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
            start_new_session=(os.name == "posix"),
        )
    except OSError as error:
        returncode = 127 if isinstance(error, FileNotFoundError) and cwd.exists() else 126
        status["returncode"] = returncode
        status["error"] = str(error)
        write_status(status_path, status_snapshot(status, "failed_to_start", start_time, output_lines, output_lock))
        print(
            f"completed {args.name}: state=failed_to_start returncode={returncode} "
            f"error={error} log={log_path} status={status_path}",
            flush=True,
        )
        return returncode
    status["pid"] = process.pid
    write_status(status_path, status_snapshot(status, "running", start_time, output_lines, output_lock))

    reader = threading.Thread(
        target=read_process_output,
        args=(process, log_path, output_lines, output_lock),
        daemon=True,
    )
    reader.start()

    timed_out = False
    next_heartbeat = time.monotonic() + args.heartbeat_seconds
    while process.poll() is None:
        now = time.monotonic()
        if args.timeout_seconds is not None and now - start_time >= args.timeout_seconds:
            timed_out = True
            status["timed_out"] = True
            write_status(status_path, status_snapshot(status, "timing_out", start_time, output_lines, output_lock))
            terminate_process(process)
            break
        if now >= next_heartbeat:
            write_status(status_path, status_snapshot(status, "running", start_time, output_lines, output_lock))
            next_heartbeat = now + args.heartbeat_seconds
        time.sleep(0.1)

    process.wait()
    reader.join()
    status["returncode"] = process.returncode
    status["timed_out"] = timed_out
    final_state = "timed_out" if timed_out else ("succeeded" if process.returncode == 0 else "failed")
    write_status(status_path, status_snapshot(status, final_state, start_time, output_lines, output_lock))
    print(
        f"completed {args.name}: state={final_state} returncode={process.returncode} "
        f"log={log_path} status={status_path}",
        flush=True,
    )
    return 124 if timed_out else int(process.returncode or 0)


def load_statuses(target: Path, limit: int) -> list[dict]:
    if target.is_file():
        return [read_status(target)]
    if not target.exists():
        raise FileNotFoundError(target)
    status_paths = sorted(target.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return [read_status(path) for path in status_paths[:limit]]


def format_status(status: dict) -> str:
    parts = [
        str(status.get("name") or "<unnamed>"),
        str(status.get("state") or status.get("status") or "unknown"),
        f"elapsed={status.get('elapsed_seconds', 'unknown')}s",
        f"pid={status.get('pid')}",
        f"returncode={status.get('returncode')}",
    ]
    if status.get("timed_out"):
        parts.append("timed_out=true")
    parts.append(f"updated={status.get('updated_at', 'unknown')}")
    parts.append(f"log={status.get('log_path', 'unknown')}")
    parts.append(f"status={status.get('status_path', 'unknown')}")
    last_log_line = status.get("last_log_line")
    if last_log_line:
        parts.append(f"last={last_log_line}")
    return " | ".join(parts)


def show_status(args: argparse.Namespace) -> int:
    statuses = load_statuses(expand_path(args.target) or DEFAULT_DIR, args.limit)
    if args.format == "json":
        output: object = statuses[0] if len(statuses) == 1 else statuses
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        for status in statuses:
            print(format_status(status))
    return 0


def tail_log(args: argparse.Namespace) -> int:
    target = expand_path(args.target)
    if target is None:
        raise SystemExit("tail requires a status JSON or log path")
    log_path = target
    if target.suffix == ".json":
        status = read_status(target)
        log_value = status.get("log_path")
        if not log_value:
            raise SystemExit(f"status file does not include log_path: {target}")
        log_path = Path(str(log_value))
    lines: deque[str] = deque(maxlen=args.lines)
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            lines.append(line.rstrip("\n"))
    for line in lines:
        print(line)
    return 0


def main() -> int:
    args = parse_args()
    if args.command_name == "run":
        return run_command(args)
    if args.command_name == "status":
        return show_status(args)
    if args.command_name == "tail":
        return tail_log(args)
    raise SystemExit(f"unknown command: {args.command_name}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
