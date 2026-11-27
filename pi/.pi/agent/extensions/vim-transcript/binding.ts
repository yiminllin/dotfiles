import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isKeyRelease, matchesKey } from "@earendil-works/pi-tui";

export default function (pi: ExtensionAPI) {
  pi.on("session_start", (_event, ctx) => {
    const previous = ctx.ui.getEditorComponent();
    if (!ctx.hasUI || !previous) return;

    ctx.ui.setEditorComponent((tui, theme, keys) => {
      const editor = previous(tui, theme, keys);
      const viewport = tui as typeof tui & { mode?: string; scrollToBottom?: () => void };
      // pi-vim reports Ex as Normal. Keep Ex and pending Vim commands such as dG intact.
      const vim = editor as typeof editor & {
        getMode?: () => string;
        pendingExCommand?: string | null;
        prefixCount?: string;
        isRepeatRecordingInProgress?: () => boolean;
        isShowingAutocomplete?: () => boolean;
      };
      if (!vim.getMode || !vim.isRepeatRecordingInProgress) return editor;

      const handleInput = editor.handleInput?.bind(editor);
      editor.handleInput = (data) => {
        const mode = vim.getMode?.();
        // pi-vim consumes Ctrl+r for redo before Pi can dispatch extension shortcuts.
        if (!isKeyRelease(data) && (mode === "normal" || mode === "insert") &&
            vim.pendingExCommand === null && matchesKey(data, "ctrl+r")) {
          pi.events.emit("transcript:recall-prompt", { ctx });
          return;
        }
        if (
          !isKeyRelease(data) &&
          vim.getMode?.() === "normal" &&
          vim.pendingExCommand === null &&
          !vim.prefixCount &&
          !vim.isRepeatRecordingInProgress?.() &&
          !vim.isShowingAutocomplete?.()
        ) {
          if (matchesKey(data, "shift+g") && viewport.scrollToBottom) {
            viewport.scrollToBottom();
            return;
          }
          if (matchesKey(data, "m") && viewport.mode === "fullscreen") {
            pi.events.emit("transcript:toggle-latest-reply-mark", { tui, ctx });
            return;
          }
        }
        handleInput?.(data);
      };
      return editor;
    });
  });
}
