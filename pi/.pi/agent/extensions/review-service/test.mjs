import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { execFileSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { PassThrough } from "node:stream";
import { mkdtempSync, writeFileSync, rmSync, readFileSync, existsSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, parse } from "node:path";
import { ReviewService, atomicJson, checkEditTarget, readJson } from "./service.mjs";

const directory = mkdtempSync(join(process.env.TMPDIR || tmpdir(), "review-service-"));
const children = [];
const published = [];
let forks = 0;
let ready = false;
const service = new ReviewService({
  directory, cwd: directory, limit: 2, ready: () => ready,
  forkSession: (path) => { forks++; const file = join(path, "session.jsonl"); writeFileSync(file, "{}"); return file; },
  publish: (message) => published.push(message),
  spawnWorker: (command, args, options) => {
    assert.equal(command, "pi");
    assert(args.includes("--review-worker"));
    assert.deepEqual(args[args.indexOf("--tools") + 1].split(","), ["read", "grep", "find", "ls", "review_source", "ask_user_question", "edit"]);
    assert.equal(options.env.TMUX_PANE, undefined);
    assert.equal(options.env.TMUX, undefined);
    assert.equal(options.env.PI_PROGRAM_STATUS, undefined);
    assert.equal(options.env.PI_REVIEW_WORKER, "1");
    const child = new EventEmitter();
    child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
    child.commands = [];
    child.stdin.on("data", (value) => child.commands.push(JSON.parse(String(value))));
    child.kill = () => {};
    child.event = (event) => child.stdout.write(JSON.stringify(event) + "\n");
    child.done = (body) => {
      child.event({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: body }], stopReason: "stop" } });
      child.event({ type: "agent_settled" });
      child.emit("close", 0);
    };
    children.push(child);
    return child;
  },
});
const request = (comment, id) => {
  const value = { comment_id: comment, request_id: id, prompt: `Question ${id}` };
  atomicJson(join(directory, "agent-requests", `${id}.json`), value);
  return value;
};
const artifact = (value) => readJson(service.artifact(value));
try {
  const a = request("a", "request-1");
  const b = request("b", "request-2");
  const c = request("c", "request-3");
  service.tick();
  assert.equal(children.length, 0, "questions wait for a complete parent context instead of forking an unfinished tool call");
  assert(published.some((message) => message.includes("Question request-3")), "the main agent knows queued questions before workers start");
  ready = true;
  service.tick();
  assert.equal(children.length, 2, "independent threads run concurrently with bounded concurrency");
  assert.equal(forks, 2);
  assert.equal(artifact(a).status, "pending", "dispatch is not evidence of investigation");
  children[0].event({ type: "agent_start" });
  children[0].event({ type: "message_update", assistantMessageEvent: { type: "text_delta", delta: "A\u2028B" } });
  assert.equal(artifact(a).body, "A\u2028B", "JSON framing preserves Unicode separators");
  children[0].event({ type: "tool_execution_start", toolName: "read", args: { path: "src/main.rs" } });
  assert.match(artifact(a).activity, /src\/main.rs/);
  children[0].event({ type: "extension_ui_request", id: "input-1", method: "confirm", title: "Continue?" });
  assert.equal(artifact(a).status, "blocked");
  children[1].event({ type: "agent_start" });
  assert.equal(artifact(b).status, "running", "a blocked thread does not block another");
  atomicJson(join(directory, "agent-controls", `${a.request_id}.json`), { id: "wrong", confirmed: true });
  service.tick();
  assert.equal(children[0].commands.length, 1, "unrelated UI replies are ignored");
  atomicJson(join(directory, "agent-controls", `${a.request_id}.json`), { id: "input-1", confirmed: false });
  service.tick();
  assert.deepEqual(children[0].commands[1], { id: "input-1", confirmed: false, type: "extension_ui_response" });
  children[0].event({ type: "extension_ui_request", id: "input-2", method: "input", title: "First?" });
  children[0].event({ type: "extension_ui_request", id: "input-3", method: "input", title: "Second?" });
  atomicJson(join(directory, "agent-controls", `${a.request_id}.json`), { id: "input-2", value: "one" });
  service.tick();
  assert.equal(artifact(a).status, "blocked", "answering one dialog must not clear another");
  assert.equal(artifact(a).input.id, "input-3");
  atomicJson(join(directory, "agent-controls", `${a.request_id}.json`), { id: "input-3", cancelled: true });
  service.tick();
  children[0].event({ type: "agent_end" });
  assert.equal(artifact(a).status, "running", "agent_end is not final completion");
  const finished = service.active.get("a");
  children[0].done("Answer A");
  atomicJson(join(directory, "agent-controls", `${a.request_id}.json`), { action: "cancel" });
  service.control(finished);
  assert.equal(artifact(a).body, "Answer A");
  assert.equal(artifact(a).status, "completed");
  service.tick();
  assert.equal(children.length, 3, "the next queued thread starts when capacity is available");
  const follow = request("a", "request-4");
  children[1].done("Answer B");
  service.tick();
  assert.equal(children.length, 4);
  assert.equal(forks, 3, "follow-up resumes the existing thread session");
  children[3].done("Follow-up A");
  assert.equal(artifact(follow).status, "completed");
  atomicJson(join(directory, "agent-controls", `${c.request_id}.json`), { action: "cancel" });
  service.tick();
  assert.equal(artifact(c).status, "cancelled");
  children[2].emit("close", 0);
  const failed = request("d", "request-5");
  service.tick();
  children.at(-1).event({ type: "message_end", message: { role: "assistant", stopReason: "error", errorMessage: "provider unavailable" } });
  assert.equal(artifact(failed).status, "failed");
  assert.match(artifact(failed).error, /provider unavailable/);
  children.at(-1).emit("close", 1);
  const exited = request("e", "request-6");
  service.tick();
  children.at(-1).stderr.write("startup failed");
  children.at(-1).emit("close", 1);
  assert.equal(artifact(exited).status, "failed");
  assert(published.some((message) => message.includes("Question request-1")));
  assert(published.some((message) => message.includes("Answer A")));
  assert(!published.some((message) => message.includes("A\u2028B")), "only completed answers enter the main context");
  const cancelled = request("f", "request-7");
  atomicJson(join(directory, "agent-controls", `${cancelled.request_id}.json`), { action: "cancel" });
  const count = children.length;
  service.tick();
  assert.equal(children.length, count, "cancelling queued work must not launch a model");
  assert.equal(artifact(cancelled).status, "cancelled");
  assert.equal(JSON.parse(readFileSync(join(directory, "review-service.json"))).cwd, directory);
  const closing = [request("g", "request-8"), request("h", "request-9"), request("i", "request-10")];
  service.tick();
  service.close();
  for (const value of closing) assert.equal(artifact(value).status, "failed", "shutdown stops active and queued work; reopening must not silently replay it");
  console.log("review-service: parallelism, resume, streaming, UI routing, cancellation and failures passed");
} finally {
  service.close();
  for (const child of children) child.emit("close", 0);
  rmSync(directory, { recursive: true, force: true });
}

