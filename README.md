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

Run

```bash
chmod -x ~/.tmux/cycle-layouts.sh
```

Stowing have `--adopt` flag enabled, where `dotfiles/` contents are overwritten with local's contents. We need to manually run `git --reset HARD` to use the most updated change.
Then

```bash
nvim
:checkhealth
```

For the first time starting tmux, use tmuxinator:

```bash
tmuxinator start main
```

Julia: To install

```bash
juliaup add <julia_version>
julia -e 'using Pkg; Pkg.add("LanguageServer")'
```

AIChat: create `aichat/.config/aichat/.env`, where

```bash
CLAUDE_API_KEY=...
```

OpenCode: run

```bash
opencode auth login
```

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

Update OS packages, Cargo tools, UV tools, Node, and OpenCode:

```bash
fish ~/dotfiles/scripts/system_update.fish
```

**Note:** Auto-update aborts on merge conflicts and requires manual resolution.
