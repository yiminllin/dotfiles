# Fixture: dotfile-documenter plugin docs

Agent: `dotfile-documenter`

Prompt:

```text
Based on nvim/.config/nvim/lua/plugins/, tmux/.tmux.conf,
fish/.config/fish/config.fish, and install.sh, update PLUGINS.md for plugin
additions/removals only. If there are no plugin-related changes, don't update
anything. Keep the change as minimal as possible.
```

Expected behavior:

- Updates only `PLUGINS.md`, and only for plugin additions or removals detected
  in the listed dotfiles inputs.
- Leaves `PLUGINS.md` unchanged when there are no plugin-related changes.
- Preserves the existing `PLUGINS.md` structure and avoids broad reformatting or
  unrelated tool documentation changes.
