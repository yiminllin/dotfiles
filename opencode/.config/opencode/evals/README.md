# OpenCode agent regression fixtures

These fixtures are lightweight manual checks for prompt and agent behavior. Use
them after editing `opencode/.config/opencode/agents/`, `opencode.json`, or the
shared profile. They are intentionally plain Markdown, not a test framework.

Run the static checks with:

```bash
scripts/check_dotfiles.sh
```

For behavioral regression checks, start OpenCode with the relevant agent and use
the prompt in each fixture. The expected behavior section is the pass condition.
