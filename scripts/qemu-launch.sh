#!/bin/bash

ROOTFS=$1
KERNEL=$2
TAP_INTERFACE=$3
GDB_PORT=$4
   
exec qemu-system-x86_64 \
    -gdb tcp:127.0.0.1:$GDB_PORT \
    -m 4G \
    -smp 4 \
    -kernel $KERNEL \
    -append "console=ttyS0 acpi=off panic=-1 root=/dev/vda rw net.ifnames=0 reboot=t nokaslr" \
    -drive file=$ROOTFS,format=qcow2,if=virtio \
    -netdev tap,id=mynet0,ifname=$TAP_INTERFACE,vhost=on \
    -device virtio-net-pci,mq=on,vectors=10,netdev=mynet0,mac=52:55:00:d1:55:01 \
    -enable-kvm \
    -nographic \
    -pidfile vm.pid
    -no-reboot \
    -no-acpi \
    2>&1 | tee vm.log


    #-device virtio-net-pci,netdev=mynet0,mac=52:55:00:d1:55:01,id=net0 \
