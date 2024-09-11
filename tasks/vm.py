import os
import socket
import netifaces
import json
import platform
from invoke import task
from glob import glob
from invoke.exceptions import Exit
from tasks.arch import Arch
from tasks.kernel import build_kernel , get_kernel_pkg_dir, get_kernel_image_name, KernelBuildPaths, KernelVersion
from tasks.rootfs import build as rootfs_build
from tasks.tool import warn, Exit

IP_ADDR = "169.254.0.%s"
GUEST_ADDR = "169.254.0.%s"

def tap_interface_name():
    interfaces = netifaces.interfaces()
    for i in range(1, 100):
        name = f"qemu_tap-{i}"
        if name in interfaces:
            continue

        return name


def setup_tap_interface(ctx, kernel_version: KernelVersion):
    manifest_file = get_kernel_pkg_dir(kernel_version) / "kernel.manifest"
    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    if "gateway_ip" not in manifest:
        raise Exit(
            "vm package improperly initialized. No gateway ip specified in manifest"
        )

    default_interface = ctx.run(
        "ip route get $(getent ahosts google.com | awk '{print $1; exit}') | grep -Po '(?<=(dev ))(\S+)'"
    ).stdout.split()[0]

    tap_ip = manifest["gateway_ip"]
    if "tap_name" in manifest:
        old_tap = manifest["tap_name"]
        ctx.run(f"sudo ip link del {old_tap}", warn=True)

    tap_name = tap_interface_name()
    ctx.run(f"sudo ip link del {tap_name}", warn=True)
    ctx.run(f"sudo ip tuntap add {tap_name} mode tap")
    ctx.run(f"sudo ip addr add {tap_ip}/30 dev {tap_name}")
    ctx.run(f"sudo ip link set dev {tap_name} up")
    ctx.run("sudo sh -c 'echo 1 > /proc/sys/net/ipv4/ip_forward'")

    '''
    This iptables rule effectively sets up NAT for outbound traffic on interface {default_interface}, 
    allowing devices on the local network to access the internet using the public IP address associated with {default_interface}
    '''
    ctx.run(f"sudo iptables -t nat -A POSTROUTING -o {default_interface} -j MASQUERADE")
    ctx.run(
        "sudo iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT"
    )

    ctx.run(f"sudo iptables -A FORWARD -i {tap_name} -o {default_interface} -j ACCEPT")

    return tap_name


def setup_kernel_package(ctx, kernel_version, arch, compile_only, always_use_gcc8):
    build_kernel(ctx, kversion=kernel_version, arch=arch, compile_only=compile_only, always_use_gcc8=always_use_gcc8)
    rootfs_build(ctx, kernel_version)


def find_free_gdb_port():
    kernel_dir = os.path.join(".", "kernels", "sources")
    all_kernels = glob(f"{kernel_dir}/kernel-*")
    ports = list()
    for k in all_kernels:
        if not os.path.isdir(k):
            continue

        with open(os.path.join(k, "kernel.manifest"), "r") as f:
            manifest = json.load(f)
            if "gdb_port" in manifest:
                ports.append(manifest["gdb_port"])

    for i in range(5432, 6432):
        if i not in ports:
            return i

    return 0


def add_gdb_script(ctx, kernel_version, port):
    kdir = get_kernel_pkg_dir(kernel_version)
    if not os.path.exists(kdir):
        raise Exit(f"Kernel directory '{kdir}' not present")

    cfg = KernelBuildPaths.linux_stable / ".config"
    ctx.run(f"cp {cfg} {kdir}/linux-source")
    ctx.run(f"cd {kdir}/linux-source && make scripts_gdb")

    dbg_img = kdir.absolute() / "vmlinux"
    src_dir = kdir.absolute() / "linux-source"
    vmlinux_gdb = src_dir.absolute() / "vmlinux_gdb.py"

    gdb_script = kdir / "gdb.sh"
    with open(gdb_script, "w") as f:
        f.write("#!/bin/bash\n")
        f.write(f'gdb -ex "add-auto-load-safe-path {src_dir}" -ex "file {dbg_img}" -ex "set arch i386:x86-64:intel" \
                -ex "target remote localhost:{port}" -ex "source {vmlinux_gdb}" -ex "set disassembly-flavor inter" \
                -ex "set pagination off"\n')

    ctx.run(f"chmod +x {gdb_script}")


@task(
    help={
        "kernel_version": "kernel version string of the form v6.8 or v5.2.20",
        "arch": "architecture of the form x86 or aarch64, etc.",
        "compile_only": "only rebuild bzImage",
    }
)
def init(
    ctx, 
    kernel_version: str, 
    arch: str | None = None, 
    compile_only: bool = False,
    always_use_gcc8: bool = False,
):
    if arch is None:
        arch = Arch.local()
    else:
        arch = Arch.from_str(arch)

    kversion = KernelVersion.from_str(ctx, kernel_version)
    pkg_dir = get_kernel_pkg_dir(kversion)

    if not pkg_dir.exists():
        setup_kernel_package(ctx, kversion, arch, compile_only, always_use_gcc8)

    with open(pkg_dir / "kernel.manifest", "r") as f:
        manifest = json.load(f)

    if "gdb_port" not in manifest:
        port = find_free_gdb_port()
        if port == 0:
            raise Exit("unable to find free port for gdb server")
    else:
        port = manifest["gdb_port"]

    scripts_dir = os.path.join(".", "scripts")
    qemu_script = os.path.abspath(os.path.join(scripts_dir, "qemu-launch.sh"))

    tap = setup_tap_interface(ctx, kversion)

    kabspath = os.path.abspath(kernel_dir)
    kimage = get_kernel_image_name(arch)
    ctx.run(
        f"echo 'sudo {qemu_script} {pkg_dir.absolute()}/rootfs.qcow2 {pkg_dir.absolute}/{kimage} {tap} {port}' > {pkg_dir}/run.sh"
    )
    ctx.run(f"chmod +x {pkg_dir.absolute()}/run.sh")

    manifest["tap_name"] = tap
    manifest["gdb_port"] = port
    with open(pkg_dir / "kernel.manifest", "w") as f:
        json.dump(manifest, f)

    ctx.run(f"rm -f {KernelBuildPaths.kernel_sources_dir}/linux-*", warn=True)

    add_gdb_script(ctx, kversion, port)


@task
def cleanup_taps(ctx):
    interfaces = netifaces.interfaces()
    for tap in interfaces:
        if "qemu_tap" in tap:
            ctx.run(f"sudo ip link del {tap}", warn=True)


@task
def clean(ctx, kernel_version, all_vms=False):
    kernel_dir = get_kernel_pkg_dir(kernel_version)
    manifest_file = get_kernel_pkg_dir(kernel_version) / "kernel.manifest"
    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    if "tap_name" in manifest:
        name = manifest["tap_name"]
        ctx.run(f"sudo ip link del {name}", warn=True)

    ctx.run(f"rm -rf {kernel_dir}")
