import { AssistantMessageComponent, SkillInvocationMessageComponent, UserMessageComponent, parseSkillBlock, type ExtensionAPI, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Input, SelectList, Text, matchesKey, parseColor, replaceControlCharacters, stripTerminalSequences, styleText, truncateToWidth, visibleWidth, type TUI } from "@earendil-works/pi-tui";

// Pi 1.6 internals: the fullscreen scroll box owns the rendered document.
// Use component identity for scroll targets: text can repeat, and live components can lack an ID.
const MARK_ENTRY = "transcript-reply-mark";
const ZONE_START = "\x1b]133;A\x07";
const BOOKMARK = "󰃀";

type RenderedComponent = {
  text?: unknown;
  messageId?: string;
  lastMessage?: { role: string; content: readonly { type: string; text?: string }[] };
  skillBlock?: { name: string; userMessage?: string };
  childLines?: {
    children: readonly RenderedComponent[];
    parts: readonly (readonly string[])[];
    lines: readonly string[];
  };
};

type ScrollView = {
  scrollTop: number;
  viewportHeight: number;
  scrollTo(row: number, options: { disableFollow: boolean }): void;
};
type LayoutBox = {
  component: RenderedComponent;
  children: readonly LayoutBox[];
  scrollView?: ScrollView;
  scrollContentLines?: readonly string[];
};

function readTranscript(tui: unknown, messageIds: WeakMap<object, string>) {
  const screen = tui as {
    mode?: string;
    currentLayout?: { root: LayoutBox; primaryScrollView?: ScrollView };
  };
  const frame = screen.mode === "fullscreen" ? screen.currentLayout : undefined;
  const scroll = frame?.primaryScrollView;
  const box = frame?.root?.children.find((child) => child.scrollView === scroll);
  const document = box?.children[0]?.component;
  if (!scroll || !document?.childLines || !box?.scrollContentLines) return;

  const messages: { component: RenderedComponent; row: number; lastRow: number; text: string; isReply?: boolean; id?: string }[] = [];
  function visit(component: RenderedComponent, lines: readonly string[], row: number) {
    if (!lines.length) return;
    const lastRow = row + lines.length - 1;
    if (component.lastMessage?.role === "assistant") {
      const reply = component.lastMessage;
      const id = component.messageId ?? messageIds.get(reply);
      const text = reply.content.filter((block) => block.type === "text").map((block) => block.text).join("\n");
      if (text.trim()) messages.push({ component, row, lastRow, text, isReply: true, id });
    } else if (typeof component.text === "string" && "messageId" in component && lines[0].startsWith(ZONE_START)) {
      messages.push({ component, row, lastRow, text: component.text, id: component.messageId ?? messageIds.get(component) });
    } else if (component.skillBlock && !component.skillBlock.userMessage) {
      messages.push({ component, row, lastRow, text: `/skill:${component.skillBlock.name}`, id: component.messageId ?? messageIds.get(component) });
    } else if (component.childLines?.lines === lines) {
      const { children, parts } = component.childLines;
      for (let i = 0; i < children.length; i++) {
        visit(children[i], parts[i], row);
        row += parts[i].length;
      }
    }
  }
  visit(document, box.scrollContentLines, 0);
  return { scroll, messages };
}

