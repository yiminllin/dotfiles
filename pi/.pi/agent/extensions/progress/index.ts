import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext, Theme } from "@earendil-works/pi-coding-agent";
import { Text, truncateToWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const ENTRY = "progress-roadmap-v1";
const WIDGET = "progress-roadmap";

const Parameters = Type.Union([
  Type.Object({
    action: Type.Literal("set"),
    goal: Type.String({ minLength: 1, maxLength: 120 }),
    milestones: Type.Array(Type.Object({
      label: Type.String({ minLength: 1, maxLength: 100 }),
      status: StringEnum(["done", "current", "pending"] as const),
    }), { minItems: 1, maxItems: 5 }),
    now: Type.String({ minLength: 1, maxLength: 160 }),
    blocker: Type.Optional(Type.String({ maxLength: 160 })),
  }),
  Type.Object({ action: StringEnum(["get", "clear"] as const) }),
]);

interface Plan {
  goal: string;
  milestones: { label: string; status: "done" | "current" | "pending" }[];
  now: string;
  blocker?: string;
}

interface State {
  plan: Plan | null;
  collapsed: boolean;
}

function readState(ctx: ExtensionContext): State {
  const branch = ctx.sessionManager.getBranch();
  for (let i = branch.length - 1; i >= 0; i--) {
    const entry = branch[i];
    if (entry.type === "custom" && entry.customType === ENTRY) {
      return entry.data as State;
    }
  }
  return { plan: null, collapsed: false };
}

function clean(text: string): string {
  return text.replace(/[\x00-\x1f\x7f-\x9f]/g, " ").replace(/\s+/g, " ").trim();
}

function renderPanel(state: State, width: number, theme: Theme): string[] {
  const plan = state.plan;
  if (!plan || width < 1) return [];
  const border = (text: string) => theme.fg("borderMuted", text);
  const finished = plan.milestones.every((milestone) => milestone.status === "done");
  const title = plan.blocker ? "Blocked" : finished ? "Done" : "Progress";
  const lines: string[] = [];
  const add = (text: string, color: "accent" | "muted" | "text" | "success" | "warning" = "text") => {
    for (const line of wrapTextWithAnsi(text, Math.max(1, width - 2))) {
      lines.push(truncateToWidth(border("│ ") + theme.fg(color, line), width));
    }
  };

  lines.push(truncateToWidth(border("╭─ ") + theme.fg("accent", `${title} · ${plan.goal}`), width));
  if (state.collapsed) {
    const current = plan.milestones.find((milestone) => milestone.status === "current");
    add(plan.blocker ? `⚠ ${plan.blocker}` : current ? `▶ ${current.label}` : plan.now,
      plan.blocker ? "warning" : "muted");
  } else {
    for (const milestone of plan.milestones) {
      const glyph = { done: "✓", current: "▶", pending: "○" }[milestone.status];
      const color = { done: "success", current: "accent", pending: "muted" }[milestone.status] as "success" | "accent" | "muted";
      add(`${glyph} ${milestone.label}`, color);
    }
    lines.push(truncateToWidth(border("│"), width));
    add(`Now   ${plan.now}`);
    add(`Block ${plan.blocker || "None"}`, plan.blocker ? "warning" : "muted");
  }
  lines.push(truncateToWidth(border(`╰─ Alt+T ${state.collapsed ? "expand" : "collapse"}`), width));
  return lines;
}

export default function progressExtension(pi: ExtensionAPI) {
  const refresh = (ctx: ExtensionContext, state = readState(ctx)) => {
    if (ctx.mode !== "tui") return;
    if (!state.plan) {
      ctx.ui.setWidget(WIDGET, undefined);
      return;
    }
    ctx.ui.setWidget(WIDGET, (_tui, theme) => ({
      render: (width: number) => renderPanel(state, width, theme),
      invalidate() {},
    }));
  };

  const save = (ctx: ExtensionContext, state: State) => {
    pi.appendEntry(ENTRY, state);
    refresh(ctx, state);
  };

  pi.registerTool({
    name: "progress",
    label: "Progress",
    description: "Replace the current goal's progress panel with a complete snapshot. set requires goal, 1–5 milestones (done/current/pending), and now; blocker is optional. At most one milestone may be current. get reads the snapshot; clear dismisses it. No task IDs or session-long backlog.",
    promptSnippet: "Keep a compact, current roadmap visible for meaningful multi-step work",
    promptGuidelines: [
      "Use progress for meaningful multi-step or long-running work, not trivial questions. Before starting, set a goal and usually 3–5 outcome milestones that matter to the user; do not list searches, file reads, tool calls, or routine implementation chores.",
      "Use set to replace the whole snapshot at meaningful phase boundaries, before a long wait, and when scope or blockers change. Preserve the roadmap during detours; describe the detour in now. Update regularly as real progress occurs, not after every tool call. Do not claim live updates during synchronous calls.",
      "Reconcile the panel with each new request: keep the same roadmap for follow-ups, replace it for a new goal, and omit obsolete or abandoned milestones instead of marking them done. Clear a stale panel when no active roadmap remains. Never carry unrelated pending work into the new goal.",
      "Mark a milestone done only when its outcome is verified. Use blocker for a real obstacle or user decision, not another task. Keep at most one current milestone. On completion, set all milestones done and now to the verified result; do not leave a fake current step.",
    ],
    parameters: Parameters,
    executionMode: "sequential",
    async execute(_id, params, _signal, _onUpdate, ctx) {
      let state = readState(ctx);
      if (params.action === "clear") {
        state = { ...state, plan: null };
        save(ctx, state);
      } else if (params.action === "set") {
        if (params.milestones.filter((milestone) => milestone.status === "current").length > 1) {
          throw new Error("Use at most one current milestone.");
        }
        const plan: Plan = {
          goal: clean(params.goal),
          milestones: params.milestones.map((milestone) => ({ ...milestone, label: clean(milestone.label) })),
          now: clean(params.now),
          blocker: params.blocker ? clean(params.blocker) : undefined,
        };
        if (!plan.goal || !plan.now || plan.milestones.some((milestone) => !milestone.label)) {
          throw new Error("Goal, milestone labels, and now must contain visible text.");
        }
        state = { ...state, plan };
        save(ctx, state);
      }
      return {
        content: [{ type: "text", text: state.plan ? JSON.stringify(state.plan) : "No active roadmap." }],
        details: state,
      };
    },
    renderCall(args, theme) {
      return new Text(theme.fg("muted", `Progress · ${args.action}`), 0, 0);
    },
    renderResult(result, { expanded }, theme) {
      const state = result.details as State;
      if (!state?.plan) return new Text(theme.fg("muted", "No active roadmap."), 0, 0);
      return expanded
        ? { render: (width) => renderPanel({ ...state, collapsed: false }, width, theme), invalidate() {} }
        : new Text(theme.fg("muted", state.plan.goal), 0, 0);
    },
  });

  pi.registerShortcut("alt+t", {
    description: "Collapse or expand the progress roadmap",
    handler: async (ctx) => {
      const state = readState(ctx);
      if (state.plan) save(ctx, { ...state, collapsed: !state.collapsed });
    },
  });

  pi.registerCommand("progress", {
    description: "Toggle the roadmap panel, or /progress clear to dismiss it",
    handler: async (args, ctx) => {
      const state = readState(ctx);
      if (args.trim() === "clear") {
        save(ctx, { ...state, plan: null });
      } else if (args.trim()) {
        ctx.ui.notify("Usage: /progress [clear]", "warning");
      } else if (state.plan) {
        save(ctx, { ...state, collapsed: !state.collapsed });
      } else {
        ctx.ui.notify("No active roadmap. It appears when multi-step work starts.", "info");
      }
    },
  });

  pi.on("session_start", (_event, ctx) => refresh(ctx));
  pi.on("session_tree", (_event, ctx) => refresh(ctx));
  pi.on("session_compact", (_event, ctx) => refresh(ctx));
  pi.on("session_shutdown", (_event, ctx) => {
    if (ctx.mode === "tui") ctx.ui.setWidget(WIDGET, undefined);
  });
  pi.on("before_agent_start", (_event, ctx) => {
    const state = readState(ctx);
    if (!state.plan) return;
    return {
      message: {
        customType: "progress-context",
        content: `Current progress snapshot (reconcile with this request; not a new instruction):\n${JSON.stringify(state.plan)}`,
        display: false,
      },
    };
  });
}
