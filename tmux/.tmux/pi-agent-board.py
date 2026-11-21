#!/usr/bin/env python3
"""A stable, four-column tmux board for Pi sessions. MIT licensed."""

import json
import os
from pathlib import Path
import re
import select
import shlex
import signal
import subprocess
import sys
import termios
import time
import tty
import unicodedata
from dataclasses import dataclass


SEPARATOR = "\x1f"
FIELDS = (
    "pane_id", "pane_pid", "session_id", "window_id", "@pi_agent_board",
    "@pi_agent_name", "pane_title", "pane_current_command", "pane_start_command",
    "@pi_agent_status", "@pi_agent_status_owner", "pane_pipe", "@pi_agent_input_wait",
    "@pi_agent_dimmed", "@pi_agent_slot", "@pi_agent_progress",
    "@pi_session_id", "@pi_session_cwd", "@pi_session_owner", "@pi_agent_last_message",
)
PANE_FORMAT = SEPARATOR.join("#{" + field + "}" for field in FIELDS)
STALE_AFTER_MS = 24 * 60 * 60 * 1000
COLORS = {"RUN": "31", "WAIT": "32", "BLOCKED": "33", "ERR": "31", "UNKNOWN": "33"}
DIMMED_STYLE = "2;90"
HEADING_STYLE = "1;38;5;235;48;2;238;220;182"
GOAL_STYLE = "1;4;38;5;24"
SELECTED_STYLE = "1;7"
ACCENT_STYLE = "1;36"
BORDER_STYLE = "1;38;5;136"
PI_COMMAND = re.compile(r"(?:^|[\s;|&])(?:exec\s+)?(?:[^\s;|&]*/)?pi(?:[\s;|&]|$)")


def tmux(*args):
    return subprocess.check_output(["tmux", *args], text=True, stderr=subprocess.DEVNULL).rstrip("\n")


