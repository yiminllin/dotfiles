import { execFileSync } from "node:child_process";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

function latestMessageTime(session: ExtensionContext["sessionManager"]): string {
  // The current branch is already in memory; skip metadata and tool results.
  for (let entry = session.getLeafEntry(); entry; entry = entry.parentId ? session.getEntry(entry.parentId) : undefined) {
    if (entry.type !== "message") continue;
    const { role, timestamp } = entry.message;
    if (role === "user" || role === "assistant") {
      const time = timestamp > 0 ? timestamp : Date.parse(entry.timestamp);
      if (Number.isSafeInteger(time) && time > 0) return String(time);
    }
  }
  return "";
}

// Custom dialogs do not set Pi's OSC 7501 blocked state.
export default function (pi: ExtensionAPI) {
  const pane = process.env.TMUX_PANE;
  if (!pane) return;
  const pending = new Set<string>();
  let active = false;

  function publish() {
    if (!active) return;
    try {
      execFileSync("tmux", ["set-option", "-pt", pane, "@pi_agent_input_wait", pending.size ? String(process.pid) : ""], {
        stdio: "ignore", timeout: 1000,
      });
    } catch {
      // Board availability must not affect dialog decisions.
    }
  }

  function update(source: string, id: unknown, waiting: unknown) {
    if (!active || typeof id !== "string" || typeof waiting !== "boolean") return;
    const key = `${source}:${id}`;
    if (waiting) pending.add(key);
    else if (!pending.delete(key)) return;
    publish();
  }

  pi.events.on("permissions:ui_prompt", (data) => update("permission", (data as { requestId?: unknown })?.requestId, true));
  pi.events.on("permissions:decision", (data) => update("permission", (data as { requestId?: unknown })?.requestId, false));
  pi.events.on("rpiv:ask-user:blocked", (data) => {
    const event = data as { toolCallId?: unknown; active?: unknown } | null;
    update("question", event?.toolCallId, event?.active);
  });

  pi.on("session_start", (_event, ctx) => {
    active = ctx.mode === "tui";
    pending.clear();
    if (active) {
      try {
        execFileSync("tmux", [
          "set-option", "-pt", pane, "@pi_session_id", ctx.sessionManager.getSessionId(), ";",
          "set-option", "-pt", pane, "@pi_session_owner", String(process.pid), ";",
          "set-option", "-pt", pane, "@pi_session_cwd", ctx.sessionManager.getCwd(), ";",
          "set-option", "-pt", pane, "@pi_agent_last_message", latestMessageTime(ctx.sessionManager),
        ], { stdio: "ignore", timeout: 1000 });
      } catch {
        // Task navigation must not prevent Pi startup.
      }
    }
    publish();
  });
  const publishMessageTime = (time: string) => {
    try {
      execFileSync("tmux", ["set-option", "-pt", pane, "@pi_agent_last_message", time], {
        stdio: "ignore", timeout: 1000,
      });
    } catch {
      // Board availability must not affect conversations.
    }
  };

  pi.on("message_end", ({ message }) => {
    if (!active || (message.role !== "user" && message.role !== "assistant")) return;
    if (Number.isSafeInteger(message.timestamp) && message.timestamp > 0) publishMessageTime(String(message.timestamp));
  });
  pi.on("session_tree", (_event, ctx) => {
    if (active) publishMessageTime(latestMessageTime(ctx.sessionManager));
  });
  pi.on("session_shutdown", () => {
    pending.clear();
    publish();
    if (active) {
      try {
        execFileSync("tmux", [
          "set-option", "-pt", pane, "-u", "@pi_session_id", ";",
          "set-option", "-pt", pane, "-u", "@pi_session_owner", ";",
          "set-option", "-pt", pane, "-u", "@pi_session_cwd", ";",
          "set-option", "-pt", pane, "-u", "@pi_agent_last_message",
        ], { stdio: "ignore", timeout: 1000 });
      } catch {
        // The pane may already be gone.
      }
    }
    active = false;
  });
}
