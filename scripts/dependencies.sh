#!/bin/bash

set -euxo pipefail

# python3 should be installed
pip3 install invoke netifaces

sudo apt update
sudo apt install -y git \
    bc \
    bison \
    flex \
    libelf-dev \
    libdw-dev \
    cpio \
    build-essential \
    libssl-dev \
    debhelper-compat \
    debootstrap \
    cmake \
    qemu-utils

rm -rf /tmp/dwarves
git -c http.sslVerify=false clone --recurse-submodules https://github.com/acmel/dwarves.git /tmp/dwarves
cd /tmp/dwarves
git config http.sslVerify "false"
git checkout v1.22
mkdir build
cd build
cmake -D__LIB=lib -DCMAKE_INSTALL_PREFIX=/usr/ ..
make install
