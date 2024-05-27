#!/bin/bash

# python3 should be installed
pip3 install invoke

sudo apt update
sudo apt install git \
    bc \
    bison \
    flex \
    libelf-dev \
    cpio \
    build-essential \
    libssl-dev
