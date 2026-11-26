import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isKeyRelease, matchesKey } from "@earendil-works/pi-tui";

export default function (pi: ExtensionAPI) {
  pi.on("session_start", (_event, ctx) => {
    const previous = ctx.ui.getEditorComponent();
    if (!ctx.hasUI || !previous) return;

    ctx.ui.setEditorComponent((tui, theme, keys) => {
      const editor = previous(tui, theme, keys);
      const viewport = tui as typeof tui & { scrollToBottom?: () => void };
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
        if (
          matchesKey(data, "shift+g") &&
          !isKeyRelease(data) &&
          vim.getMode?.() === "normal" &&
          vim.pendingExCommand === null &&
          !vim.prefixCount &&
          !vim.isRepeatRecordingInProgress?.() &&
          !vim.isShowingAutocomplete?.() &&
          viewport.scrollToBottom
        ) {
          viewport.scrollToBottom();
          return;
        }
        handleInput?.(data);
      };
      return editor;
    });
  });
}
