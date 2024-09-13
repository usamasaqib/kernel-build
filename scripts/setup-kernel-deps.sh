#!/bin/bash

set -euxo pipefail

apt update
apt install -y git \
    bc \
    bison \
    flex \
    kmod \
    libelf-dev \
    libdw-dev \
    cpio \
    build-essential \
    libssl-dev \
    debhelper-compat \
    cmake \
    rsync

rm -rf /tmp/dwarves
git -c http.sslVerify=false clone --recurse-submodules https://github.com/acmel/dwarves.git /tmp/dwarves
cd /tmp/dwarves
git config http.sslVerify "false"
git checkout v1.22
mkdir build
cd build
cmake -D__LIB=lib -DCMAKE_INSTALL_PREFIX=/usr/ ..
make install
