```
apt update -y && apt upgrade -y && apt install -y vim git
cd ~ && git clone git@github.com:yiminllin/dotfiles.git && cd dotfiles && bash ./install.sh
```
Then
```
nvim
:UpdateRemotePlugins
```

To test locally:
```
docker run -it -v ~/dotfiles:/root/dotfiles ubuntu bash
```
