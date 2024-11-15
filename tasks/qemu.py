from pathlib import Path

QEMU_CMDLINE_TEMPLATE = """
exec qemu-system-x86_64 \
    -gdb tcp:127.0.0.1:{gdb_port} \
    -smp {cpus},sockets=4,cores=1,threads=1 \
    -m {memory} \
    -cpu host \
    -kernel {kernel_image} \
    -append "{kernel_cmdline}"
    -drive file={rootfs_path},format=qcow2,if=virtio \
    -netdev tap,id=mynet0,ifname={tap_interface},vhost=on,script=no,downscript=no \
    -device virtio-net-pci,mq=on,vectors=10,netdev=mynet0,mac=52:55:00:d1:55:01 \
    -enable-kvm \
    -nographic \
    -pidfile vm.pid
    -no-reboot \
    -no-acpi \
    {extra_qemu_args} \
    2>&1 | tee vm.log
"""


# -append "console=ttyS0 acpi=off panic=-1 root=/dev/vda rw net.ifnames=0 reboot=t nokaslr" \
def generate_qemu_cmdline(
    rootfs_path: Path,
    kernel_image: Path,
    kernel_cmdline: str,
    tap_interface: str,
    gdb_port: int,
    wait_for_gdb: bool,
    memory: str,
    cpus: int,
) -> str:
    extra_qemu_args = []
    if wait_for_gdb:
        extra_qemu_args.append("-S")

    cmdline = QEMU_CMDLINE_TEMPLATE.format(
        rootfs_path=rootfs_path.absolute().as_posix(),
        kernel_image=kernel_image.absolute().as_posix(),
        tap_interface=tap_interface,
        gdb_port=gdb_port,
        kernel_cmdline=kernel_cmdline,
        memory=memory,
        cpus=cpus,
        extra_qemu_args=' '.join(extra_qemu_args),
    )
    return ' '.join(cmdline.split('\n'))
