import { execFileSync, spawn } from "node:child_process";
import { mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync, existsSync, realpathSync, lstatSync } from "node:fs";
import { join } from "node:path";

export function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return undefined;
  }
}
export function atomicJson(path, value) {
  writeFileSync(`${path}.tmp`, JSON.stringify(value));
  renameSync(`${path}.tmp`, path);
}
const THREAD_TERMINAL = ["completed", "failed", "cancelled"];
const GUIDE_TERMINAL = ["completed", "failed"];
const safeId = (value) => typeof value === "string" && /^[\w.-]+$/.test(value);
const textOf = (message) => (message?.content ?? []).filter((part) => part.type === "text").map((part) => part.text).join("\n");

export const REVIEW_TOOLS = ["read", "grep", "find", "ls", "review_source", "ask_user_question", "edit"];

export function checkEditTarget(root, head, path) {
  if (typeof path !== "string" || path !== path.trim() || path.includes("\\") || /[\u0000-\u001f]/.test(path)
    || path.startsWith("@") || path.split("/").some((part) => !part || [".", "..", ".git"].includes(part.toLowerCase()))
    || !/^[a-f0-9]{40,64}$/.test(head ?? "")) {
    throw new Error("Edit locally requires a repository-relative file and a pinned head");
  }
  if (["guide.json", "diffview-review.json", "review-hunks.json", "review-service.json"].includes(path.split("/").at(-1))) {
    throw new Error("Review threads cannot modify review artifacts");
  }
  const git = (...args) => execFileSync("git", ["--no-optional-locks", "--literal-pathspecs", ...args], {
    cwd: root, encoding: "utf8", timeout: 5000, stdio: ["ignore", "pipe", "pipe"],
  });
  if (git("rev-parse", "HEAD").trim() !== head) {
    throw new Error("The checkout does not match the reviewed head. Open the matching checkout before editing.");
  }
  const file = join(realpathSync(root), path);
  if (realpathSync(file) !== file || !lstatSync(file).isFile() || lstatSync(file).nlink !== 1
    || !/^100(?:644|755) [a-f0-9]+ 0\t/.test(git("ls-files", "--stage", "-z", "--", path))) {
    throw new Error("Edit locally requires a regular tracked file, not a link");
  }
}

export function guidePrompt(directory, request) {
  const guide = join(directory, "guide.json");
  return [
    "/skill:pr-human-review-guide",
    `Guide request: ${request.request_id}`,
    request.action === "refine" ? "Refine the existing human review guide using the feedback below." : "Generate or update the human review guide from the pinned source evidence.",
    `Repository: ${request.root}`,
    `Pinned comparison: ${request.base_oid}..${request.head_oid}`,
    `Guide: ${guide}`,
    `The user authorizes creating and updating exactly ${guide} and ${guide}.tmp for this requested guide, including outside the repository. Write atomically via that temporary file and rename; do not ask again for these two paths.`,
    "Use code-explainer to coordinate code-diagram and core-code-extractor. This is an explicit one-shot guide update; do not stop for layout approval.",
    "Make the guide code-centered: goal, verified before/after behavior, source-backed ASCII diagram, minimal representative core code changes, top-down review route, and review focus. Use consistent source identifiers and the same mechanism/revisions in diagrams and snippets. Label excerpts versus simplified code/pseudocode and give source anchors for both sides. Never invent missing source or edges.",
    "Write the same guide.json with summary, behavior_change, diagram, core_code, chunks, files (with reason/suggestions), high_risk, and validation. Read the guide skill's JSON template. Do not substitute a chat-only JSON reply for the file update. Keep full-PR context even when Diffview filters files.",
    `Read ${join(directory, "review-hunks.json")} as the canonical, read-only hunk inventory. Its context must match the pinned comparison. Partition every listed hunk ID into exactly one ordered semantic chunk, including file-level changes. A chunk may span files; separate hunks in a file may belong to different chunks. Do not invent IDs or edit the inventory. Each chunk needs stable id/title, summary, relationship to the overview, dependencies on earlier chunks, local diagram, source-backed core_code, checks, depth (careful/skim), and hunks. Preserve hunk IDs and chunk IDs when refining; Neovim owns read progress. If the inventory is unavailable, report that instead of fabricating a plan.`,

    `Read the existing guide, ${join(directory, "diffview-review.json")}, and completed answers in ${join(directory, "agent-replies")} before refining. Fold in substantive discussion conclusions only after checking them against pinned source. Keep detailed back-and-forth in threads.`,
    `Preserve context.base_oid=${request.base_oid} and context.head_oid=${request.head_oid}, plus still-relevant suggestion IDs. Never change the pinned boundary to a moving branch or remote tip.`,
    "Only this main session owns guide updates. Do not edit review state, source files, Git state, or GitHub. Explain your changes and uncertainty in this visible main session.",
    request.body ? `User feedback:\n${request.body}` : "",
  ].filter(Boolean).join("\n");
}

