import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Input, SelectList, Text, matchesKey, parseColor, replaceControlCharacters, stripTerminalSequences, styleText, truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

// Pi 1.6 internals: the fullscreen scroll box owns the rendered document.
// Use component identity, not text or session IDs: prompts can repeat, and live prompts have no ID.
type RenderedComponent = {
  text?: unknown;
  messageId?: string;
  skillBlock?: { name: string; userMessage?: string };
  childLines?: {
    children: readonly RenderedComponent[];
    parts: readonly (readonly string[])[];
    lines: readonly string[];
  };
};

type ScrollView = { scrollTo(row: number, options: { disableFollow: boolean }): void };
type LayoutBox = {
  component: RenderedComponent;
  children: readonly LayoutBox[];
  scrollView?: ScrollView;
  scrollContentLines?: readonly string[];
};

function readTranscript(tui: unknown) {
  const screen = tui as {
    mode?: string;
    currentLayout?: { root: LayoutBox; primaryScrollView?: ScrollView };
  };
  const frame = screen.mode === "fullscreen" ? screen.currentLayout : undefined;
  const scroll = frame?.primaryScrollView;
  const box = frame?.root?.children.find((child) => child.scrollView === scroll);
  const document = box?.children[0]?.component;
  if (!scroll || !document?.childLines || !box?.scrollContentLines) return;

  const prompts: { component: RenderedComponent; row: number; text: string }[] = [];
  function visit(component: RenderedComponent, lines: readonly string[], row: number) {
    if (!lines.length) return;
    if (typeof component.text === "string" && "messageId" in component && lines[0].startsWith("\x1b]133;A\x07")) {
      prompts.push({ component, row, text: component.text });
    } else if (component.skillBlock && !component.skillBlock.userMessage) {
      prompts.push({ component, row, text: `/skill:${component.skillBlock.name}` });
    } else if (component.childLines?.lines === lines) {
      const { children, parts } = component.childLines;
      for (let i = 0; i < children.length; i++) {
        visit(children[i], parts[i], row);
        row += parts[i].length;
      }
    }
  }
  visit(document, box.scrollContentLines, 0);
  return { scroll, prompts };
}

export default function (pi: ExtensionAPI) {
  pi.registerShortcut("alt+p", {
    description: "Find a prompt in the fullscreen transcript",
    handler: async (ctx) => {
      const status = await ctx.ui.custom<string | undefined>((tui, theme, keys, done) => {
        const transcript = readTranscript(tui);
        if (!transcript?.prompts.length) {
          queueMicrotask(() => done(transcript ? "No prompts in this transcript" : "Prompt picker requires Pi's fullscreen transcript"));
          return new Text("");
        }

        const { prompts } = transcript;
        const items = prompts.map(({ text }, i) => ({
          value: String(i),
          label: replaceControlCharacters(stripTerminalSequences(text).replace(/\s+/g, " ").trim()),
        })).reverse();
        const light = theme.appearance === "light";
        const mode = theme.getColorMode();
        const panel = parseColor(light ? "#f2f2f2" : "#262626");
        const text = parseColor(light ? "#262626" : "#e4e4e4");
        const blue = parseColor(light ? "#275b97" : "#a1c9ef");
        const blueBg = parseColor(light ? "#dce8f5" : "#30445b");
        const mutedColor = parseColor(light ? "#595959" : "#ababab");
        const muted = (line: string) => styleText(line, { fg: mutedColor }, mode);
        const border = (line: string) => styleText(line, { fg: mutedColor, bg: panel }, mode);
        const fit = (line: string, width: number) => truncateToWidth(line, width, "", true);
        let bodyWidth = 0;
        const selected = (line: string) => styleText(fit(line, bodyWidth), { fg: blue, bg: blueBg, bold: true }, mode);

        let filtering = false;
        const input = new Input({ prompt: "/ ", placeholder: "Filter prompts", placeholderStyle: muted });
        input.focused = true;

        const listTheme = {
          selectedPrefix: selected,
          selectedText: selected,
          description: muted,
          scrollInfo: muted,
          noMatch: () => muted("  No matching prompts"),
        };
        function makeList() {
          const query = input.getValue().trim().toLowerCase();
          const visible = Math.max(1, Math.min(10, tui.terminal.rows - 7));
          const list = new SelectList(items.filter(({ label }) => label.toLowerCase().includes(query)), visible, listTheme);
          list.onSelect = ({ value }) => {
            const target = prompts[Number(value)].component;
            const current = readTranscript(tui);
            const match = current?.prompts.find(({ component }) => component === target);
            if (!current || !match) return done("This prompt is no longer in the transcript");
            current.scroll.scrollTo(match.row, { disableFollow: true });
            done(undefined);
          };
          return list;
        }
        let list = makeList();
        return {
          render(width: number) {
            if (width < 4) return [];
            bodyWidth = width - 2;
            const title = truncateToWidth("─ Transcript prompts ", bodyWidth, "");
            const rule = "─".repeat(bodyWidth);
            const row = (line: string) => border("│") + styleText(fit(line, bodyWidth), { fg: text, bg: panel }, mode) + border("│");
            const footer = filtering
              ? " ↑/↓ Move   Enter Jump   Esc Close"
              : " j/k or ↑/↓ Move   / Filter   Enter Jump   Esc Close";
            return [
              border("╭" + title + "─".repeat(bodyWidth - visibleWidth(title)) + "╮"),
              ...(filtering ? input.render(bodyWidth - 1).map((line) => row(" " + line)) : []),
              ...list.render(bodyWidth).map(row),
              border("├" + rule + "┤"),
              row(muted(truncateToWidth(footer, bodyWidth))),
              border("╰" + rule + "╯"),
            ];
          },
          invalidate() {
            input.invalidate();
            list.invalidate();
          },
          handleInput(data: string) {
            if (keys.matches(data, "tui.select.cancel")) return done(undefined);
            const selectionKeys = ["tui.select.up", "tui.select.down", "tui.select.pageUp", "tui.select.pageDown", "tui.select.confirm"] as const;
            if (selectionKeys.some((key) => keys.matches(data, key))) {
              list.handleInput(data);
            } else if (!filtering) {
              if (matchesKey(data, "/")) filtering = true;
              else if (matchesKey(data, "j")) list.handleInput("\x1b[B");
              else if (matchesKey(data, "k")) list.handleInput("\x1b[A");
            } else {
              const previous = input.getValue();
              input.handleInput(data);
              if (previous !== input.getValue()) list = makeList();
            }
          },
        };
      }, { overlay: true, overlayOptions: { anchor: "center", width: "80%", maxHeight: "100%" } });
      if (status) ctx.ui.notify(status, "info");
    },
  });
}
