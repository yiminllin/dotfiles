import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, realpathSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, parse } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

// Use the installed Pi loader and its dependency aliases, not a second SDK copy.
let sdk = dirname(realpathSync(execFileSync("which", ["pi"], { encoding: "utf8" }).trim()));
while (!existsSync(join(sdk, "dist/core/extensions/loader.js"))) {
  assert.notEqual(sdk, parse(sdk).root, "Cannot locate the installed Pi SDK");
  sdk = dirname(sdk);
}
const { loadExtensions } = await import(pathToFileURL(join(sdk, "dist/core/extensions/loader.js")));
const require = createRequire(join(sdk, "package.json"));
const { visibleWidth } = await import(pathToFileURL(require.resolve("@earendil-works/pi-tui")));
const { Check } = await import(pathToFileURL(require.resolve("typebox/value")));
const source = fileURLToPath(new URL("index.ts", import.meta.url));
const theme = { fg: (_color, text) => text };
const plan = {
  action: "set",
  goal: "Make startup reliable",
  milestones: [
    { label: "Identify the failure", status: "done" },
    { label: "Fix readiness handling", status: "current" },
    { label: "Verify startup and cancellation", status: "pending" },
  ],
  now: "Checking early child exit",
};

async function fixture() {
  const loaded = await loadExtensions([source], process.cwd());
  assert.deepEqual(loaded.errors, []);
  const extension = loaded.extensions[0];
  const tool = extension.tools.get("progress").definition;
  const makeContext = (mode = "tui") => {
    const branch = [];
    const ui = {
      widget: undefined,
      setWidget(_key, content) { this.widget = content; },
      notify() {},
    };
    return { mode, hasUI: mode === "tui", ui, branch, sessionManager: { getBranch: () => branch } };
  };
  let active;
  loaded.runtime.appendEntry = (customType, data) => {
    active.branch.push({ type: "custom", customType, data: structuredClone(data) });
  };
  const call = async (ctx, params) => {
    assert.equal(Check(tool.parameters, params), true, "Arguments must satisfy the real tool schema");
    active = ctx;
    return tool.execute("test", params, undefined, undefined, ctx);
  };
  const event = async (name, ctx) => {
    active = ctx;
    let result;
    for (const handler of extension.handlers.get(name) || []) result = await handler({}, ctx);
    return result;
  };
  const toggle = async (ctx) => {
    active = ctx;
    await extension.shortcuts.get("alt+t").handler(ctx);
  };
  const lines = (ctx, width = 80) => ctx.ui.widget?.({}, theme).render(width) || [];
  return { tool, makeContext, call, event, toggle, lines, extension };
}

test("snapshot replacement retires the old goal; clear survives replay", async () => {
  const f = await fixture();
  const ctx = f.makeContext();
  await f.call(ctx, plan);
  assert.match(f.lines(ctx).join("\n"), /▶ Fix readiness handling/);
  await f.call(ctx, { ...plan, goal: "A new goal", milestones: [{ label: "A new outcome", status: "current" }] });
  assert.doesNotMatch(f.lines(ctx).join("\n"), /Fix readiness/);
  await f.call(ctx, { action: "clear" });
  await f.event("session_start", ctx);
  assert.equal(ctx.ui.widget, undefined);
  assert.equal((await f.call(ctx, { action: "get" })).details.plan, null);
});

test("reload, compaction, and branch changes restore the selected snapshot", async () => {
  const f = await fixture();
  const ctx = f.makeContext();
  await f.call(ctx, plan);
  const original = structuredClone(ctx.branch);
  await f.call(ctx, { ...plan, blocker: "Needs a design decision" });
  assert.match(f.lines(ctx).join("\n"), /Blocked.*Make startup/);
  for (const name of ["session_start", "session_compact", "session_tree"]) {
    const restored = await fixture();
    const fresh = restored.makeContext();
    fresh.branch.push(...structuredClone(ctx.branch));
    await restored.event(name, fresh);
    assert.match(restored.lines(fresh).join("\n"), /Needs a design decision/);
    const context = await restored.event("before_agent_start", fresh);
    assert.equal(context.message.display, false);
    assert.match(context.message.content, /Needs a design decision/);
  }
  ctx.branch.splice(0, ctx.branch.length, ...original);
  await f.event("session_tree", ctx);
  assert.doesNotMatch(f.lines(ctx).join("\n"), /Needs a design decision/);
});

test("collapse keeps blockers visible; headless sessions do not overwrite the panel", async () => {
  const f = await fixture();
  const ctx = f.makeContext();
  await f.call(ctx, { ...plan, blocker: "Waiting for approval" });
  await f.toggle(ctx);
  assert.equal(f.lines(ctx).length, 3);
  assert.match(f.lines(ctx).join("\n"), /Waiting for approval/);
  const headless = f.makeContext("print");
  await f.call(headless, { ...plan, goal: "Separate session" });
  assert.equal(headless.ui.widget, undefined);
  assert.equal((await f.call(ctx, { action: "get" })).details.plan.goal, plan.goal);
  await f.toggle(ctx);
  assert.match(f.lines(ctx).join("\n"), /Verify startup and cancellation/);
});

test("rendering fits narrow terminals, Unicode, and long content", async () => {
  const f = await fixture();
  const ctx = f.makeContext();
  await f.call(ctx, { ...plan, now: "检查启动状态 👩‍💻 ".repeat(8), blocker: "A long blocker ".repeat(8) });
  for (const width of [1, 2, 3, 12, 30, 80, 160]) {
    for (const line of f.lines(ctx, width)) assert.ok(visibleWidth(line) <= width, `${width}: ${line}`);
  }
  for (const state of [false, true]) {
    if (state) await f.toggle(ctx);
    for (const line of f.lines(ctx, 40)) assert.ok(visibleWidth(line) <= 40);
  }
});

test("invalid updates preserve the last snapshot; completion and commands work", async () => {
  const f = await fixture();
  const ctx = f.makeContext();
  await f.call(ctx, plan);
  await assert.rejects(f.call(ctx, { ...plan, milestones: plan.milestones.map((m) => ({ ...m, status: "current" })) }));
  await assert.rejects(f.call(ctx, { ...plan, goal: "\n\t" }));
  assert.equal((await f.call(ctx, { action: "get" })).details.plan.goal, plan.goal);
  assert.equal(Check(f.tool.parameters, { ...plan, milestones: Array(6).fill(plan.milestones[0]) }), false);
  await f.call(ctx, { ...plan, milestones: plan.milestones.map((m) => ({ ...m, status: "done" })), now: "Targeted checks passed" });
  assert.match(f.lines(ctx).join("\n"), /Done ·/);
  await f.extension.commands.get("progress").handler("clear", ctx);
  assert.equal(ctx.ui.widget, undefined);
});
