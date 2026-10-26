# Dotfiles

Neovim, Fish, tmux, and Kitty configuration for macOS, Debian/Ubuntu, and Fedora.
See [installed tools](PLUGINS.md) and [past tools](GONE_BUT_NOT_FORGOTTEN.md).

Original code and configuration use the [MIT license](LICENSE).
Third-party material retains its own license and notices.

## Install

Add your SSH key to GitHub, then:

```bash
cd ~ && git clone git@github.com:yiminllin/dotfiles.git && cd dotfiles && bash ./install.sh
```

| Setup                                         | Command                               |
| --------------------------------------------- | ------------------------------------- |
| Lightweight Fish, Neovim, tmux, and CLI tools | `./install_minimal.sh`                |
| Optional full TeX distribution                | `bash scripts/install_tex.sh`         |
| Local validation                              | `scripts/check_dotfiles.sh`           |
| GitHub authentication                         | `gh auth login`                       |
| Git pre-push hook                             | `git config core.hooksPath .githooks` |

The installer backs up conflicting files to `~/.dotfiles-backups/<timestamp>/` before Stow links them.
On macOS, use `chsh -s /bin/bash` for the login shell; Bash starts Fish.
In Neovim, run `:checkhealth`. Validation skips unavailable optional tools.

For Julia, run `juliaup add <julia_version>` and
`julia -e 'using Pkg; Pkg.add("LanguageServer")'`.

For Ubuntu containers, install Git first with `apt update -y && apt upgrade -y && apt install -y git`.
To test in a container: `docker run -it -v ~/dotfiles:/root/dotfiles ubuntu bash`.

## Daily use

Start `tmux`. Prefix is Ctrl-Space.

| Action                               | Command / key                              |
| ------------------------------------ | ------------------------------------------ |
| Select home (`~`) or a Git workspace | prefix + f                                 |
| Open tasks                           | prefix + T or `td` ([guide](td/README.md)) |
| Start Pi                             | `pi`, then `/login`                        |
| Reload Pi configuration              | `/reload`                                  |
| Cycle Pi models                      | Ctrl-P / Ctrl-Shift-P or Alt-] / Alt-[     |
| Open or prompt the Pi pane           | Neovim `<leader>cp`                        |
| Review a branch or PR                | `review [PR-number-or-URL]`                |

Pi configuration lives in `pi/.pi/agent/`, linked to `~/.pi/agent/`; credentials and sessions stay private.
For Pi-only setup: `npm install -g --ignore-scripts @earendil-works/pi-coding-agent`,
then `stow pi` and `bash scripts/setup_pi_project_memory.sh`.
The installer links project memory to `~/notes/pi-memory/projects`; missing notes only warns.
Conflicting stores stop setup. Close all Pi sessions before [manual migration](https://github.com/yiminllin/notes#pi-memory).
Notes restores saved memory and skills, not conversation history.
Check Pi offline with `pi --offline --version`.
The pre-push hook requires Pi and blocks if inventory verification fails or `PLUGINS.md` needs a commit.

## Keyboard setup

Map Caps Lock to Escape on tap and Control on hold.
On Fedora, after installing keyd:

```bash
sudo systemctl daemon-reload
sudo systemctl enable keyd
sudo systemctl start keyd
sudo keyd reload
```

On macOS, use [Karabiner-Elements](https://karabiner-elements.pqrs.org/) with the
[Caps Lock modification](https://ke-complex-modifications.pqrs.org/?q=caps#tap4caps_hold4ctrl).
On Fedora, set Resize Window to Cmd + Shift + \.

## Updates

| Action                                           | Command                                                                        |
| ------------------------------------------------ | ------------------------------------------------------------------------------ |
| Pull dotfiles and update plugins                 | `fish ~/dotfiles/scripts/dotfiles_auto_update.fish`                            |
| Update OS packages, Cargo/UV tools, Node, and Pi | `fish ~/dotfiles/scripts/system_update.fish`                                   |
| Poll every 30 minutes in Fish                    | `source ~/dotfiles/scripts/dotfiles_polling.fish; dotfiles_auto_poll & disown` |

Dotfile pulls require a fast-forward; resolve divergence or conflicts manually.
Selected install/update steps cache manifest checksums in `~/.cache/dotfiles/`.
Set `DOTFILES_RUN_ONCHANGE_FORCE=1` or remove a matching cache stamp to rerun a skipped step.
