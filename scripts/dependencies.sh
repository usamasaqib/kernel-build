#!/bin/bash

set -euxo pipefail

python3 -c 'import sys; v = sys.version_info; sys.exit(0) if v.major == 3 and v.minor >= 8 else sys.exit(1)' || exit 1

./scripts/setup-kernel-deps.sh

# python3 should be installed
./scripts/install-venv
. ./venv
pip install -r requirements.txt

sudo apt install -y git \
    debootstrap \
    qemu-utils

if docker info > /dev/null 2>&1; then
    exit 0
fi

echo "Installing docker"
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do sudo apt-get remove $pkg; done
curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
sudo sh /tmp/get-docker.sh