const guideDirectory = mkdtempSync(join(process.env.TMPDIR || tmpdir(), "review-guide-"));
const guidePrompts = [];
const guideService = new ReviewService({
  directory: guideDirectory, cwd: guideDirectory,
  forkSession: () => { throw new Error("Guide updates must not fork a worker"); },
  publish: () => {}, sendGuide: (prompt) => guidePrompts.push(prompt),
});
const base = "a".repeat(40), head = "b".repeat(40);
const guideRequest = (id, action = "generate", body) => {
  atomicJson(join(guideDirectory, "guide-requests", `${id}.json`), { request_id: id, root: guideDirectory, base_oid: base, head_oid: head, action, body });
};
const guideResult = (id) => readJson(join(guideDirectory, "guide-replies", `${id}.json`));
const validGuide = { context: { base_oid: base, head_oid: head }, summary: "Explain the changed gate", diagram: ["before -> after"], core_code: [{ code: ["if ready && fresh { dispatch(); }"] }] };
try {
  guideRequest("guide-01");
  guideRequest("guide-02", "refine", "Show the failure branch\nand preserve source names.");
  guideService.tick();
  assert.equal(guidePrompts.length, 1, "guide updates are serialized in the main session");
  assert.equal(guideResult("guide-01").status, "queued");
  assert(guidePrompts[0].startsWith("/skill:pr-human-review-guide"));
  for (const text of [base, head, "code-diagram", "core-code-extractor", "core_code", "agent-replies", "Do not edit review state", "guide.json.tmp", "review-hunks.json", "exactly one", "semantic chunk", "Neovim owns read progress"]) assert(guidePrompts[0].includes(text));
  guideService.startGuide("An unrelated main-session prompt");
  guideService.completeGuide();
  assert.equal(guideResult("guide-01").status, "queued", "an unrelated main turn cannot complete the guide request");
  guideService.startGuide(guidePrompts[0]);
  assert.equal(guideResult("guide-01").status, "running");
  atomicJson(join(guideDirectory, "guide.json"), validGuide);
  guideService.completeGuide();
  assert.equal(guideResult("guide-01").status, "completed");
  guideService.tick();
  assert.equal(guidePrompts.length, 2);
  assert(guidePrompts[1].includes("Show the failure branch\nand preserve source names."), "refinement preserves multiline user feedback");
  guideService.startGuide(guidePrompts[1]);
  atomicJson(join(guideDirectory, "guide.json"), { ...validGuide, context: { base_oid: base, head_oid: "c".repeat(40) } });
  guideService.completeGuide();
  assert.equal(guideResult("guide-02").status, "failed", "a different boundary is never reported as an updated guide");
  guideRequest("guide-03"); guideService.tick(); guideService.startGuide(guidePrompts.at(-1));
  atomicJson(join(guideDirectory, "guide.json"), { ...validGuide, core_code: [] });
  guideService.completeGuide();
  assert.match(guideResult("guide-03").error, /core code/, "a diagram-only artifact cannot satisfy a code-centered guide request");
  guideRequest("guide-04"); guideService.tick(); guideService.startGuide(guidePrompts.at(-1));
  atomicJson(join(guideDirectory, "guide.json"), validGuide);
  guideService.guideMessage({ role: "assistant", stopReason: "error", errorMessage: "provider unavailable" });
  guideService.completeGuide();
  assert.match(guideResult("guide-04").error, /provider unavailable/, "an old valid guide cannot hide a failed model run");
  guideRequest("guide-05"); guideService.tick(); guideService.startGuide(guidePrompts.at(-1));
  guideService.completeGuide(true);
  assert.match(guideResult("guide-05").error, /cancelled/);
  guideRequest("guide-06"); guideRequest("guide-07", "refine", "Keep the route top-down.");
  guideService.tick(); guideService.close();
  assert.equal(guideResult("guide-06").status, "failed");
  assert.equal(guideResult("guide-07").status, "failed", "closing the main session retires queued guide requests too");
  console.log("review-service: main-session guide generation, refinement, revisions, errors and shutdown passed");
} finally {
  guideService.close();
  rmSync(guideDirectory, { recursive: true, force: true });
}

