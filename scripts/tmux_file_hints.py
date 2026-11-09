#!/usr/bin/env python3
"""Choose a visible file path without changing the remote tmux pane's layout."""

import itertools
import os
from pathlib import Path
import re
import select
import shlex
import subprocess
import sys
import termios
import tty
import unicodedata
from urllib.parse import unquote


PATH_PATTERN = re.compile(
    r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s`<>\"'|]+"
    r"|(?:~/|/|\.\.?/)[^\s`<>\"'|()\[\]{}*]+"
    r"|(?<![\w/:])[\w@+.-]+(?:/[\w@+.-]+)*\.[\w+-]+(?::\d+(?::\d+)?)?"
)
OPENER = Path(__file__).resolve().with_name("open_in_tmux_nvim_pane.sh")


def tmux(*args):
    return subprocess.check_output(["tmux", *args], text=True).removesuffix("\n")


def resolve_file_target(token, cwd):
    token = token.rstrip(".,;:!?)]}")
    if "://" in token:
        if not token.startswith("file://"):
            return None
        token = unquote(token.removeprefix("file://").removeprefix("localhost"))
    match = re.fullmatch(r"(.*?)(:\d+(?::\d+)?)?", token)
    path, location = match.groups()
    path = Path(os.path.expanduser(path))
    if not path.is_absolute():
        path = Path(cwd) / path
    return str(path) + (location or "") if path.is_file() else None


def find_file_positions(joined_lines, cwd, width):
    """Map paths in joined lines back to their original pane cells."""
    file_positions, row = [], 0
    for line in joined_lines:
        matches = {}
        for match in PATH_PATTERN.finditer(line):
            target = resolve_file_target(match.group(), cwd)
            if target:
                matches[match.start()] = target
        column = 0
        for offset, char in enumerate(line):
            if unicodedata.combining(char):
                character_width = 0
            elif unicodedata.east_asian_width(char) in ("W", "F"):
                character_width = 2
            else:
                character_width = 1
            if column + character_width > width:
                row += 1
                column = 0
            if offset in matches:
                file_positions.append((row, column, matches[offset]))
            column += character_width
        row += 1
    return file_positions


def render_hints(rows, hints, prefix):
    # Absolute cursor positions and disabled wrapping also protect the last row.
    output = ["\x1b[?25l\x1b[?7l\x1b[0m\x1b[H\x1b[2J"]
    for row, content in enumerate(rows, 1):
        output.append(f"\x1b[{row};1H{content}")
    for label, (row, column, _) in hints:
        if label.startswith(prefix):
            output.append(f"\x1b[{row + 1};{column + 1}H\x1b[0;1;30;43m{label}\x1b[0m")
    return "".join(output)


def select_file(rows, file_positions, width, height, read_key, emit):
    alphabet = "asdfghjkl"
    visible_files = [
        (row, column, target)
        for row, column, target in file_positions
        if row < height
    ]
    if not visible_files:
        return None
    label_length = 1
    while len(alphabet) ** label_length < len(visible_files):
        label_length += 1
    labels = ("".join(chars) for chars in itertools.product(alphabet, repeat=label_length))
    hints = [
        (label, (row, min(column, width - label_length), target))
        for label, (row, column, target) in zip(labels, visible_files)
    ]
    prefix = ""
    while True:
        emit(render_hints(rows, hints, prefix))
        key = read_key()
        if key in (None, "", "\x1b", "\x03", "q"):
            return None
        if key in ("\x7f", "\b"):
            prefix = prefix[:-1]
        elif key in alphabet:
            candidate_prefix = prefix + key
            for label, (_, _, target) in hints:
                if label.startswith(candidate_prefix):
                    prefix = candidate_prefix
                    if label == prefix:
                        return target
                    break


def open_hint_overlay(pane):
    width, height, foreground, background = tmux(
        "display-message", "-p", "-t", pane,
        "#{pane_width} #{pane_height} #{pane_fg} #{pane_bg}",
    ).split()
    # "default" inherits tmux's popup theme; "terminal" bypasses that theme.
    foreground = "terminal" if foreground == "default" else foreground
    background = "terminal" if background == "default" else background
    style = f"fg={foreground},bg={background}"
    command = shlex.join([sys.executable, str(Path(__file__).resolve()), "--select", pane])
    subprocess.run([
        "tmux", "display-popup", "-t", pane, "-E", "-B", "-s", style,
        "-x", "P", "-y", "P", "-w", width, "-h", height, command,
    ], check=True)


def select_file_in_pane(pane):
    cwd = tmux("display-message", "-p", "-t", pane, "#{pane_current_path}")
    # Keep physical rows for display; joined lines are only for finding wrapped paths.
    physical_rows = tmux("capture-pane", "-p", "-e", "-N", "-t", pane).split("\n")
    joined_lines = tmux("capture-pane", "-p", "-J", "-t", pane).split("\n")
    width, height = os.get_terminal_size()
    file_positions = find_file_positions(joined_lines, cwd, width)
    if not file_positions:
        tmux("display-message", "-t", pane, "No visible file paths found")
        return
    input_fd = sys.stdin.fileno()
    terminal_settings = termios.tcgetattr(input_fd)

    def read_key():
        while os.get_terminal_size() == (width, height):
            if select.select([input_fd], [], [], 0.1)[0]:
                return os.read(input_fd, 1).decode("ascii", errors="ignore")
        return None  # Dismiss on resize rather than move the captured view.

    def emit(text):
        sys.stdout.write(text)
        sys.stdout.flush()

    try:
        tty.setraw(input_fd)
        target = select_file(physical_rows, file_positions, width, height, read_key, emit)
    finally:
        termios.tcsetattr(input_fd, termios.TCSADRAIN, terminal_settings)
        emit("\x1b[0m\x1b[?7h\x1b[?25h")
    if target:
        subprocess.run([str(OPENER), target], env={**os.environ, "TMUX_PANE": pane}, check=True)


def main():
    pane = sys.argv[-1]
    if not re.fullmatch(r"%\d+", pane):
        raise SystemExit("Usage: tmux_file_hints.py [--select] %pane_id")
    if len(sys.argv) == 2:
        open_hint_overlay(pane)
    else:
        select_file_in_pane(pane)


if __name__ == "__main__":
    main()