// One service belongs to one main review session. Workers never own review state.
export class ReviewService {
  constructor({ directory, cwd, forkSession, publish, spawnWorker = spawn, limit = 3, now = () => Date.now(), ready = () => true, sendGuide }) {
    Object.assign(this, { directory, cwd, forkSession, publish, spawnWorker, limit, now, ready, sendGuide });
    this.active = new Map();
    this.closed = false;
    for (const name of ["agent-requests", "agent-replies", "agent-controls", "agent-threads", "guide-requests", "guide-replies"]) mkdirSync(join(directory, name), { recursive: true });
  }
  artifact(request) { return join(this.directory, "agent-replies", `${request.comment_id}--${request.request_id}.json`); }
  status(run, status, extra = {}) {
    if (status === "running" && run.inputs?.size) status = "blocked";
    if (status === "blocked") extra.input = run.inputs?.values().next().value;
    atomicJson(this.artifact(run.request), {
      comment_id: run.request.comment_id, request_id: run.request.request_id,
      author: "pi", created_at: new Date(this.now()).toISOString(), status,
      body: run.body ?? "", activity: run.activity ?? "", ...extra,
    });
  }
  tick() {
    if (this.closed) return;
    atomicJson(join(this.directory, "review-service.json"), { pid: process.pid, cwd: this.cwd, updated_at: this.now() });
    this.dispatchGuide();
    for (const run of this.active.values()) this.control(run);
    const files = readdirSync(join(this.directory, "agent-requests")).filter((name) => name.endsWith(".json")).sort();
    for (const filename of files) {
      const request = readJson(join(this.directory, "agent-requests", filename));
      if (!request || !safeId(request.comment_id) || !safeId(request.request_id) || typeof request.prompt !== "string") continue;
      const previous = readJson(this.artifact(request));
      if (THREAD_TERMINAL.includes(previous?.status)) continue;
      if (!previous) {
        this.status({ request }, "pending");
        this.publish(`Review question ${request.comment_id}: ${request.prompt}`);
      }
      const active = this.active.get(request.comment_id);
      const control = readJson(join(this.directory, "agent-controls", `${request.request_id}.json`));
      if (control?.action === "cancel" && active?.request.request_id !== request.request_id) {
        this.status({ request }, "cancelled");
        continue;
      }
      if (active || this.active.size >= this.limit || !this.ready()) continue;
      this.start(request);
    }
  }
  guideStatus(request, status, extra = {}) {
    const result = { request_id: request.request_id, base_oid: request.base_oid, head_oid: request.head_oid, status, updated_at: this.now(), ...extra };
    atomicJson(join(this.directory, "guide-replies", `${request.request_id}.json`), result);
    atomicJson(join(this.directory, "guide-status.json"), result);
  }
  dispatchGuide() {
    if (!this.sendGuide || this.guideActive) return;
    for (const name of readdirSync(join(this.directory, "guide-requests")).filter((name) => name.endsWith(".json")).sort()) {
      const request = readJson(join(this.directory, "guide-requests", name));
      if (!request || !safeId(request.request_id)) continue;
      if (GUIDE_TERMINAL.includes(readJson(join(this.directory, "guide-replies", `${request.request_id}.json`))?.status)) continue;
      if (request.root !== this.cwd || !["generate", "refine"].includes(request.action)
        || !/^[a-f0-9]{40,64}$/.test(request.base_oid ?? "") || !/^[a-f0-9]{40,64}$/.test(request.head_oid ?? "")) {
        this.guideStatus(request, "failed", { error: "Guide request has an invalid repository, action, or pinned boundary" });
        continue;
      }
      this.guideActive = { request, started: false };
      this.guideStatus(request, "queued");
      try {
        this.sendGuide(guidePrompt(this.directory, request));
      } catch (error) {
        this.guideStatus(request, "failed", { error: error.message });
        this.guideActive = undefined;
      }
      break;
    }
  }
  startGuide(prompt) {
    if (this.guideActive && prompt.includes(`Guide request: ${this.guideActive.request.request_id}`)) {
      this.guideActive.started = true;
      this.guideStatus(this.guideActive.request, "running");
    }
  }
  guideMessage(message) {
    if (this.guideActive?.started && message.role === "assistant") {
      this.guideActive.error = ["error", "aborted", "length"].includes(message.stopReason) ? (message.errorMessage || message.stopReason) : undefined;
    }
  }
  completeGuide(aborted = false) {
    if (!this.guideActive?.started) return;
    const guide = readJson(join(this.directory, "guide.json"));
    const request = this.guideActive.request;
    let error = aborted ? "Guide update was cancelled" : this.guideActive.error;
    if (!error && (guide?.context?.base_oid !== request.base_oid || guide?.context?.head_oid !== request.head_oid)) {
      error = "The guide is missing, invalid, or has a different pinned boundary";
    }
    const hasText = (value) => typeof value === "string"
      ? Boolean(value.trim())
      : Array.isArray(value) && value.some((line) => typeof line === "string" && line.trim());
    if (!error && (!hasText(guide.summary) || !hasText(guide.diagram)
      || !Array.isArray(guide.core_code) || !guide.core_code.some((block) => hasText(block?.code)))) {
      error = "The guide needs a goal, code diagram, and core code changes";
    }
    this.guideStatus(request, error ? "failed" : "completed", error ? { error } : {});
    this.guideActive = undefined;
  }
  start(request) {
    const run = { request, body: "", activity: "Starting review session", buffer: "", settled: false, stderr: "", inputs: new Map() };
    this.active.set(request.comment_id, run);
    try {
      const control = readJson(join(this.directory, "agent-controls", `${request.request_id}.json`));
      if (control?.action === "cancel") {
        run.settled = true;
        this.status(run, "cancelled");
        this.active.delete(request.comment_id);
        return;
      }
      const threadDirectory = join(this.directory, "agent-threads", request.comment_id);
      mkdirSync(threadDirectory, { recursive: true });
      const manifestPath = join(threadDirectory, "thread.json");
      let session = readJson(manifestPath)?.session;
      if (!session || !existsSync(session)) {
        session = this.forkSession(threadDirectory);
        atomicJson(manifestPath, { session });
      }
      const env = { ...process.env, PI_REVIEW_WORKER: "1", PI_REVIEW_BASE: request.base_oid ?? "", PI_REVIEW_HEAD: request.head_oid ?? "" };
      for (const key of ["TMUX", "TMUX_PANE", "PI_PROGRAM_STATUS"]) delete env[key];
      run.child = this.spawnWorker("pi", ["--mode", "rpc", "--review-worker", "--session", session, "--tools", REVIEW_TOOLS.join(",")], {
        cwd: this.cwd, env, stdio: ["pipe", "pipe", "pipe"],
      });
      run.child.stdin.on("error", (error) => this.fail(run, error.message));
      run.child.stdout.setEncoding("utf8");
      run.child.stderr.setEncoding("utf8");
      run.child.stdout.on("data", (chunk) => {
        run.buffer += chunk;
        let end;
        while ((end = run.buffer.indexOf("\n")) !== -1) {
          const line = run.buffer.slice(0, end).replace(/\r$/, "");
          run.buffer = run.buffer.slice(end + 1);
          try {
            this.event(run, JSON.parse(line));
          } catch (error) {
            this.fail(run, `Invalid worker event: ${error.message}`);
          }
        }
      });
      run.child.stderr.on("data", (chunk) => { run.stderr = (run.stderr + chunk).slice(-4000); });
      run.child.on("error", (error) => this.fail(run, error.message));
      run.child.on("close", () => {
        if (!run.settled) this.fail(run, run.stderr || "Review worker exited before completing its reply");
        clearTimeout(run.killTimer);
        this.active.delete(request.comment_id);
      });
      this.status(run, "pending");
      this.send(run, { id: request.request_id, type: "prompt", message: request.prompt });
    } catch (error) {
      this.fail(run, error.message);
      if (!run.child) this.active.delete(request.comment_id);
    }
  }
  send(run, value) {
    if (!run.child?.stdin?.destroyed) run.child.stdin.write(`${JSON.stringify(value)}\n`);
  }
  stop(run) {
    run.child?.stdin.end();
    run.killTimer = setTimeout(() => run.child?.kill("SIGTERM"), 2000);
    run.killTimer.unref?.();
  }
  fail(run, error) {
    if (run.settled) return;
    run.settled = true;
    try {
      this.status(run, "failed", { error });
      this.publish(`Review thread ${run.request.comment_id} failed: ${error}`);
    } finally {
      this.stop(run);
    }
  }
  event(run, event) {
    if (run.settled) return;
    if (event.type === "response" && event.success === false) return this.fail(run, event.error || "Pi rejected the request");
    if (event.type === "agent_start") this.status(run, "running");
    if (event.type === "message_update" && event.assistantMessageEvent?.type === "text_delta") {
      run.body += event.assistantMessageEvent.delta;
      this.status(run, "running");
    }
    if (event.type === "tool_execution_start") {
      const args = event.args ?? {};
      run.activity = `${event.toolName}: ${args.path ?? args.pattern ?? "inspecting code"}`;
      this.status(run, "running");
    }
    if (event.type === "message_end" && event.message?.role === "assistant") {
      if (["error", "aborted"].includes(event.message.stopReason)) return this.fail(run, event.message.errorMessage || event.message.stopReason);
      run.body = textOf(event.message);
      this.status(run, "running");
    }
    if (event.type === "extension_ui_request") {
      if (["select", "confirm", "input", "editor"].includes(event.method)) {
        run.inputs.set(event.id, event);
        this.status(run, "blocked");
      } else if (!["notify", "setStatus", "setWidget", "setTitle", "set_editor_text"].includes(event.method)) {
        this.fail(run, `Unsupported worker interaction: ${event.method}`);
      }
    }
    if (event.type === "agent_settled") {
      if (!run.body.trim()) return this.fail(run, "Pi finished without an answer");
      run.settled = true;
      this.status(run, "completed", { activity: "Reply ready" });
      this.publish(`Review thread ${run.request.comment_id} replied:\n${run.body}`);
      this.stop(run);
    }
  }
  control(run) {
    if (run.settled) return;
    const path = join(this.directory, "agent-controls", `${run.request.request_id}.json`);
    const control = readJson(path);
    const serialized = JSON.stringify(control);
    if (!control || run.control === serialized) return;
    run.control = serialized;
    if (control.action === "cancel") {
      run.settled = true;
      this.status(run, "cancelled", { activity: "Cancelled" });
      this.publish(`Review thread ${run.request.comment_id} was cancelled`);
      this.send(run, { type: "abort" });
      this.stop(run);
    } else if (run.inputs.has(control.id)) {
      this.send(run, { ...control, type: "extension_ui_response", id: control.id });
      run.inputs.delete(control.id);
      this.status(run, "running");
    }
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    for (const run of this.active.values()) {
      try { this.fail(run, "Main review session closed; retry to resume this thread"); }
      catch { /* A failed artifact write must not leave the other workers running. */ }
    }
    for (const name of readdirSync(join(this.directory, "agent-requests"))) {
      if (!name.endsWith(".json")) continue;
      const request = readJson(join(this.directory, "agent-requests", name));
      if (!request || !safeId(request.comment_id) || !safeId(request.request_id)) continue;
      const artifact = readJson(this.artifact(request));
      if (!THREAD_TERMINAL.includes(artifact?.status)) {
        this.status({ request }, "failed", { error: "Main review session closed; retry to resume this thread" });
      }
    }
    for (const name of readdirSync(join(this.directory, "guide-requests"))) {
      if (!name.endsWith(".json")) continue;
      const request = readJson(join(this.directory, "guide-requests", name));
      if (!request || !safeId(request.request_id)) continue;
      const result = readJson(join(this.directory, "guide-replies", `${request.request_id}.json`));
      if (!GUIDE_TERMINAL.includes(result?.status)) {
        this.guideStatus(request, "failed", { error: "Main review session closed; request the guide update again" });
      }
    }
    this.guideActive = undefined;
    atomicJson(join(this.directory, "review-service.json"), { pid: process.pid, cwd: this.cwd, updated_at: 0 });
  }
}