let sdk = dirname(realpathSync(execFileSync("which", ["pi"], { encoding: "utf8" }).trim()));
while (!existsSync(join(sdk, "dist/core/extensions/loader.js"))) {
  assert.notEqual(sdk, parse(sdk).root, "Cannot locate installed Pi SDK");
  sdk = dirname(sdk);
}
const { loadExtensions } = await import(pathToFileURL(join(sdk, "dist/core/extensions/loader.js")));
const loaded = await loadExtensions([fileURLToPath(new URL("index.ts", import.meta.url))], process.cwd());
assert.deepEqual(loaded.errors, [], "the actual installed Pi loader accepts the extension");
const extension = loaded.extensions[0];
loaded.runtime.flagValues.set("review-worker", true);
let activeTools;
loaded.runtime.setActiveTools = (names) => { activeTools = names; };
const title = process.title;
for (const handler of extension.handlers.get("session_start")) await handler({}, { mode: "rpc" });
assert.equal(process.title, "pi-review-worker", "workers retain a distinct process identity even when Pi replaces argv");
process.title = title;
assert.deepEqual(activeTools, ["read", "grep", "find", "ls", "review_source", "ask_user_question", "edit"]);
const source = extension.tools.get("review_source").definition;
const previousHead = process.env.PI_REVIEW_HEAD;
try {
  const head = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
  process.env.PI_REVIEW_HEAD = head;
  const pinned = execFileSync("git", ["show", `${head}:PLUGINS.md`], { encoding: "utf8" }).split("\n")[39];
  const result = await source.execute("source", { path: "PLUGINS.md", offset: 40, limit: 1 }, undefined, undefined, { cwd: process.cwd() });
  assert(result.content[0].text.includes(`40: ${pinned}`), "source inspection reads Git objects, not the potentially different checkout");
  await assert.rejects(source.execute("source", { path: "../outside" }, undefined, undefined, { cwd: process.cwd() }), /repository-relative/);
} finally {
  if (previousHead === undefined) delete process.env.PI_REVIEW_HEAD;
  else process.env.PI_REVIEW_HEAD = previousHead;
}
for (const handler of extension.handlers.get("tool_call")) {
  assert.equal((await handler({ toolName: "bash" }, {})).block, true);
  assert.equal((await handler({ toolName: "write" }, {})).block, true);
  assert.equal((await handler({ toolName: "codemode" }, {})).block, true);
  assert.equal(await handler({ toolName: "read" }, {}), undefined);
  assert.equal(await handler({ toolName: "ask_user_question" }, {}), undefined);
}
for (const handler of extension.handlers.get("before_agent_start")) {
  assert.match((await handler({ systemPrompt: "Original" }, {})).systemPrompt, /Answer questions without editing/);
}
const editRoot = mkdtempSync(join(process.env.TMPDIR || tmpdir(), "review-edit-"));
const gitEdit = (...args) => execFileSync("git", args, { cwd: editRoot, encoding: "utf8" }).trim();
try {
  gitEdit("init", "-q");
  writeFileSync(join(editRoot, "README.md"), "Before\n");
  gitEdit("add", "README.md");
  gitEdit("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
    "-c", "core.hooksPath=/dev/null", "commit", "-qm", "Fixture");
  const head = gitEdit("rev-parse", "HEAD");
  assert.throws(() => checkEditTarget(editRoot, "f".repeat(40), "README.md"), /does not match/);
  assert.throws(() => checkEditTarget(editRoot, head, "../README.md"), /repository-relative/);
  assert.throws(() => checkEditTarget(editRoot, head, "guide.json"), /review artifacts/);
  writeFileSync(join(editRoot, "README.md"), "Before\nLocal work\n");
  writeFileSync(join(editRoot, "other.md"), "Untracked\n");
  process.env.PI_REVIEW_HEAD = head;
  for (const handler of extension.handlers.get("tool_call")) {
    const ctx = { cwd: editRoot };
    assert((await handler({ toolName: "edit", input: { path: "other.md" } }, ctx)).block);
    assert((await handler({ toolName: "bash" }, ctx)).block);
    const input = { path: "README.md", edits: [{ oldText: "Before", newText: "After" }] };
    assert.equal(await handler({ toolName: "edit", input }, ctx), undefined);
    const { createEditTool } = await import(pathToFileURL(join(sdk, "dist/index.js")));
    await createEditTool(editRoot).execute("fixture", input);
    assert.equal(readFileSync(join(editRoot, "README.md"), "utf8"), "After\nLocal work\n");
    assert.equal(gitEdit("show", "HEAD:README.md"), "Before");
    assert.equal(await handler({ toolName: "edit", input }, ctx), undefined, "follow-ups can edit the file again");
  }
} finally {
  if (previousHead === undefined) delete process.env.PI_REVIEW_HEAD;
  else process.env.PI_REVIEW_HEAD = previousHead;
  process.title = title;
  rmSync(editRoot, { recursive: true, force: true });
}
loaded.runtime.flagValues.set("review-worker", false);
for (const handler of extension.handlers.get("tool_call")) assert.equal(await handler({ toolName: "write" }, {}), undefined);
const mainDirectory = mkdtempSync(join(process.env.TMPDIR || tmpdir(), "review-main-"));
const mainCalls = [];
loaded.runtime.sendUserMessage = (content, options) => mainCalls.push({ content, options });
const mainContext = { mode: "tui", cwd: mainDirectory, isIdle: () => false, ui: { setStatus() {}, notify() {} } };
try {
  const requests = join(mainDirectory, "guide-requests");
  // Start the service before publishing, just as Neovim connects to the review.
  await extension.commands.get("review-service").handler(mainDirectory, mainContext);
  atomicJson(join(requests, "guide-main.json"), { request_id: "guide-main", root: mainDirectory, action: "generate", base_oid: base, head_oid: head });
  await new Promise((resolve) => setTimeout(resolve, 600));
  assert.equal(mainCalls.length, 1);
  assert.deepEqual(mainCalls[0].options, { deliverAs: "followUp", expandPromptTemplates: true }, "guide generation queues a main-session turn without steering its current work");
  for (const handler of extension.handlers.get("before_agent_start")) await handler({ prompt: "Current unrelated main run", systemPrompt: "Main" }, mainContext);
  assert.equal(readJson(join(mainDirectory, "guide-status.json")).status, "queued");
  // Queued follow-ups enter through message_start without a second before_agent_start.
  for (const handler of extension.handlers.get("message_start")) await handler({ message: { role: "user", content: [{ type: "text", text: mainCalls[0].content }] } }, mainContext);
  assert.equal(readJson(join(mainDirectory, "guide-status.json")).status, "running");
  atomicJson(join(mainDirectory, "guide.json"), validGuide);
  for (const handler of extension.handlers.get("agent_settled")) await handler({ aborted: false }, mainContext);
  assert.equal(readJson(join(mainDirectory, "guide-status.json")).status, "completed");
} finally {
  for (const handler of extension.handlers.get("session_shutdown")) await handler({}, mainContext);
  rmSync(mainDirectory, { recursive: true, force: true });
}
console.log("review-service: real extension loading, main guide dispatch and fail-closed worker tools passed");
// SETUP: Import the current board without starting tmux or its interactive UI.
const snapshot = "10 1 bash bash\n20 10 pi pi --name main\n30 1 bash bash\n40 30 pi pi --mode rpc --review-worker --session child\n50 1 bash bash\n60 50 pi-review-worker pi-review-worker\n";
const inspectAncestors = `
import runpy, sys
from unittest.mock import patch
board = runpy.run_path("tmux/.tmux/pi-agent-board.py")
with patch("subprocess.check_output", return_value=sys.stdin.read()):
    print("\\n".join(sorted(board["pi_ancestors"]())))
`;
// TEST: Supply ordinary Pi, flagged workers and workers with a rewritten process title.
const visible = execFileSync("python3", ["-c", inspectAncestors], { input: snapshot, encoding: "utf8" }).trim().split("\n");
// VERIFY: Workers cannot register either themselves or their host as another board entry.
assert(visible.includes("20") && visible.includes("10"), "normal Pi panes remain discoverable");
assert(!["30", "40", "50", "60"].some((pid) => visible.includes(pid)));
console.log("review-service: Agent Board child-session exclusion passed");
