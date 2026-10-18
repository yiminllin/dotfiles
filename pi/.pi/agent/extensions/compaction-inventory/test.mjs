import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, realpathSync } from "node:fs";
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { dirname, join, parse } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";

let sdk = dirname(realpathSync(execFileSync("which", ["pi"], { encoding: "utf8" }).trim()));
while (!existsSync(join(sdk, "dist/core/extensions/loader.js"))) {
  assert.notEqual(sdk, parse(sdk).root, "Cannot locate installed Pi SDK");
  sdk = dirname(sdk);
}
const { loadExtensions } = await import(pathToFileURL(join(sdk, "dist/core/extensions/loader.js")));
const source = fileURLToPath(new URL("index.ts", import.meta.url));
const usage = { input: 10, output: 5, cacheRead: 0, cacheWrite: 0, totalTokens: 15, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
const manyPaths = Array.from({ length: 130 }, (_, i) => `src/historical-subsystem/file-${i}.rs`);

async function fixture(t) {
  const loaded = await loadExtensions([source], process.cwd());
  assert.deepEqual(loaded.errors, []);
  loaded.runtime.getThinkingLevel = () => "medium";
  const settings = { retry: { enabled: true, maxRetries: 2, baseDelayMs: 0, maxAgentDelayMs: 0 } };
  loaded.runtime.getSettings = () => structuredClone(settings);
  const handler = loaded.extensions[0].handlers.get("session_before_compact")[0];
  await mkdir(join(process.cwd(), ".pi"), { recursive: true });
  const cwd = await mkdtemp(join(process.cwd(), ".pi/compaction-test-"));
  t.after(() => rm(cwd, { recursive: true, force: true }));
  const requests = [], notices = [];
  const ctx = {
    cwd,
    model: { id: "offline", provider: "test", api: "test", reasoning: true, maxTokens: 16384 },
    ui: { notify: (...args) => notices.push(args) },
    sessionManager: { getSessionId: () => "test-session" },
    modelRegistry: {
      streamSimple(model, context, options) {
        requests.push({ model, context, options });
        return { result: async () => ({ content: [{ type: "text", text: "## Goal\nContinue current work." }], stopReason: "stop", usage }) };
      },
    },
  };
  const event = {
    signal: new AbortController().signal,
    branchEntries: [],
    customInstructions: "Preserve the pending request and authorization limits.",
    preparation: {
      firstKeptEntryId: "retained-message",
      tokensBefore: 230000,
      messagesToSummarize: [{ role: "user", content: "Keep current authorization limits.", timestamp: 1 }],
      turnPrefixMessages: [],
      isSplitTurn: false,
      fileOps: { read: new Set(manyPaths), written: new Set(), edited: new Set(["src/current.rs"]) },
      settings: { enabled: true, reserveTokens: 16384, keepRecentTokens: 20000 },
    },
  };
  return { ctx, event, requests, notices, settings, call: () => handler(event, ctx) };
}

test("externalizes large inventories with real Pi compaction and unchanged recent boundary", async (t) => {
  const f = await fixture(t);
  f.event.preparation.previousSummary = "## Goal\nContinue.\n<read-files>\nold-list-only.rs\n</read-files>";
  const original = structuredClone(f.event.preparation);
  const { compaction: result } = await f.call();
  assert.equal(result.firstKeptEntryId, original.firstKeptEntryId);
  assert.equal(result.tokensBefore, original.tokensBefore);
  assert.deepEqual(result.usage, usage);
  assert.deepEqual(f.event.preparation, original);
  assert.doesNotMatch(result.summary, /<read-files>|<modified-files>|file-129.rs/);
  assert.match(result.summary, /not current Git status/);
  const path = result.details.inventory.path;
  assert.ok(path.startsWith(join(f.ctx.cwd, ".pi/compaction-inventories/")));
  assert.ok(result.summary.includes(path));
  const inventory = JSON.parse(await readFile(path, "utf8"));
  assert.equal(inventory.cwd, f.ctx.cwd);
  assert.equal(inventory.sessionId, "test-session");
  assert.deepEqual(inventory.readFiles, [...manyPaths].sort());
  assert.deepEqual(inventory.modifiedFiles, ["src/current.rs"]);
  assert.doesNotMatch(JSON.stringify(f.requests), /old-list-only.rs/);
  assert.match(JSON.stringify(f.requests), /Preserve the pending request/);
  assert.equal(f.requests[0].options.reasoning, "medium");
  assert.equal(f.requests[0].options.cacheRetention, "none");
});

test("repeated compaction restores cumulative metadata and replaces old references", async (t) => {
  const f = await fixture(t);
  const first = (await f.call()).compaction;
  f.event.branchEntries = [{ type: "compaction", fromHook: true, details: first.details }];
  f.event.preparation.previousSummary = first.summary;
  f.event.preparation.fileOps = { read: new Set(["new.rs"]), written: new Set([manyPaths[0]]), edited: new Set() };
  const second = (await f.call()).compaction;
  assert.ok(second.details.readFiles.includes("new.rs"));
  assert.ok(second.details.readFiles.includes(manyPaths[1]));
  assert.ok(!second.details.readFiles.includes(manyPaths[0]));
  assert.deepEqual(second.details.modifiedFiles, [manyPaths[0], "src/current.rs"].sort());
  assert.ok(!second.summary.includes(first.details.inventory.path));
  assert.equal((second.summary.match(/<historical-file-inventory>/g) || []).length, 1);
  assert.ok(!JSON.stringify(f.requests.at(-1)).includes(first.details.inventory.path));
});

test("split turns use both normal summaries without summarizing retained messages", async (t) => {
  const f = await fixture(t);
  f.event.preparation.isSplitTurn = true;
  f.event.preparation.turnPrefixMessages = [{ role: "user", content: "Earlier part of the current turn", timestamp: 2 }];
  const result = (await f.call()).compaction;
  assert.equal(f.requests.length, 2);
  assert.match(JSON.stringify(f.requests[1]), /Earlier part of the current turn/);
  assert.match(result.summary, /Turn Context \(split turn\)/);
  assert.equal(result.firstKeptEntryId, "retained-message");
  assert.equal(result.usage.output, usage.output * 2);
});

test("small inventories and virtual models use the default path", async (t) => {
  const f = await fixture(t);
  f.event.preparation.fileOps.read.clear();
  assert.equal(await f.call(), undefined);
  f.event.preparation.fileOps.read = new Set(manyPaths);
  f.ctx.model.api = "pi-virtual";
  assert.equal(await f.call(), undefined);
  assert.equal(f.requests.length, 0);
  assert.deepEqual(await readdir(f.ctx.cwd), []);
});

function failResponses(f, failures, errorMessage = "terminated") {
  const stream = f.ctx.modelRegistry.streamSimple;
  f.ctx.modelRegistry.streamSimple = (...args) => {
    const response = stream(...args);
    return { result: async () => {
      const message = await response.result();
      if (failures-- > 0) return { ...message, stopReason: "error", errorMessage };
      return message;
    } };
  };
}

test("transient model failure retries with effective settings and saves one inventory", async (t) => {
  const f = await fixture(t);
  failResponses(f, 1);
  const { compaction } = await f.call();
  assert.equal(f.requests.length, 2);
  assert.equal(compaction.firstKeptEntryId, "retained-message");
  assert.equal(f.notices.length, 1);
  assert.match(f.notices[0][0], /Compaction retry 1\/2/);
  assert.equal((await readdir(join(f.ctx.cwd, ".pi/compaction-inventories"))).length, 1);
});

test("retry exhaustion, disabled retries, and permanent errors follow Pi policy", async (t) => {
  for (const mode of ["exhausted", "disabled", "permanent"]) {
    const f = await fixture(t);
    if (mode === "disabled") f.settings.retry.enabled = false;
    failResponses(f, Infinity, mode === "permanent" ? "Invalid API key" : "terminated");
    assert.deepEqual(await f.call(), { cancel: true }, mode);
    assert.equal(f.requests.length, mode === "exhausted" ? 3 : 1, mode);
    assert.deepEqual(await readdir(f.ctx.cwd), [], mode);
  }
});

test("default retry limits apply and cancellation interrupts backoff", async (t) => {
  const f = await fixture(t);
  delete f.settings.retry;
  const controller = new AbortController();
  f.event.signal = controller.signal;
  failResponses(f, Infinity);
  f.ctx.ui.notify = (...args) => {
    f.notices.push(args);
    controller.abort();
  };
  assert.deepEqual(await f.call(), { cancel: true });
  assert.equal(f.requests.length, 1);
  assert.match(f.notices[0][0], /Compaction retry 1\/3 in 2s/);
  assert.deepEqual(await readdir(f.ctx.cwd), []);
});

test("terminal model, cancellation, and storage failures do not start an extra compaction", async (t) => {
  for (const failure of ["model", "length", "abort", "storage"]) {
    const f = await fixture(t);
    const controller = new AbortController();
    f.event.signal = controller.signal;
    const stream = f.ctx.modelRegistry.streamSimple;
    f.ctx.modelRegistry.streamSimple = (...args) => {
      const response = stream(...args);
      return { result: async () => {
        if (failure === "model") throw new Error("offline failure");
        const message = await response.result();
        if (failure === "length") message.stopReason = "length";
        if (failure === "abort") controller.abort();
        return message;
      } };
    };
    if (failure === "storage") await writeFile(join(f.ctx.cwd, ".pi"), "not a directory");
    assert.deepEqual(await f.call(), { cancel: true }, failure);
    assert.equal(f.requests.length, 1, failure);
    if (failure !== "storage") assert.deepEqual(await readdir(f.ctx.cwd), [], failure);
  }
});
