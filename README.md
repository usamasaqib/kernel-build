# kernel-build
Collection of scripts to quickly launch a QEMU VM for testing some kernel version.   
It also allows a user to build a debian based filesystem for a fully working environemnt.   
The scripts automatically setup a network, ssh keys, and provide auto-generated scripts for connecting to the VM.

## Steps
1. Build the kernel
```
inv -e kernel.build --version=6.8
```

2. Build the filesystem
```
inv -e rootfs.build
```

3. Package the VM
```
inv -e vm.init
```

4. Launch the VM
```
./vms/vm-1000/run.sh
```

5. Connection to the VM
```
./vms/vm-1000/ssh-connect.sh
```
