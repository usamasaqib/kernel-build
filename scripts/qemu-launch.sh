#!/bin/bash

ROOTFS=$1
KERNEL=$2
TAP_INTERFACE=$3
   
exec qemu-system-x86_64 \
    -m 2G \
    -smp 4 \
    -kernel $KERNEL \
    -append "console=ttyS0 acpi=off panic=-1 root=/dev/vda rw net.ifnames=0 reboot=t nokaslr" \
    -drive file=$ROOTFS,format=raw,if=virtio \
    -netdev tap,id=mynet0,ifname=$TAP_INTERFACE,script=no,downscript=no \
    -device e1000,netdev=mynet0,mac=52:55:00:d1:55:01 \
    -enable-kvm \
    -nographic \
    -pidfile vm.pid
    -no-reboot \
    -no-acpi \
    2>&1 | tee vm.log

