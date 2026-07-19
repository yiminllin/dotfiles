---
name: dotfile-documenter
description: Update or refresh PLUGINS.md when dotfiles changes add, remove, or materially change documented plugins or installed tools in Neovim, tmux, Fish, or install sources. Use for plugin/tool inventory documentation changes, not ordinary dotfile edits.
---

# Dotfile Documenter

## Purpose

Keep `PLUGINS.md` aligned with observed plugin and tool-installation changes in this dotfiles repository.

## Use boundaries

- Use only when a change to Neovim plugin specs, `tmux/.tmux.conf`, Fish plugin/config files, or install scripts/manifests may change the documented plugin or tool inventory.
- Do not use for unrelated settings, keymaps, formatting, or other dotfile edits that do not affect that inventory.
- Require this repository's `PLUGINS.md` and relevant source paths. If ownership or evidence is unclear, stop and ask rather than guessing.
- Keep documentation work local. Do not run installers or package managers, fetch from the network, authenticate, or modify runtime/external paths without explicit approval.

## Workflow

1. Read `PLUGINS.md` and preserve its existing headings, tables, link style, ordering, and level of detail.
2. Inspect the requested diff or local comparison and then the affected source files. Check relevant Neovim specs under `nvim/.config/nvim/lua/plugins/`, tmux plugin declarations, Fish plugin/config files, and install scripts or manifests.
3. Identify only evidenced plugin or installed-tool additions, removals, renames, or material documentation changes. Do not infer inventory from names alone or invent plugins, purposes, install methods, or paths.
4. Update only the corresponding `PLUGINS.md` entries. If there is no plugin/tool inventory change, leave it unchanged and report that result.
5. Review the focused diff for source support, valid links, preserved formatting, and absence of unrelated edits.

## Validation and output

- Use local reads, searches, and focused git diff checks; run a repository documentation/check script only when it is relevant and does not invoke network or installers.
- Report the source files inspected, entries changed (or why none changed), validation performed, and any unresolved uncertainty.
- Do not edit files other than `PLUGINS.md` for a documentation refresh.
