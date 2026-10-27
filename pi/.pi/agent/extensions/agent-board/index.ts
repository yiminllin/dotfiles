import { execFileSync } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

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
    publish();
  });
  pi.on("session_shutdown", () => {
    pending.clear();
    publish();
    active = false;
  });
}
