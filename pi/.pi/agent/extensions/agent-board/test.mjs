import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, realpathSync } from "node:fs";
import { dirname, join, parse } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

let sdk = dirname(realpathSync(execFileSync("which", ["pi"], { encoding: "utf8" }).trim()));
while (!existsSync(join(sdk, "dist/core/extensions/loader.js"))) {
  assert.notEqual(sdk, parse(sdk).root, "Cannot locate the installed Pi SDK");
  sdk = dirname(sdk);
}
const { loadExtensions } = await import(pathToFileURL(join(sdk, "dist/core/extensions/loader.js")));
const { createEventBus } = await import(pathToFileURL(join(sdk, "dist/core/event-bus.js")));
const source = fileURLToPath(new URL("index.ts", import.meta.url));
const progressSource = fileURLToPath(new URL("../progress/index.ts", import.meta.url));

test("progress publishes full snapshots without the dialog bridge", async (t) => {
  const socket = `pi-board-test-${process.pid}`;
  const tmux = (...args) => execFileSync("tmux", ["-L", socket, ...args], { encoding: "utf8" }).trim();
  tmux("-f", "/dev/null", "new-session", "-d", "-s", "test");
  const previous = { TMUX: process.env.TMUX, TMUX_PANE: process.env.TMUX_PANE, PI_REVIEW_WORKER: process.env.PI_REVIEW_WORKER };
  t.after(() => {
    tmux("kill-server");
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  });
  const pane = tmux("display-message", "-p", "#{pane_id}");
  process.env.TMUX = tmux("display-message", "-p", "#{socket_path},#{pid},0");
  process.env.TMUX_PANE = pane;
  delete process.env.PI_REVIEW_WORKER;
  const loaded = await loadExtensions([progressSource], process.cwd());
  assert.deepEqual(loaded.errors, []);
  const branch = [];
  const ctx = { mode: "tui", isIdle: () => true, ui: { setWidget() {} }, sessionManager: { getBranch: () => branch, getSessionId: () => "td-session-test", getCwd: () => process.cwd() } };
  loaded.runtime.appendEntry = (customType, data) => branch.push({ type: "custom", customType, data: structuredClone(data) });
  const extension = loaded.extensions[0];
  const event = async (name) => {
    for (const handler of extension.handlers.get(name) || []) await handler({}, ctx);
  };
  const tool = extension.tools.get("progress").definition;
  const call = (params) => tool.execute("test", params, undefined, undefined, ctx);
  const raw = () => tmux("show-options", "-pqv", "-t", pane, "@pi_agent_progress");
  const snapshot = () => JSON.parse(raw());
  await event("session_start");
  assert.deepEqual(snapshot(), { pid: process.pid, plan: null });
  const plan = { goal: "Ship | the feature", milestones: [
    { label: "Inspect", status: "done" },
    { label: "Implement", status: "current", tasks: [{ label: "Wire events", status: "current" }] },
    { label: "Verify", status: "pending" },
  ], blocker: "Need input" };
  await call({ action: "set", ...plan, now: "Do not expose hidden context" });
  assert.deepEqual(snapshot(), { pid: process.pid, plan });
  await call({ action: "clear" });
  assert.equal(snapshot().plan, null);
  branch.pop();
  await event("session_tree");
  assert.deepEqual(snapshot().plan, plan);
  await event("session_compact");
  assert.deepEqual(snapshot().plan, plan);
  await event("session_shutdown");
  assert.equal(raw(), "");
  await event("session_start");
  assert.deepEqual(snapshot().plan, plan, "Startup restores the selected pin");
  await event("session_shutdown");
  ctx.mode = "json";
  await event("session_start");
  await call({ action: "set", ...plan });
  assert.equal(raw(), "", "Headless sessions cannot overwrite a pane pin");
  ctx.mode = "tui";
  process.env.PI_REVIEW_WORKER = "1";
  await event("session_start");
  assert.equal(raw(), "", "Review workers cannot overwrite the main agent pin");

  delete process.env.PI_REVIEW_WORKER;
  const bus = createEventBus();
  const bridge = await loadExtensions([source], process.cwd(), bus);
  assert.deepEqual(bridge.errors, []);
  const old = 1700000000000;
  const first = { id: "user", parentId: null, type: "message", message: { role: "user", timestamp: old } };
  const toolResult = { id: "tool", parentId: first.id, type: "message", message: { role: "toolResult", timestamp: old + 1 } };
  let leaf = toolResult;
  Object.assign(ctx.sessionManager, {
    getLeafEntry: () => leaf,
    getEntry: (id) => id === first.id ? first : undefined,
  });
  const bridgeEvent = async (name, data = {}) => {
    for (const handler of bridge.extensions[0].handlers.get(name)) await handler(data, ctx);
  };
  const lastMessage = () => tmux("show-options", "-pqv", "-t", pane, "@pi_agent_last_message");
  await bridgeEvent("session_start");
  assert.equal(lastMessage(), String(old));
  const runState = () => tmux("show-options", "-pqv", "-t", pane, "@pi_agent_run_state");
  assert.equal(runState(), "WAIT");
  await bridgeEvent("agent_start");
  assert.equal(runState(), "RUN");
  await bridgeEvent("agent_settled");
  assert.equal(runState(), "WAIT");
  await bridgeEvent("message_end", { message: toolResult.message });
  assert.equal(lastMessage(), String(old));
  await bridgeEvent("message_end", { message: { role: "assistant", timestamp: old + 2 } });
  assert.equal(lastMessage(), String(old + 2));
  await bridgeEvent("session_tree");
  assert.equal(lastMessage(), String(old), "Tree navigation restores the selected branch timestamp");
  leaf = undefined;
  await bridgeEvent("session_tree");
  assert.equal(lastMessage(), "");
  await bridgeEvent("message_end", { message: { role: "user", timestamp: old + 3 } });
  assert.equal(tmux("show-options", "-pqv", "-t", pane, "@pi_session_id"), "td-session-test");
  assert.equal(tmux("show-options", "-pqv", "-t", pane, "@pi_session_owner"), String(process.pid));
  const wait = () => tmux("show-options", "-pqv", "-t", pane, "@pi_agent_input_wait");
  bus.emit("permissions:ui_prompt", { requestId: "p1" });
  bus.emit("rpiv:ask-user:blocked", { toolCallId: "q1", active: true });
  bus.emit("permissions:decision", { requestId: "p1" });
  assert.equal(wait(), String(process.pid));
  bus.emit("rpiv:ask-user:blocked", { toolCallId: "q1", active: false });
  assert.equal(wait(), "");
  await bridgeEvent("session_shutdown");
  assert.equal(lastMessage(), "");
  assert.equal(runState(), "");
  assert.equal(tmux("show-options", "-pqv", "-t", pane, "@pi_session_id"), "");
});
