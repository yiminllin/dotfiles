(Only if on ubuntu docker)
```
apt update -y && apt upgrade -y && apt install -y git
```
Then set up git (also need to add SSH key in GitHub page) and pull repo
```
ssh-keygen -t ed25519 -C "yiminlllin@gmail.com" -f ~/.ssh/id_ed25519 && cat ~/.ssh/id_ed25519.pub
cd ~ && git clone git@github.com:yiminllin/dotfiles.git && cd dotfiles && bash ./install.sh
```
Then
```
nvim
:UpdateRemotePlugins
:checkhealth
```

AIChat: create `aichat/.config/aichat/.env`, where
```
CLAUDE_API_KEY=...
```

Github-CLI, we need
```
gh auth login
```

Nvim's copilot, after installing the plugin, we need to run
```
:Copilot setup
```

On Fedora, set "Resize Window" as 'Cmd + Shift + \\'

To test locally:
```
docker run -it -v ~/dotfiles:/root/dotfiles ubuntu bash
```

Map CAPS to {ESC, CTRL}:
On Linux:
```
sudo systemctl daemon-reload
sudo systemctl enable keyd
sudo systemctl start keyd
sudo keyd reload
```
