FROM ubuntu:18.04

COPY setup-kernel-deps.sh /root

RUN /root/setup-kernel-deps.sh

RUN apt-get update ; apt-get upgrade -y ; apt-get install -y gcc-8 g++-8 && \
  update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-8 60 --slave /usr/bin/g++ g++ /usr/bin/g++-8 && \
  update-alternatives --config gcc
