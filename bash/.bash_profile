export SHELL_PATH=$(which fish)
export EDITOR_PATH=$(which nvim)

if [ -f ~/.bashrc ]; then
    source ~/.bashrc
fi
