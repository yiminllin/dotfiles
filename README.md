**Minimal install** (fish, nvim, tmux, fzf, rg only): `./install_minimal.sh`

**Fast local validation** (no sudo/network by default):

```bash
scripts/check_dotfiles.sh
```

Optional tools such as Fish, Stylua, Stow, Lua, and Pi are used when
available and reported as skipped when missing.

(Only if on ubuntu docker)

```bash
apt update -y && apt upgrade -y && apt install -y git
```

Then set up git (also need to add SSH key in GitHub page) and pull repo

```bash
ssh-keygen -t ed25519 -C "yiminlllin@gmail.com" -f ~/.ssh/id_ed25519 && cat ~/.ssh/id_ed25519.pub
cd ~ && git clone git@github.com:yiminllin/dotfiles.git && cd dotfiles && bash ./install.sh
```

On mac, set the bash as the default shell

```bash
chsh -s /bin/bash
```

The installer backs up conflicting configuration files under
`~/.dotfiles-backups/<timestamp>/` before linking the repository with Stow.
It does not use `--adopt`. The tmux layout script is already executable.

Check Neovim after installation:

```bash
nvim
:checkhealth
```

Start tmux with `tmux`, then use prefix + f to open the session picker.
Choose `~` for a home-directory workspace or select a discovered Git repository.
The home entry is always available, even when no repositories are found.

Tasks are managed by [td](td/README.md), a local CLI/TUI. Open it with prefix + T
in tmux, or run `td`. See its README for Taskwarrior migration instructions.

Julia: To install

```bash
juliaup add <julia_version>
julia -e 'using Pkg; Pkg.add("LanguageServer")'
```

## Pi agent workflow

```bash
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
stow pi
pi
```

In Pi, run `/login` to authenticate. Configuration is sourced from
`pi/.pi/agent/` and stowed to `~/.pi/agent/`; credentials and sessions remain
private runtime files. Cycle the configured models with `Ctrl-P`/`Ctrl-Shift-P`
or `Alt-]`/`Alt-[`. Run `/reload` after changing keybindings, skills, prompts,
themes, extensions, or context files.

Inside tmux, `<leader>cp` in Neovim opens or prompts the right-hand Pi pane.
Fish `review [PR-number-or-URL]` opens Diffview without waiting for guidance.
Inside tmux it also starts or reuses a visible Pi pane, named `review-<PR-number>`
or `review-<branch-name>` on the Agent Board. Repeating the command in another
pane moves the existing assistant below that invoking pane without restarting it;
reuse searches the current tmux session, including its other windows. Use `--no-agent` for Diffview only;
`--refresh-guide` requests fresh guidance without blocking review. Local review
uses the committed branch diff, not uncommitted working-tree changes.

In Diffview, `<leader>gda` saves a local note, `<leader>gdA` asks Pi, and
`<leader>gdt` replies to a thread and asks Pi a follow-up. `<leader>gdR` refreshes
the review without generating guidance or changing revisions. Tab / Shift-Tab
follow the visible file order; `<leader>gdn` / `<leader>gdN` skip reviewed files.
Until guidance is ready, Diffview uses its native order. When the guide arrives,
the panel becomes a flat list in recommended order without moving the current
diff or cursor. Later guide changes update this same order. `<leader>gdg` opens the concise PR-flow
diagram and recommended route; Enter opens a route file. The guide preserves ASCII
spacing and updates as Pi refines it during conversation, without moving the
current diff cursor or clearing reviewed-file progress. Existing discussions and
local resolutions stay saved when guide items are replaced; those threads are
labelled "earlier guide". Winbars show route position
and explicit completion separately. `<leader>gdv` marks a file reviewed.

`<leader>gdf` toggles All/Phoenix scope in the actual Diffview panel and navigation.
It reads CODEOWNERS at the reviewed head and matches the last applicable rule for
`@ZiplineTeam/phoenix-reviewers`, including shared ownership. The diagram keeps
full-PR context; progress counts only the visible scope. Filtering preserves rename
pairs and saved progress. Missing CODEOWNERS leaves the full review available.

`<leader>gdV` opens a read-only, scrollable diff of all visible files in the same
review order. Enter on an added/removed line opens the exact RIGHT/LEFT location
in Diffview for commenting; Enter on a heading opens that file. Use `za`, `zM`,
and `zR` to fold files, `q` to return, and `r` to refresh. The skim view builds
asynchronously from the pinned revisions, including rename pairs. Changes to
order, scope, or revisions mark it outdated and block old jumps until refreshed.
Opening it again preserves the previous skim position where possible. Skimming
does not mark files reviewed. Lowercase `<leader>gdv` still marks a file reviewed.

`<leader>gds` opens the comment list
(`dd` dismisses/deletes locally, `R` resolves locally). `<leader>gdg` shows the
route and progress. Local resolution does not resolve a GitHub thread.
GitHub comment import requires a current `gh` supporting `gh api --slurp`.
Run the offline workflow checks with `bash nvim/.config/nvim/tests/review.sh`.

`prefix + f` opens the sessionizer with a Pi agent window. The pre-push hook
runs `/skill:dotfile-documenter` and blocks when `PLUGINS.md` must be committed
or Pi cannot verify it. Check the installed configuration without provider or
network access with `pi --offline --version`.

Github-CLI, we need

```bash
gh auth login
```

Nvim's copilot, after installing the plugin, we need to run

```bash
:Copilot setup
```

On Fedora, set "Resize Window" as 'Cmd + Shift + \\'

To test locally:

```bash
docker run -it -v ~/dotfiles:/root/dotfiles ubuntu bash
```

Map CAPS to {ESC, CTRL}:
On Linux:

```bash
sudo systemctl daemon-reload
sudo systemctl enable keyd
sudo systemctl start keyd
sudo keyd reload
```

On MacOS:
Download https://karabiner-elements.pqrs.org/, and use the plugin https://ke-complex-modifications.pqrs.org/?q=caps#tap4caps_hold4ctrl.

Set up Git hooks

```bash
chmod +x .githooks/pre-push
git config core.hooksPath .githooks
```

## Auto-Update

### Background Auto-Update (Dotfiles + Plugins)

Automatically checks for dotfiles updates every 30 minutes and updates Neovim/Fish/Tmux plugins:

```bash
fish ~/dotfiles/scripts/dotfiles_polling.fish & disown
```

### Manual Dotfiles Update

Pull latest dotfiles and update plugins:

```bash
fish ~/dotfiles/scripts/dotfiles_auto_update.fish
```

### Manual System Update

Update OS packages, Cargo tools, UV tools, Node, and Pi:

```bash
fish ~/dotfiles/scripts/system_update.fish
```

**Note:** Auto-update aborts on merge conflicts and requires manual resolution.

Install and auto-update flows use `scripts/run_onchange.sh` for selected
manifest-driven steps. Checksums are stored under `~/.cache/dotfiles/`; set
`DOTFILES_RUN_ONCHANGE_FORCE=1` or remove the matching cache stamp to force a
skipped step to run again.
