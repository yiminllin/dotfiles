import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext, Theme } from "@earendil-works/pi-coding-agent";
import { Text, truncateToWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const ENTRY = "progress-roadmap-v1";
const WIDGET = "progress-roadmap";

const Task = Type.Object({
  label: Type.String({ minLength: 1, maxLength: 100 }),
  status: StringEnum(["done", "current", "pending"] as const),
});

const Parameters = Type.Union([
  Type.Object({
    action: Type.Literal("set"),
    goal: Type.String({ minLength: 1, maxLength: 120 }),
    milestones: Type.Array(Type.Object({
      label: Type.String({ minLength: 1, maxLength: 100 }),
      status: StringEnum(["done", "current", "pending"] as const),
      tasks: Type.Optional(Type.Array(Task, { maxItems: 5 })),
    }), { minItems: 1 }),
    now: Type.Optional(Type.String({ minLength: 1, maxLength: 160 })),
    blocker: Type.Optional(Type.String({ maxLength: 160 })),
  }),
  Type.Object({ action: StringEnum(["get", "clear"] as const) }),
]);

interface ProgressItem {
  label: string;
  status: "done" | "current" | "pending";
  tasks?: { label: string; status: "done" | "current" | "pending" }[];
}

interface Plan {
  goal: string;
  milestones: ProgressItem[];
  now?: string;
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
  const titleColor = plan.blocker ? "error" : finished ? "success" : "accent";
  const lines: string[] = [];
  const add = (text: string, color: "accent" | "muted" | "text" | "success" | "warning" | "error" = "text") => {
    for (const line of wrapTextWithAnsi(text, Math.max(1, width - 2))) {
      lines.push(truncateToWidth(border("│ ") + theme.fg(color, line), width));
    }
  };

  const addItem = (item: ProgressItem, indent = "") => {
    const glyph = { done: "✓", current: "▶", pending: "○" }[item.status];
    const color = { done: "success", current: "warning", pending: "muted" }[item.status] as "success" | "warning" | "muted";
    add(`${indent}${glyph} ${item.label}`, color);
  };

  lines.push(truncateToWidth(border("╭─ ") + theme.fg(titleColor, plan.goal), width));
  if (state.collapsed) {
    const current = plan.milestones.find((milestone) => milestone.status === "current");
    add(plan.blocker ? `⚠ Blocked: ${plan.blocker}` : current ? `▶ ${current.label}` : finished ? "✓ Done" : "○ Pending",
      plan.blocker ? "error" : current ? "warning" : finished ? "success" : "muted");
  } else {
    for (const milestone of plan.milestones) {
      addItem(milestone);
      if (milestone.status === "current") {
        for (const task of milestone.tasks || []) addItem(task, "  ");
      }
    }
    if (plan.blocker) add(`⚠ Blocked: ${plan.blocker}`, "error");
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
    if (JSON.stringify(readState(ctx)) === JSON.stringify(state)) return;
    pi.appendEntry(ENTRY, state);
    refresh(ctx, state);
  };

  pi.registerTool({
    name: "progress",
    label: "Progress",
    description: "Pin the high-level session roadmap. set supplies goal (a recognizable session title) and the plan's persistent high-level steps (done/current/pending), each with optional tasks. Only the current milestone's tasks appear. now is optional context, not displayed; blocker is optional. At most one milestone and one task per milestone may be current. get reads; clear dismisses. Preserve goals across related replies.",
    promptSnippet: "Pin persistent high-level session goals; nest granular tasks under the current goal",
    promptGuidelines: [
      "For meaningful multi-step work, pin a recognizable session title in goal (project/topic plus intended outcome) and the plan's highest-level steps as milestones. Preserve an existing plan's step count and order: a ten-step plan needs ten visible top-level milestones, not five grouped goals. Infer these from the request; ask the user to confirm only when the title or goals are unclear.",
      "Preserve the title and high-level milestones across related replies, follow-ups, and detours. Completing a small request does not complete the session roadmap. Replace the roadmap only when the session purpose genuinely changes; ask if that boundary is unclear.",
      "Put granular work in optional milestone.tasks, not in top-level milestones. Keep tasks short; only the current milestone's tasks are displayed. Do not list routine reads, searches, or tool calls. Omit tasks when they add no useful information.",
      "Use set only for a meaningful outcome/status change, a useful nested-task change, or a real blocker. Do not refresh for every reply, tool call, or wait. now is optional context and is not shown. Keep completed goals visible; remove abandoned goals rather than marking them done. Clear only when dismissed or no longer relevant.",
      "Mark outcomes done only when verified. Keep at most one current milestone and one current task per milestone. Use blocker for an actual obstacle or user decision. Do not claim live updates during synchronous calls.",
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
          milestones: params.milestones.map((milestone) => ({
            ...milestone,
            label: clean(milestone.label),
            tasks: milestone.tasks?.map((task) => ({ ...task, label: clean(task.label) })),
          })),
          now: params.now ? clean(params.now) : undefined,
          blocker: params.blocker ? clean(params.blocker) : undefined,
        };
        if (!plan.goal || plan.milestones.some((milestone) => !milestone.label || milestone.tasks?.some((task) => !task.label))) {
          throw new Error("Title, milestone labels, and task labels must contain visible text.");
        }
        if (plan.milestones.some((milestone) => (milestone.tasks || []).filter((task) => task.status === "current").length > 1)) {
          throw new Error("Use at most one current task per milestone.");
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
        content: `Pinned session roadmap (preserve title and high-level goals across related requests; nest granular work; update only meaningful changes):\n${JSON.stringify(state.plan)}`,
        display: false,
      },
    };
  });
}
