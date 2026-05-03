# Fixture: agent permission frontmatter

Scope: `opencode/.config/opencode/agents/*.md`

Expected behavior:

- Agent frontmatter uses `permission:`, not deprecated `tools:`.
- `yolo` and `builder` keep broad local execution ability for routine dotfiles
  work, including edit, bash, and task delegation.
- Read-only or evaluative agents preserve their no-edit/no-bash boundary with
  explicit denies where needed.
- `dotfile-documenter` may edit `PLUGINS.md` for plugin-doc updates, but should
  not broaden into unrelated task delegation or web research.

Static check:

```bash
scripts/check_dotfiles.sh
```
