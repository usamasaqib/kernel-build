#!/bin/sh

set -euxo pipefail

if [[ $UID = 0 ]] ; then
  echo "Please dont run this script as root, since the gef scripts will get setup for the root user"
  exit 1
fi

echo "[+] apt"
sudo apt-get update
sudo apt-get install -y gdb-multiarch binutils gcc file python3-pip ruby-dev git

echo "[+] pip3"
pip3 install crccheck unicorn capstone ropper keystone-engine tqdm

echo "[+] install seccomp-tools, one_gadget"
if [ "x$(which seccomp-tools)" = "x" ]; then
    sudo gem install seccomp-tools
fi

if [ "x$(which one_gadget)" = "x" ]; then
    sudo gem install one_gadget
fi

echo "[+] install rp++"
if [ "x$(uname -m)" = "xx86_64" ]; then
    if [ "x$(which rp-lin)" = "x" ] && [ ! -e /usr/local/bin/rp-lin ]; then
        wget -q https://github.com/0vercl0k/rp/releases/download/v2.1.3/rp-lin-clang.zip -P /tmp
        sudo unzip /tmp/rp-lin-clang.zip -d /usr/local/bin/
        sudo chmod +x /usr/local/bin/rp-lin
        rm /tmp/rp-lin-clang.zip
    fi
fi

echo "[+] install vmlinux-to-elf"
if [ "x$(which vmlinux-to-elf)" = "x" ] && [ ! -e /usr/local/bin/vmlinux-to-elf ]; then
    pip3 install --upgrade lz4 zstandard git+https://github.com/clubby789/python-lzo@b4e39df
    pip3 install --upgrade git+https://github.com/marin-m/vmlinux-to-elf
fi

echo "[+] download gef"
if [ -e ~/.gdbinit-gef.py ]; then
    echo "[-] ~/.gdbinit-gef.py already exists. Please delete or rename."
    echo "[-] INSTALLATION FAILED"
    exit 1
else
    wget -q https://raw.githubusercontent.com/bata24/gef/dev/gef.py -O ~/.gdbinit-gef.py
fi

echo "[+] setup gef"
STARTUP_COMMAND="source ~/.gdbinit-gef.py"
if [ ! -e ~/.gdbinit ] || [ "x$(grep "$STARTUP_COMMAND" ~/.gdbinit)" = "x" ]; then
    echo "$STARTUP_COMMAND" >> ~/.gdbinit
fi

echo "[+] INSTALLATION SUCCESSFUL"
exit 0