export default function (pi: ExtensionAPI) {
  const messageIds = new WeakMap<object, string>();
  const marked = new Set<string>();
  function loadMarks(ctx: ExtensionContext) {
    marked.clear();
    for (const entry of ctx.sessionManager.getEntries()) {
      if (entry.type === "message" && entry.message.role === "assistant") {
        messageIds.set(entry.message, entry.id);
      } else if (entry.type === "custom" && entry.customType === MARK_ENTRY && typeof entry.data?.id === "string") {
        if (entry.data.marked) marked.add(entry.data.id);
        else marked.delete(entry.data.id);
      }
    }
  }

  function toggleMark(id: string) {
    const mark = !marked.has(id);
    pi.appendEntry(MARK_ENTRY, { id, marked: mark });
    if (mark) marked.add(id);
    else marked.delete(id);
  }

  const cache = new WeakMap<readonly string[], readonly string[]>();
  const restoreRender: (() => void)[] = [];
  pi.on("session_start", (_event, ctx) => {
    if (!ctx.hasUI) return;
    loadMarks(ctx);
    if (restoreRender.length) return;
    for (const { prototype } of [AssistantMessageComponent, UserMessageComponent, SkillInvocationMessageComponent]) {
      const render = prototype.render;
      function renderBookmark(this: unknown, width: number) {
        const lines = render.call(this, width);
        const component = this as RenderedComponent;
        const id = component.messageId ?? messageIds.get(component.lastMessage ?? component);
        if (!id || !marked.has(id) || component.skillBlock?.userMessage || !lines.length || width < visibleWidth(BOOKMARK)) return lines;
        let bookmarked = cache.get(lines);
        if (!bookmarked) {
          // Use the existing blank first row to preserve scroll and mouse positions.
          if (stripTerminalSequences(lines[0]).trim()) return lines;
          const zone = lines[0].startsWith(ZONE_START) ? ZONE_START : "";
          const first = truncateToWidth(BOOKMARK + lines[0].slice(zone.length), width, "");
          bookmarked = [zone + first, ...lines.slice(1)];
          cache.set(lines, bookmarked);
        }
        return bookmarked;
      }
      const ownRender = Object.hasOwn(prototype, "render");
      prototype.render = renderBookmark;
      restoreRender.push(() => {
        if (prototype.render !== renderBookmark) return;
        if (ownRender) prototype.render = render;
        else Reflect.deleteProperty(prototype, "render");
      });
    }
  });
  const stopMarking = pi.events.on("transcript:toggle-latest-reply-mark", (data) => {
    const { tui, ctx } = data as { tui: TUI; ctx: ExtensionContext };
    loadMarks(ctx);
    const latest = readTranscript(tui, messageIds)?.messages.findLast(({ isReply }) => isReply);
    if (!latest?.id) return;
    toggleMark(latest.id);
    tui.requestRender();
  });
  pi.on("session_shutdown", () => {
    stopMarking();
    for (const restore of restoreRender.splice(0)) restore();
  });

  async function recallPrompt(ctx: ExtensionContext) {
    const prompts = ctx.sessionManager.getBranch().flatMap((entry) => {
      if (entry.type !== "message" || entry.message.role !== "user") return [];
      const content = entry.message.content;
      const text = typeof content === "string" ? content : content.flatMap((part) => part.type === "text" ? [part.text] : []).join("");
      const skill = parseSkillBlock(text);
      const prompt = skill ? skill.userMessage || `/skill:${skill.name}` : text;
      return prompt.trim() ? [prompt] : [];
    }).reverse();
    const items = [...new Set(prompts)].reverse().map((value) => ({
      value,
      label: replaceControlCharacters(stripTerminalSequences(value).replace(/\s+/g, " ").trim()),
    }));
    const prompt = await ctx.ui.custom<string | undefined>((tui, theme, keys, done) => {
      const input = new Input({ prompt: "/ ", placeholder: "Search previous prompts" });
      const muted = (text: string) => theme.fg("muted", text);
      const accent = (text: string) => theme.fg("accent", text);
      function makeList() {
        const query = input.getValue().trim().toLowerCase();
        const matches = items.filter(({ label }) => label.toLowerCase().includes(query));
        const list = new SelectList(matches, Math.max(1, Math.min(8, tui.terminal.rows - 5)), {
          selectedPrefix: accent,
          selectedText: accent,
          description: muted,
          scrollInfo: muted,
          noMatch: () => muted(items.length ? "No matching prompts" : "No prompts in this session"),
        });
        const index = Math.max(0, matches.length - 1);
        list.setSelectedIndex(index);
        return { list, count: matches.length, index };
      }
      let { list, count, index } = makeList();
      return {
        get focused() { return input.focused; },
        set focused(focused: boolean) { input.focused = focused; },
        render(width: number) {
          return [
            accent(truncateToWidth("Prompt history", width)),
            ...list.render(width),
            ...input.render(width),
          ];
        },
        invalidate() { input.invalidate(); list.invalidate(); },
        handleInput(data: string) {
          if (keys.matches(data, "tui.select.cancel")) return done(undefined);
          if (keys.matches(data, "tui.select.confirm")) {
            const item = list.getSelectedItem();
            if (item) done(item.value);
          } else if (count && (matchesKey(data, "ctrl+r") || keys.matches(data, "tui.select.up"))) {
            list.setSelectedIndex(index = (index + count - 1) % count);
          } else if (count && keys.matches(data, "tui.select.down")) {
            list.setSelectedIndex(index = (index + 1) % count);
          } else {
            const previous = input.getValue();
            input.handleInput(data);
            if (input.getValue() !== previous) {
              ({ list, count, index } = makeList());
            }
          }
        },
      };
    });
    if (prompt !== undefined) ctx.ui.setEditorText(prompt);
  }
  pi.events.on("transcript:recall-prompt", ({ ctx }) => {
    void recallPrompt(ctx).catch((error) => ctx.ui.notify(String(error), "error"));
  });
  pi.registerShortcut("ctrl+r", {
    description: "Search and reuse prompts from the current session",
    handler: recallPrompt,
  });

  for (const markedOnly of [false, true]) {
    const title = markedOnly ? "Marked messages" : "Transcript messages";
    pi.registerShortcut(markedOnly ? "alt+m" : "alt+p", {
      description: `Find ${markedOnly ? "a marked message" : "a prompt or reply"} in the fullscreen transcript`,
      handler: async (ctx) => {
        loadMarks(ctx);
        const status = await ctx.ui.custom<string | undefined>((tui, theme, keys, done) => {
          const transcript = readTranscript(tui, messageIds);
          if (!transcript) {
            queueMicrotask(() => done("Message picker requires Pi's fullscreen transcript"));
            return new Text("");
          }

          const { messages, scroll } = transcript;
          const top = scroll.scrollTop;
          const bottom = top + Math.max(0, scroll.viewportHeight - 1);
          // Live prompts lack IDs. Match the ordered suffix of the active branch so
          // repeated text cannot select a different copy of a prompt.
          if (ctx.isIdle()) {
            const live = messages.filter(({ component, isReply }) => !isReply && !component.messageId);
            if (live.length) {
              const saved = ctx.sessionManager.getBranch().flatMap((entry) => {
                if (entry.type !== "message" || entry.message.role !== "user") return [];
                const content = entry.message.content;
                const text = typeof content === "string" ? content : content.flatMap((part) => part.type === "text" ? [part.text] : []).join("");
                if (!text) return [];
                const skill = parseSkillBlock(text);
                return [{ id: entry.id, text: skill ? skill.userMessage || "/skill:" + skill.name : text }];
              }).slice(-live.length);
              if (saved.length === live.length && live.every(({ text }, i) => text === saved[i].text)) {
                live.forEach((message, i) => {
                  message.id = saved[i].id;
                  messageIds.set(message.component, saved[i].id);
                });
              }
            }
          }
          const items = messages.map(({ text, isReply, id }, i) => ({
            value: String(i),
            id,
            isReply,
            text: replaceControlCharacters(stripTerminalSequences(text).replace(/\s+/g, " ").trim()),
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
          const input = new Input({ prompt: "/ ", placeholder: "Filter messages", placeholderStyle: muted });

          const listTheme = {
            selectedPrefix: selected,
            selectedText: selected,
            description: muted,
            scrollInfo: muted,
            noMatch: () => muted(markedOnly && !input.getValue() ? "  No marked messages" : "  No matching messages"),
          };
          function makeList() {
            const query = input.getValue().trim().toLowerCase();
            const visible = Math.max(1, Math.min(10, tui.terminal.rows - 7));
            const matches = items.filter(({ text, id }) =>
              (!markedOnly || (id && marked.has(id))) && text.toLowerCase().includes(query),
            ).map(({ value, text, isReply, id }) => ({
              value,
              label: `${id && marked.has(id) ? BOOKMARK : " "} ${isReply ? "  󰚩" : "󰀄"}: ${text}`,
            }));
            const list = new SelectList(matches, visible, listTheme);
            let nearest = 0;
            let distance = Infinity;
            for (let i = 0; i < matches.length; i++) {
              const { row, lastRow } = messages[Number(matches[i].value)];
              // Prefer visible messages, starting near the bottom of the viewport.
              const outside = Math.max(row - bottom, top - lastRow, 0);
              const gap = outside ? scroll.viewportHeight + outside : Math.max(0, bottom - lastRow);
              if (gap < distance) {
                nearest = i;
                distance = gap;
              }
            }
            if (matches.length) list.setSelectedIndex(nearest);
            list.onSelect = ({ value }) => {
              const target = messages[Number(value)].component;
              const current = readTranscript(tui, messageIds);
              const match = current?.messages.find(({ component }) => component === target);
              if (!current || !match) return done("This message is no longer in the transcript");
              current.scroll.scrollTo(match.row, { disableFollow: true });
              done(undefined);
            };
            return { list, matches };
          }
          let { list, matches } = makeList();
          return {
            render(width: number) {
              if (width < 4) return [];
              bodyWidth = width - 2;
              const heading = truncateToWidth(`─ ${title} `, bodyWidth, "");
              const rule = "─".repeat(bodyWidth);
              const row = (line: string) => border("│") + styleText(fit(line, bodyWidth), { fg: text, bg: panel }, mode) + border("│");
              const footer = filtering
                ? " ↑/↓ Move   Tab Mark/unmark   Enter Lock filter   Esc Close"
                : " j/k Move   / Filter   m Mark/unmark   Enter Jump   Esc Close";
              return [
                border("╭" + heading + "─".repeat(bodyWidth - visibleWidth(heading)) + "╮"),
                ...(filtering || input.getValue().trim() ? input.render(bodyWidth - 1).map((line) => row(" " + line)) : []),
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
              if (filtering && keys.matches(data, "tui.select.confirm")) {
                filtering = false;
                input.focused = false;
                return;
              }
              const selectionKeys = ["tui.select.up", "tui.select.down", "tui.select.pageUp", "tui.select.pageDown", "tui.select.confirm"] as const;
              if (matchesKey(data, "tab") || (!filtering && matchesKey(data, "m"))) {
                const selected = list.getSelectedItem();
                if (!selected) return;
                const id = messages[Number(selected.value)].id;
                if (!id) return;
                const index = matches.findIndex(({ value }) => value === selected.value);
                toggleMark(id);
                ({ list, matches } = makeList());
                if (matches.length) list.setSelectedIndex(Math.min(index, matches.length - 1));
              } else if (selectionKeys.some((key) => keys.matches(data, key))) {
                list.handleInput(data);
              } else if (!filtering) {
                if (matchesKey(data, "/")) {
                  filtering = true;
                  input.focused = true;
                } else if (matchesKey(data, "j")) list.handleInput("\x1b[B");
                else if (matchesKey(data, "k")) list.handleInput("\x1b[A");
              } else {
                const previous = input.getValue();
                input.handleInput(data);
                if (previous !== input.getValue()) ({ list, matches } = makeList());
              }
            },
          };
        }, { overlay: true, overlayOptions: { anchor: "center", width: "80%", maxHeight: "100%" } });
        if (status) ctx.ui.notify(status, "info");
      },
    });
  }
}