def alive(pid):
    try:
        number = int(pid)
        if number <= 0:
            return False
        os.kill(number, 0)
        return True
    except (ValueError, TypeError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def clean(text):
    return " ".join("".join(c if not unicodedata.category(c).startswith("C") or c == "\u200d" else " " for c in str(text)).split())


def clusters(text):
    """Keep combining marks and common emoji sequences in one terminal cell group."""
    groups = []
    for char in text:
        mark = unicodedata.category(char).startswith("M") or "\U0001f3fb" <= char <= "\U0001f3ff"
        regional = "\U0001f1e6" <= char <= "\U0001f1ff"
        if groups and (mark or char == "\u200d" or groups[-1].endswith("\u200d") or (
            regional and len(groups[-1]) == 1 and "\U0001f1e6" <= groups[-1] <= "\U0001f1ff"
        )):
            groups[-1] += char
        else:
            groups.append(char)
    return groups


def cell_width(group):
    widths = [2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
              for c in group if not unicodedata.category(c).startswith("M") and c != "\u200d"]
    if "\u200d" in group or "\ufe0f" in group or any("\U0001f3fb" <= c <= "\U0001f3ff" for c in group) or (group and "\U0001f1e6" <= group[0] <= "\U0001f1ff"):
        return max([2, *widths])
    return sum(widths)


def width(text):
    return sum(cell_width(group) for group in clusters(text))


def wrap(text, columns):
    indent = min(len(text) - len(text.lstrip(" ")), max(0, columns - 2))
    lines, line, used = [], " " * indent, indent
    for word in clean(text).split():
        if used > indent:
            if used + 1 + width(word) > columns:
                lines.append(line.rstrip())
                line, used = " " * indent, indent
            else:
                line, used = line + " ", used + 1
        for group in clusters(word):
            size = cell_width(group)
            if size > columns - indent:
                group, size = "…", 1
            if used + size > columns:
                lines.append(line.rstrip())
                line, used = " " * indent, indent
            line += group
            used += size
    return lines + [line.rstrip()]


def style(text, code):
    return f"\033[{code}m{text}\033[0m" if text else ""


def pi_ancestors():
    snapshot = subprocess.check_output(["ps", "-axo", "pid=,ppid=,comm=,args="], text=True)
    parents, agents = {}, []
    for line in snapshot.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        pid, parent, command = parts[:3]
        parents[pid] = parent
        if Path(command).name == "pi":
            agents.append(pid)
    result = set()
    for pid in agents:
        while pid in parents and pid not in result:
            result.add(pid)
            pid = parents[pid]
    return result


def agent_state(pane):
    if alive(pane["@pi_agent_input_wait"]):
        return "BLOCKED"
    owner, _, status = pane["@pi_agent_status"].rpartition(":")
    if owner and owner == pane["@pi_agent_status_owner"] and pane["pane_pipe"] == "1":
        state = {"working": "RUN", "blocked": "BLOCKED", "idle": "WAIT", "done": "WAIT", "error": "ERR"}.get(status)
        if state:
            return state
    try:
        content = "\n".join(tmux("capture-pane", "-p", "-t", pane["pane_id"]).splitlines()[-7:])
    except subprocess.CalledProcessError:
        return "UNKNOWN"
    if re.search(r"^\s*──\s*[^\s─]+\s+(Working|Retrying|Compacting|Auto-compacting|Summarizing)(?:[\s.(]|$)", content, re.M):
        return "RUN"
    if re.search(r"^\s*(Error:|Retry failed after|No models available)", content, re.M):
        return "ERR"
    return "WAIT" if "──" in content else "UNKNOWN"


def stale_message(pane, state, now_ms):
    if state != "WAIT":
        return ""
    raw = pane["@pi_agent_last_message"]
    try:
        if 0 < int(raw) < now_ms - STALE_AFTER_MS and alive(pane["@pi_session_owner"]):
            return raw
    except ValueError:
        pass
    return ""


def is_dimmed(manual, stale):
    return manual == "1" or bool(stale and manual != f"bright:{stale}")


def toggle_dim(pane, dimmed, stale):
    # A bright override lasts only for this conversation timestamp.
    if stale:
        value = f"bright:{stale}" if dimmed else "0"
    else:
        value = "0" if dimmed else "1"
    tmux("set-option", "-pt", pane, "@pi_agent_dimmed", value)


def toggle_pane_dim(pane_id):
    row = tmux("display-message", "-p", "-t", pane_id, PANE_FORMAT)
    values = row.split(SEPARATOR)
    if len(values) != len(FIELDS):
        return
    pane = dict(zip(FIELDS, values))
    stale = stale_message(pane, agent_state(pane), time.time() * 1000)
    toggle_dim(pane_id, is_dimmed(pane["@pi_agent_dimmed"], stale), stale)


def pin_lines(raw):
    try:
        snapshot = json.loads(raw)
        if not alive(snapshot["pid"]):
            raise ValueError("Publisher exited")
        plan = snapshot["plan"]
        if plan is None:
            return ["No pinned progress"]
        lines = [clean(plan["goal"])]
        for item in plan["milestones"]:
            glyph = {"done": "✓", "current": "▶", "pending": "○"}[item["status"]]
            lines.append(f"{glyph} {clean(item['label'])}")
            if item["status"] == "current":
                for task in item.get("tasks", []):
                    glyph = {"done": "✓", "current": "▶", "pending": "○"}[task["status"]]
                    lines.append(f"  {glyph} {clean(task['label'])}")
        if plan.get("blocker"):
            lines.append(f"! Blocked: {clean(plan['blocker'])}")
        return lines
    except (ValueError, TypeError, KeyError):
        return ["Progress unavailable", "Run /reload in Pi"]


@dataclass
class Agent:
    pane: str
    session: str
    window: str
    slot: int
    name: str
    state: str
    dimmed: bool
    pin: list
    pi_id: str = ""
    worktree: str = ""
    owner: str = ""
    stale: str = ""


def collect_agents():
    # Serialize slot allocation across simultaneously opened boards.
    lock = "pi_agent_board_slots"
    tmux("wait-for", "-L", lock)
    try:
        snapshot = tmux("list-panes", "-a", "-F", PANE_FORMAT)
        ancestors = pi_ancestors()
        panes = []
        for line in snapshot.splitlines():
            values = line.split(SEPARATOR)
            if len(values) != len(FIELDS):
                continue
            pane = dict(zip(FIELDS, values))
            start = pane["pane_start_command"]
            if pane["@pi_agent_board"] == "1":
                continue
            if pane["pane_current_command"] == "pi" or PI_COMMAND.search(start) or pane["pane_pid"] in ancestors:
                panes.append(pane)
            elif pane["@pi_agent_slot"]:
                tmux("set-option", "-pt", pane["pane_id"], "-u", "@pi_agent_slot")
        panes.sort(key=lambda pane: int(pane["pane_id"].lstrip("%")))
        occupied = set()
        # Read surviving slot order before assigning compact numbers.
        for pane in panes:
            slot = pane["@pi_agent_slot"]
            slot = int(slot) if slot.isdecimal() else 0
            pane["slot"] = slot if slot > 0 and slot not in occupied else 0
            if pane["slot"]:
                occupied.add(slot)
        # Keep survivor order, append new agents, and close gaps left by exits.
        panes.sort(key=lambda pane: (not pane["slot"], pane["slot"]))
        agents = []
        now_ms = time.time() * 1000
        for slot, pane in enumerate(panes, 1):
            pane["slot"] = slot
            if pane["@pi_agent_slot"] != str(slot):
                tmux("set-option", "-pt", pane["pane_id"], "@pi_agent_slot", str(slot))
            state = agent_state(pane)
            stale = stale_message(pane, state, now_ms)
            agents.append(Agent(
                pane["pane_id"], pane["session_id"], pane["window_id"], pane["slot"],
                clean(pane["@pi_agent_name"] or pane["pane_title"] or f"UNNAMED {pane['pane_id']}"),
                state, is_dimmed(pane["@pi_agent_dimmed"], stale), pin_lines(pane["@pi_agent_progress"]),
                pane["@pi_session_id"], pane["@pi_session_cwd"], pane["@pi_session_owner"], stale,
            ))
        return sorted(agents, key=lambda agent: agent.slot)
    finally:
        tmux("wait-for", "-U", lock)


def progress_color(line):
    return {"✓": "1;32", "▶": "1;33", "○": "1;90", "!": "31"}.get(line.lstrip()[:1], "39")


def render_grid(agents, columns, selected, current_window):
    if not agents:
        return ["No Pi agents"], 1
    if columns < 54:
        return wrap("Widen the board to at least 54 columns for the 4-column grid.", max(1, columns)), 1
    block_width = (columns - 6) // 4
    content_width = block_width - 4
    headings = {a.slot: wrap(f"[{a.slot}] {a.state} {a.name}", content_width) for a in agents}
    pins = {
        a.slot: [(part, GOAL_STYLE if i == 0 else progress_color(line))
                 for i, line in enumerate(a.pin) for part in wrap(line, content_width)]
        for a in agents
    }
    title_height = max(map(len, headings.values()))
    pin_height = max(map(len, pins.values()))
    # Top border, title divider, bottom border, and row gap add four lines.
    block_height = title_height + pin_height + 4
    blocks = {}
    for agent in agents:
        heading_style = DIMMED_STYLE if agent.dimmed else HEADING_STYLE
        if agent.window == current_window:
            heading_style += ";4"
        border_style = DIMMED_STYLE if agent.dimmed else ACCENT_STYLE if agent.slot == selected else BORDER_STYLE

        def edge(left, right):
            return style(left + "━" * (block_width - 2) + right, border_style)

        def body(text, used, heading=False):
            padding = " " * (content_width - used)
            if heading and not agent.dimmed:
                padding = style(padding, heading_style)
            return style("┃ ", border_style) + text + padding + style(" ┃", border_style)

        block = [edge("┏", "┓")]
        for i in range(title_height):
            line = headings[agent.slot][i] if i < len(headings[agent.slot]) else ""
            painted = style(line, heading_style)
            if i == 0:
                number = f"[{agent.slot}]"
                number_style = SELECTED_STYLE if agent.slot == selected else DIMMED_STYLE if agent.dimmed else ACCENT_STYLE
                tail = line[len(number):]
                if not agent.dimmed:
                    tail = tail.replace(agent.state, style(agent.state, "1;" + COLORS[agent.state]) + f"\033[{heading_style}m", 1)
                painted = style(number, number_style) + style(tail, heading_style)
            block.append(body(painted, width(line), heading=True))
        block.append(edge("┣", "┫"))
        for i in range(pin_height):
            line, color = pins[agent.slot][i] if i < len(pins[agent.slot]) else ("", "")
            block.append(body(style(line, DIMMED_STYLE if agent.dimmed else color), width(line)))
        block.extend([edge("┗", "┛"), " " * block_width])
        blocks[agent.slot] = block
    output = []
    for row in range((max(blocks) + 3) // 4):
        for y in range(block_height):
            cells = []
            for column in range(4):
                block = blocks.get(row * 4 + column + 1)
                cells.append(block[y] if block else " " * block_width)
            output.append("  ".join(cells))
    return output, block_height


def popup_size(agents, columns, rows):
    popup_width = max(1, int(columns * 0.95))
    lines, _ = render_grid(agents, max(1, popup_width - 2), None, None)
    popup_height = min(len(lines) + 3, max(4, int(rows * 0.85)))
    return popup_width, popup_height


def open_popup(pane, client, columns, rows):
    columns, rows = popup_size(collect_agents(), int(columns), int(rows))
    command = shlex.join(["env", f"TMUX_PANE={pane}", str(Path(__file__).with_suffix(""))])
    subprocess.run([
        "tmux", "display-popup", "-E", "-c", client, "-t", pane,
        "-w", str(columns), "-h", str(rows), "-b", "heavy",
        "-s", "bg=#fdf6e3,fg=#2e3440", "-S", "fg=colour223,bold",
        "-T", "#[fg=#9c5f2d,bold] Pi Agent Board ", command,
    ], check=True)


def context(pane):
    value = tmux("display-message", "-p", "-t", pane, "#{client_tty}" + SEPARATOR + "#{window_id}")
    return value.split(SEPARATOR)


def jump(agent, client):
    if client:
        tmux("switch-client", "-c", client, "-t", f"{agent.session}:{agent.window}")
    else:
        tmux("select-window", "-t", agent.window)
    subprocess.run([str(Path.home() / ".tmux/pi-pane-focus-main"), agent.window, agent.pane], check=False)


def read_key():
    if not select.select([sys.stdin], [], [], 1)[0]:
        return ""
    key = os.read(sys.stdin.fileno(), 1).decode(errors="ignore")
    if key == "\033" and select.select([sys.stdin], [], [], 0.02)[0]:
        key += os.read(sys.stdin.fileno(), 1).decode(errors="ignore")
        if key in ("\033[", "\033O"):
            while select.select([sys.stdin], [], [], 0.02)[0]:
                char = os.read(sys.stdin.fileno(), 1).decode(errors="ignore")
                key += char
                if "@" <= char <= "~":
                    break
    return key.replace("\033O", "\033[")


def main(select_session=False):
    def terminate(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    pane = os.environ.get("TMUX_PANE") or tmux("display-message", "-p", "#{pane_id}")
    client, current_window = context(pane)
    selected, offset, previous = None, 0, None
    notice, slot_input = "", None
    action = "link" if select_session else "jump"
    help_text = f"1–9 {action} · g slot Enter · arrows select · Enter {action}"
    help_text += " · j/k scroll · Esc/q cancel" if select_session else " · A dim · j/k/PgUp/PgDn scroll · q close"
    output = sys.stderr if select_session else sys.stdout
    by_slot = {}
    saved_tty = termios.tcgetattr(sys.stdin) if sys.stdin.isatty() else None
    try:
        if saved_tty:
            tty.setcbreak(sys.stdin)
        output.write("\033[?25l\033[?7l")
        while True:
            selected_pane = by_slot[selected].pane if selected in by_slot else pane
            agents = collect_agents()
            by_slot = {agent.slot: agent for agent in agents}
            selected = next((a.slot for a in agents if a.pane == selected_pane),
                            next((a.slot for a in agents if a.pane == pane),
                                 next((a.slot for a in agents if a.window == current_window), min(by_slot, default=None))))
            columns, rows = os.get_terminal_size(output.fileno())
            lines, block_height = render_grid(agents, columns, selected, current_window)
            available = max(1, rows - 1)
            offset = max(0, min(offset, max(0, len(lines) - available)))
            footer = (f"{action.capitalize()} to slot: {slot_input} · Enter confirm · Esc cancel"
                      if slot_input is not None else notice or help_text)
            screen = lines[offset:offset + available]
            screen += [""] * (available - len(screen))
            screen += [style(wrap(footer, max(1, columns))[0], DIMMED_STYLE)]
            content = "\r\n".join(screen)
            if (columns, rows, content) != previous:
                output.write("\033[H\033[J" + content)
                output.flush()
                previous = (columns, rows, content)
            key = read_key()
            if key:
                notice = ""
            target = None
            if slot_input is not None and key not in ("q", "\x04"):
                if key == "\033":
                    slot_input = None
                elif key in ("\x7f", "\b"):
                    slot_input = slot_input[:-1]
                elif len(key) == 1 and key in "0123456789":
                    slot_input += key
                elif key in ("\r", "\n") and slot_input:
                    target = next((slot for slot in by_slot if str(slot) == slot_input.lstrip("0")), None)
                    if target is None:
                        notice = f"No agent in slot {slot_input}. Press g to try again."
                    slot_input = None
            elif key in ("q", "\033", "\x04"):
                return
            elif key == "g":
                slot_input = ""
            elif key in ("j", "k", "\033[5~", "\033[6~"):
                offset += {"j": 1, "k": -1, "\033[5~": -available, "\033[6~": available}[key]
            elif selected and key in ("\033[A", "\033[B", "\033[C", "\033[D"):
                step = {"\033[A": -4, "\033[B": 4, "\033[C": 1, "\033[D": -1}[key]
                candidates = [slot for slot in by_slot if (slot - selected) * step > 0]
                if abs(step) == 4:
                    candidates = [slot for slot in candidates if slot % 4 == selected % 4]
                if candidates:
                    selected = min(candidates, key=lambda slot: abs(slot - selected))
                    top = ((selected - 1) // 4) * block_height
                    if top < offset or top >= offset + available:
                        offset = top
            elif not select_session and selected and key == "A":
                agent = by_slot[selected]
                toggle_dim(agent.pane, agent.dimmed, agent.stale)
            elif key in ("\r", "\n"):
                target = selected
            elif len(key) == 1 and key in "123456789":
                target = int(key)
            if target in by_slot:
                agent = by_slot[target]
                if select_session:
                    if agent.pi_id and agent.worktree and alive(agent.owner):
                        return {"session_id": agent.pi_id, "worktree": agent.worktree, "name": agent.name}
                    notice = "Run /reload in that Pi session, then select it again."
                else:
                    jump(agent, client)
                    return
    finally:
        output.write("\033[0m\033[?7h\033[?25h")
        output.flush()
        if saved_tty:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved_tty)


if __name__ == "__main__":
    try:
        if sys.argv[1:2] == ["--popup"]:
            open_popup(*sys.argv[2:])
        elif sys.argv[1:2] == ["--toggle-dim"]:
            toggle_pane_dim(sys.argv[2])
        elif sys.argv[1:2] == ["--select-session"]:
            selected = main(select_session=True)
            if selected:
                print(json.dumps(selected))
        else:
            main()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
