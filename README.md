```
apt update -y && apt upgrade -y && apt install -y vim git
cd ~ && bash ./install.sh
```

To test locally:
```
docker run -it -v ~/dotfiles:/root/dotfiles myubuntu bash
```
