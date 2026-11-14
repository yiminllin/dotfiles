import { execFileSync } from "node:child_process";
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
  const publishBoard = (ctx: ExtensionContext, state: State | null) => {
    const pane = process.env.TMUX_PANE;
    if (ctx.mode !== "tui" || !pane || process.env.PI_REVIEW_WORKER === "1") return;
    const plan = state?.plan;
    const snapshot = state ? JSON.stringify({
      pid: process.pid,
      plan: plan ? { goal: plan.goal, milestones: plan.milestones, blocker: plan.blocker } : null,
    }) : "";
    try {
      execFileSync("tmux", ["set-option", "-pt", pane, "@pi_agent_progress", snapshot], {
        stdio: "ignore", timeout: 1000,
      });
    } catch {
      // The board shows an unavailable hint if publication fails.
    }
  };

  const refresh = (ctx: ExtensionContext, state = readState(ctx)) => {
    if (ctx.mode !== "tui") return;
    publishBoard(ctx, state);
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
    description: "Pin the high-level session roadmap. set supplies goal (a recognizable session title) and outcome-based milestones (done/current/pending), each with optional tasks. Aim for 3–5 broad outcomes without padding. Use short labels and usually 1–3 immediate tasks, not full procedures. Blockers name actual obstacles, not planning-only constraints. Top-level items are outcome milestones; execution steps belong in tasks. Let milestones evolve with the conversation: rename, merge, split, or reorder them while preserving explicit requirements and meaningful completion state. Reuse and reopen milestones instead of appending repeated execution passes. Only the current milestone's tasks appear. now is hidden context; blocker is optional. At most one milestone and one task per milestone may be current. get reads; clear dismisses. Preserve genuine goals across related replies.",
    promptSnippet: "Pin evolving outcome milestones; fold execution steps into nested tasks",
    promptGuidelines: [
      "Use progress for meaningful multi-step work. Pin a recognizable session title in goal (project/topic plus intended outcome) and genuine high-level outcomes as milestones. Aim for 3–5 broad outcomes, not a chronological activity log; this is a guideline, not a quota or hard limit. Use short labels, usually 3–7 words; do not repeat the session title or combine an entire procedure into one row. Keep distinct deliverables identifiable and preserve their dependencies. Keep every explicitly requested step represented as a milestone or task, not necessarily as a separate top-level row. Infer the plan; ask only when its title or scope is unclear.",
      "Keep the session goal across related replies, but let milestone definitions evolve as the conversation clarifies the work. Rename, merge, split, or reorder milestones when needed to describe the current outcomes; preserve explicit requirements, dependencies, and meaningful completion state, not fixed labels or a row for every past pass. Top-level items are milestones with recognizable outcomes; execution steps belong in milestone.tasks. Reuse and reopen the relevant milestone for repeated planning, implementation, cleanup, validation, restacking, and submission passes. Add a milestone only when the evolving scope needs a separate outcome. Regroup an overgrown roadmap rather than continually appending rows. A small follow-up does not complete the whole roadmap. Replace the roadmap only when the session purpose genuinely changes; ask if that boundary is unclear.",
      "Show only useful immediate steps in milestone.tasks, usually 1–3 tasks; five is a schema limit, not a target. Use short labels, usually 3–7 words. Omit tasks that repeat the milestone, routine formatting/review/checklists, and speculative future procedures; group related checks as focused validation. Keep detailed procedures in conversation or hidden now context. Only the current milestone's tasks appear.",
      "Use progress set only for a meaningful outcome/status change, a useful nested-task change, or a real blocker. Do not refresh for every reply, tool call, or wait. now is optional context and is not shown. Keep completed goals visible; remove abandoned goals rather than marking them done. Clear only when dismissed or no longer relevant.",
      "Mark progress outcomes done only when verified. Keep at most one current milestone and one current task per milestone. Use blocker only for missing input, a decision, or an obstacle that prevents the current work; state it briefly. Planning-only scope and actions not yet authorized are constraints, not blockers unless the current agreed step actually requires that authorization. Keep those constraints in conversation or hidden now context, without treating them as permission to execute. Do not claim live updates during synchronous calls.",
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
    publishBoard(ctx, null);
    if (ctx.mode === "tui") ctx.ui.setWidget(WIDGET, undefined);
  });
  pi.on("before_agent_start", (_event, ctx) => {
    const state = readState(ctx);
    if (!state.plan) return;
    return {
      message: {
        customType: "progress-context",
        content: `Pinned session roadmap (top-level items are outcome milestones, execution steps belong in tasks; let milestones evolve with the conversation by renaming, merging, splitting, or reordering as needed; keep labels short and usually show only 1–3 immediate tasks, not full procedures; aim for 3–5 outcomes without padding; planning-only constraints are not blockers; preserve requirements, dependencies, and meaningful completion state; update only meaningful changes):\n${JSON.stringify(state.plan)}`,
        display: false,
      },
    };
  });
}
