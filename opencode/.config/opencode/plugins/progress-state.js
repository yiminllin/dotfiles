const fs = require("fs/promises")
const path = require("path")

const DEFAULT_PROGRESS_DIR = "/tmp/opencode-progress"
const PLUGIN_STATE_SUBDIR = path.join("plugins", "progress-state")
const SCHEMA_VERSION = 1
const MAX_TEXT_LENGTH = 240
const MAX_SUMMARY_LENGTH = 160
const MAX_ARRAY_ITEMS = 20
const MAX_OBJECT_KEYS = 40
const MAX_DEPTH = 4

const SECRET_KEY_RE = /api[-_]?key|authorization|cookie|credential|password|private[-_]?key|refresh[-_]?token|secret|session[-_]?token|token/i
const SECRET_ASSIGNMENT_RE = new RegExp(
  String.raw`\b(api[-_]?key|authorization|cookie|credential|password|private[-_]?key|refresh[-_]?token|secret|session[-_]?token|token)\b\s*([=:])\s*(['"]?)[^\s;&,'"}]+`,
  "gi",
)
const SECRET_JSON_RE = new RegExp(
  String.raw`(['"]?(?:api[-_]?key|authorization|cookie|credential|password|private[-_]?key|refresh[-_]?token|secret|session[-_]?token|token)['"]?\s*:\s*['"]?)[^\s,}'"]+`,
  "gi",
)
const SECRET_FLAG_RE = /(--(?:api[-_]?key|authorization|cookie|credential|password|private[-_]?key|refresh[-_]?token|secret|session[-_]?token|token)(?:=|\s+))(['"]?)[^\s;&,'"]+/gi
const BEARER_VALUE_RE = /\bBearer\s+[^\s;&,'"]+/gi
const URL_USERINFO_RE = /(\b[a-z][a-z0-9+.-]*:\/\/)[^/@\s]+@/gi

async function progressStatePlugin(input = {}) {
  const context = pluginContext(input)
  return {
    "tool.execute.before": async (hookInput = {}, hookOutput = {}) => {
      void writeToolEntry(context, hookInput, hookOutput, "running")
    },
    "tool.execute.after": async (hookInput = {}, hookOutput = {}) => {
      void writeToolEntry(context, hookInput, hookOutput, finalStatus(hookOutput))
    },
  }
}

function pluginContext(input) {
  const directory = typeof input.directory === "string" ? input.directory : undefined
  return {
    directory,
    stateDir: path.join(progressRoot(), PLUGIN_STATE_SUBDIR),
    startTimes: new Map(),
  }
}

function progressRoot() {
  return process.env.OPENCODE_PROGRESS_STATE_DIR || process.env.OPENCODE_PROGRESS_DIR || DEFAULT_PROGRESS_DIR
}

async function writeToolEntry(context, hookInput, hookOutput, status) {
  try {
    const now = new Date().toISOString()
    const tool = toolName(hookInput.tool)
    const sessionID = stringifyId(hookInput.sessionID) || "unknown-session"
    const callID = stringifyId(hookInput.callID) || `${tool}-${now}`
    const entryKey = `${sessionID}:${callID}`
    const startedAt = context.startTimes.get(entryKey) || now
    if (status === "running") {
      context.startTimes.set(entryKey, startedAt)
    } else {
      context.startTimes.delete(entryKey)
    }

    const filePath = path.join(context.stateDir, `${safeFileName(`${sessionID}-${callID}`)}.json`)
    const resultSummary = summarizeResult(hookOutput)
    const argsSummary = summarizeArgs(hookInput.args || hookOutput.args)
    const current = status === "running" ? argsSummary : resultSummary || argsSummary

    const entry = removeEmpty({
      id: `plugin:tool:${sessionID}:${callID}`,
      source: "plugin",
      label: `${tool} tool call`,
      goal: `${tool} tool call`,
      phase: "runtime tool",
      current,
      status,
      mode: "indeterminate",
      updated_at: now,
      started_at: startedAt,
      cwd: context.directory,
      last_output: status === "running" ? undefined : resultSummary,
      tool: {
        name: tool,
        call_id: callID,
      },
      session: {
        id: sessionID,
        location: context.directory,
      },
    })
    const payload = {
      schema_version: SCHEMA_VERSION,
      kind: "opencode_plugin_progress_entry",
      updated_at: now,
      entry,
    }
    await writeJsonBestEffort(filePath, payload)
  } catch (_error) {
    // Progress state is observational UI data; hook failures must not affect tools.
  }
}

function summarizeArgs(args) {
  if (args === undefined || args === null) {
    return "arguments unavailable"
  }
  return truncate(`args: ${summarizeValue(args)}`, MAX_SUMMARY_LENGTH)
}

function summarizeResult(hookOutput) {
  if (!hookOutput || typeof hookOutput !== "object") {
    return "result unavailable"
  }
  const pieces = []
  if (hookOutput.title) {
    pieces.push(`title=${summarizeValue(hookOutput.title)}`)
  }
  if (hookOutput.output !== undefined && hookOutput.output !== null) {
    pieces.push(`output=${summarizeValue(hookOutput.output)}`)
  }
  const metadata = hookOutput.metadata
  if (metadata && typeof metadata === "object") {
    const status = metadataStatus(metadata)
    if (status) {
      pieces.push(status)
    }
    if (metadata.error) {
      pieces.push(`error=${summarizeValue(metadata.error)}`)
    }
  }
  return pieces.length > 0 ? truncate(`result: ${pieces.join(" | ")}`, MAX_SUMMARY_LENGTH) : "result unavailable"
}

function metadataStatus(metadata) {
  for (const key of ["returncode", "return_code", "exit", "exit_code", "exitCode", "status"]) {
    if (metadata[key] !== undefined && metadata[key] !== null) {
      return `${key}=${summarizeValue(metadata[key])}`
    }
  }
  if (metadata.timed_out || metadata.timedOut) {
    return "timed_out=true"
  }
  return undefined
}

function summarizeValue(value) {
  const scrubbed = redactValue(value)
  if (typeof scrubbed === "string") {
    return scrubbed
  }
  try {
    return truncate(JSON.stringify(scrubbed), MAX_TEXT_LENGTH)
  } catch (_error) {
    return "[unserializable]"
  }
}

function redactValue(value, depth = 0) {
  if (value === null || value === undefined) {
    return value
  }
  if (typeof value === "string") {
    return scrubText(value)
  }
  if (typeof value !== "object") {
    return value
  }
  if (depth >= MAX_DEPTH) {
    return "[truncated]"
  }
  if (Array.isArray(value)) {
    const items = value.slice(0, MAX_ARRAY_ITEMS).map((item) => redactValue(item, depth + 1))
    if (value.length > MAX_ARRAY_ITEMS) {
      items.push(`... ${value.length - MAX_ARRAY_ITEMS} more items`)
    }
    return items
  }

  const redacted = {}
  const entries = Object.entries(value).slice(0, MAX_OBJECT_KEYS)
  for (const [key, nestedValue] of entries) {
    redacted[key] = SECRET_KEY_RE.test(key) ? "<redacted>" : redactValue(nestedValue, depth + 1)
  }
  const extra = Object.keys(value).length - entries.length
  if (extra > 0) {
    redacted._truncated = `${extra} more keys`
  }
  return redacted
}

function scrubText(value) {
  return truncate(
    String(value)
      .replace(URL_USERINFO_RE, "$1<redacted>@")
      .replace(BEARER_VALUE_RE, "Bearer <redacted>")
      .replace(SECRET_JSON_RE, "$1<redacted>")
      .replace(SECRET_ASSIGNMENT_RE, "$1$2<redacted>")
      .replace(SECRET_FLAG_RE, "$1<redacted>"),
    MAX_TEXT_LENGTH,
  )
}

function finalStatus(hookOutput) {
  return hasExplicitFailure(hookOutput) || hasExplicitFailure(hookOutput && hookOutput.metadata) || hasExplicitFailure(hookOutput && hookOutput.output)
    ? "failed"
    : "succeeded"
}

function hasExplicitFailure(value) {
  if (!value || typeof value !== "object") {
    return false
  }
  if (value.error || value.timed_out || value.timedOut) {
    return true
  }
  for (const key of ["returncode", "return_code", "exit", "exit_code", "exitCode", "status"]) {
    if (isFailedStatus(value[key])) {
      return true
    }
  }
  return false
}

function isFailedStatus(value) {
  if (typeof value === "number") {
    return value !== 0
  }
  if (typeof value !== "string") {
    return false
  }
  const normalized = value.toLowerCase()
  if (/^-?\d+$/.test(normalized)) {
    return Number(normalized) !== 0
  }
  return ["error", "errored", "failed", "failure", "timed_out", "timeout"].includes(normalized)
}

function toolName(rawTool) {
  if (typeof rawTool === "string" && rawTool) {
    return scrubText(rawTool)
  }
  if (rawTool && typeof rawTool === "object") {
    return scrubText(rawTool.name || rawTool.id || "unknown")
  }
  return "unknown"
}

function stringifyId(value) {
  if (value === undefined || value === null || value === "") {
    return undefined
  }
  return scrubText(value)
}

function safeFileName(value) {
  const safe = String(value).replace(/[^A-Za-z0-9_.-]+/g, "-").replace(/^[-._]+|[-._]+$/g, "") || "tool-call"
  return safe.slice(0, 180)
}

async function writeJsonBestEffort(filePath, payload) {
  try {
    await fs.mkdir(path.dirname(filePath), { recursive: true })
    const tmpPath = path.join(path.dirname(filePath), `.${path.basename(filePath)}.${process.pid}.${Date.now()}.tmp`)
    await fs.writeFile(tmpPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8")
    await fs.rename(tmpPath, filePath)
  } catch (_error) {
    // Progress state is observational UI data; hook failures must not affect tools.
  }
}

function removeEmpty(value) {
  const clean = {}
  for (const [key, nestedValue] of Object.entries(value)) {
    if (nestedValue === undefined || nestedValue === null) {
      continue
    }
    if (typeof nestedValue === "object" && !Array.isArray(nestedValue)) {
      const nestedClean = removeEmpty(nestedValue)
      if (Object.keys(nestedClean).length > 0) {
        clean[key] = nestedClean
      }
      continue
    }
    clean[key] = nestedValue
  }
  return clean
}

function truncate(value, width) {
  const collapsed = String(value).replace(/\s+/g, " ").trim()
  if (collapsed.length <= width) {
    return collapsed
  }
  return `${collapsed.slice(0, Math.max(0, width - 3))}...`
}

module.exports = progressStatePlugin
module.exports.default = progressStatePlugin
