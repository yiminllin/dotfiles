import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { compact, SettingsManager, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

interface InventoryDetails {
  readFiles: string[];
  modifiedFiles: string[];
  inventory?: { version: 1; path: string };
}

function withoutInventories(summary: string): string {
  return summary.replace(
    /<(read-files|modified-files|historical-file-inventory)>[\s\S]*?<\/\1>/g,
    "",
  ).trim();
}

function inventoryReference(path: string): string {
  return `<historical-file-inventory>\nHistorical read/modified paths: ${JSON.stringify(path)}\nRead only when tracing earlier work. This is not current Git status or proof that files still exist.\n</historical-file-inventory>`;
}

export default function (pi: ExtensionAPI) {
  pi.on("session_before_compact", async (event, ctx) => {
    const model = ctx.model;
    // Virtual selections require Pi's internal routing; leave those to the default path.
    if (!model || model.api === "pi-virtual") return;

    const previous = event.branchEntries.findLast((entry) => entry.type === "compaction");
    const previousDetails = previous?.details as InventoryDetails | undefined;
    const fileOps = {
      read: new Set(event.preparation.fileOps.read),
      written: new Set(event.preparation.fileOps.written),
      edited: new Set(event.preparation.fileOps.edited),
    };
    // Carry standard file metadata even when Pi skips extension-generated checkpoints.
    if (Array.isArray(previousDetails?.readFiles)) {
      for (const path of previousDetails.readFiles) fileOps.read.add(path);
    }
    if (Array.isArray(previousDetails?.modifiedFiles)) {
      for (const path of previousDetails.modifiedFiles) fileOps.written.add(path);
    }
    const modified = new Set([...fileOps.written, ...fileOps.edited]);
    const readFiles = [...fileOps.read].filter((path) => !modified.has(path)).sort();
    const modifiedFiles = [...modified].sort();
    const externalize = !!previousDetails?.inventory || JSON.stringify({ readFiles, modifiedFiles }).length >= 4000;
    // Model-specific reserves set native trigger thresholds, not summary output budgets.
    const settings = SettingsManager.inMemory(pi.getSettings());
    const summaryReserve = settings.getCompactionSettings().reserveTokens;

    const path = externalize ? join(ctx.cwd, ".pi", "compaction-inventories", `${randomUUID()}.json`) : undefined;
    const reference = path ? inventoryReference(path) : undefined;
    const preparation = {
      ...event.preparation,
      fileOps,
      settings: { ...event.preparation.settings, reserveTokens: summaryReserve },
      previousSummary: externalize && event.preparation.previousSummary
        ? `${withoutInventories(event.preparation.previousSummary)}\n\n${reference}`
        : event.preparation.previousSummary,
    };
    const instructions = [
      event.customInstructions,
      externalize && "Do not enumerate historical file inventories. Keep exact paths needed for current work; the full historical inventory is referenced separately.",
    ].filter(Boolean).join("\n\n");

    try {
      // Reuse Pi's normal summary generation, split-turn handling, usage, and cut point.
      // Authentication remains inside the registry; compact's apiKey argument is unused.
      const result = await compact(
        preparation, model, "", undefined, instructions, event.signal, pi.getThinkingLevel(),
        (selectedModel, context, options) => ctx.modelRegistry.streamSimple(selectedModel, context, {
          maxTokens: options?.maxTokens,
          reasoning: options?.reasoning,
          signal: options?.signal,
          cacheRetention: "none",
          sessionId: options?.sessionId,
        }),
        undefined,
        settings.getRetrySettings(),
        {
          onRetryScheduled: (attempt, maxRetries, delayMs) => {
            ctx.ui.notify(`Compaction retry ${attempt}/${maxRetries} in ${Math.round(delayMs / 1000)}s`, "warning");
          },
        },
      );
      if (event.signal.aborted) return { cancel: true };
      const details: InventoryDetails = { readFiles, modifiedFiles };
      if (path) {
        const inventory = {
          version: 1,
          kind: "historical-file-inventory",
          sessionId: ctx.sessionManager.getSessionId(),
          createdAt: new Date().toISOString(),
          cwd: ctx.cwd,
          note: "Historical tool-access inventory, not current Git status. Relative paths are relative to cwd. Files may no longer exist. No source files or evidence were copied.",
          readFiles,
          modifiedFiles,
        };
        await mkdir(join(ctx.cwd, ".pi", "compaction-inventories"), { recursive: true });
        await writeFile(path, `${JSON.stringify(inventory, null, 2)}\n`, { flag: "wx", mode: 0o600 });
        result.summary = `${withoutInventories(result.summary)}\n\n${reference}`;
        details.inventory = { version: 1, path };
      }
      return { compaction: { ...result, details } };
    } catch (error) {
      // After normal retries, do not fall through to a second compaction attempt.
      if (!event.signal.aborted) {
        ctx.ui.notify(`Compaction failed; no checkpoint saved: ${error instanceof Error ? error.message : String(error)}`, "error");
      }
      return { cancel: true };
    }
  });
}
