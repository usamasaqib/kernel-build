from __future__ import annotations

import os
import netifaces
import json
from invoke import task
from glob import glob
from tasks.arch import Arch
from tasks.kernel import (
    build_kernel,
    get_kernel_pkg_dir,
    get_kernel_image_name,
    KernelBuildPaths,
    KernelVersion,
    requires_gcc8,
    DEFAULT_GIT_SOURCE,
    KernelManifest,
)
from tasks.rootfs import rootfs_build
from tasks.tool import Exit
from invoke.context import Context as InvokeContext
from tasks.compiler import get_compiler, CONTAINER_LINUX_BUILD_PATH
from pathlib import Path

from typing import Optional

IP_ADDR = "169.254.0.%s"
GUEST_ADDR = "169.254.0.%s"


def tap_interface_name() -> str:
    interfaces = netifaces.interfaces()
    for i in range(1, 100):
        name = f"qemu_tap-{i}"
        if name in interfaces:
            continue

        return name

    raise Exit("could not find a valid suffix for tap name. Too may taps active")


def setup_tap_interface(ctx: InvokeContext, kernel_version: KernelVersion) -> str:
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


def setup_kernel_package(
    ctx: InvokeContext,
    kernel_version: KernelVersion,
    arch: Arch,
    compile_only: bool,
    always_use_gcc8: bool,
    kernel_src_dir: str | None,
    git_source: str,
    shallow_clone: bool,
) -> None:
    build_kernel(
        ctx,
        kversion=kernel_version,
        arch=arch,
        compile_only=compile_only,
        always_use_gcc8=always_use_gcc8,
        kernel_src_dir=kernel_src_dir,
        git_source=git_source,
        shallow_clone=shallow_clone,
    )
    rootfs_build(ctx, kernel_version)


def find_free_gdb_port() -> int:
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


def add_gdb_script(
    ctx: InvokeContext, kernel_version: KernelVersion, port: int
) -> None:
    kdir = get_kernel_pkg_dir(kernel_version)
    if not os.path.exists(kdir):
        raise Exit(f"Kernel directory '{kdir}' not present")

    cfg = KernelBuildPaths.linux_stable / ".config"
    ctx.run(f"cp {cfg} {kdir}/linux-source")

    run_cmd = ctx.run
    source_dir = kdir
    if requires_gcc8(kernel_version):
        cc = get_compiler(ctx, KernelBuildPaths.kernel_sources_dir)
        run_cmd = cc.exec
        source_dir = CONTAINER_LINUX_BUILD_PATH / os.path.basename(kdir)

    run_cmd(f"cd {source_dir}/linux-source && make scripts_gdb")

    dbg_img = kdir.absolute() / "vmlinux"
    src_dir = kdir.absolute() / "linux-source"
    vmlinux_gdb = src_dir.absolute() / "vmlinux-gdb.py"
    gdb_script = kdir / "gdb.sh"
    with open(gdb_script, "w") as f:
        f.write("#!/bin/bash\n")
        f.write(f'gdb -ex "add-auto-load-safe-path {src_dir}" -ex "file {dbg_img}" -ex "set arch i386:x86-64:intel" \
                -ex "target remote localhost:{port}" -ex "source {vmlinux_gdb}" -ex "set disassembly-flavor inter" \
                -ex "set pagination off"\n')

    ctx.run(f"chmod +x {gdb_script}")


@task(  # type: ignore
    help={
        "kernel_version": "kernel version string of the form v6.8 or v5.2.20",
        "platform_arch": "architecture of the form x86 or aarch64, etc.",
        "compile_only": "only rebuild bzImage",
    }
)
def init(
    ctx: InvokeContext,
    kernel_version: str,
    platform_arch: Optional[str] = None,
    compile_only: bool = False,
    always_use_gcc8: bool = False,
    kernel_src_dir: str | None = None,
    git_source: str = DEFAULT_GIT_SOURCE,
    shallow_clone: bool = False,
) -> None:
    if platform_arch is None:
        arch = Arch.local()
    else:
        arch = Arch.from_str(platform_arch)

    kversion = KernelVersion.from_str(ctx, kernel_version)
    pkg_dir = get_kernel_pkg_dir(kversion)

    if not pkg_dir.exists():
        setup_kernel_package(
            ctx,
            kversion,
            arch,
            compile_only,
            always_use_gcc8,
            kernel_src_dir,
            git_source,
            shallow_clone,
        )

    manifest: KernelManifest = {}
    with open(pkg_dir / "kernel.manifest", "r") as f:
        manifest = json.load(f)

    if "kernel_source_dir" not in manifest:
        raise Exit(
            "corrupted manifest does not contain 'kernel_source_dir' source directory"
        )

    KernelBuildPaths.linux_stable = Path(manifest["kernel_source_dir"])

    if "gdb_port" not in manifest:
        port = find_free_gdb_port()
        if port == 0:
            raise Exit("unable to find free port for gdb server")
    else:
        port = manifest["gdb_port"]

    scripts_dir = os.path.join(".", "scripts")
    qemu_script = os.path.abspath(os.path.join(scripts_dir, "qemu-launch.sh"))

    tap = setup_tap_interface(ctx, kversion)

    kimage = get_kernel_image_name(arch)
    ctx.run(
        f"echo 'sudo {qemu_script} {pkg_dir.absolute()}/rootfs.qcow2 {pkg_dir.absolute()}/{kimage} {tap} {port}' > {pkg_dir}/run.sh"
    )
    ctx.run(f"chmod +x {pkg_dir.absolute()}/run.sh")

    manifest["tap_name"] = tap
    manifest["gdb_port"] = port
    with open(pkg_dir / "kernel.manifest", "w") as f:
        json.dump(manifest, f)

    ctx.run(f"rm -f {KernelBuildPaths.linux_stable}/../linux-*", warn=True)

    add_gdb_script(ctx, kversion, port)


@task  # type: ignore
def cleanup_taps(ctx: InvokeContext) -> None:
    interfaces = netifaces.interfaces()
    for tap in interfaces:
        if "qemu_tap" in tap:
            ctx.run(f"sudo ip link del {tap}", warn=True)


@task  # type: ignore
def clean(ctx: InvokeContext, kernel_version: str) -> None:
    kversion = KernelVersion.from_str(ctx, kernel_version)
    kernel_dir = get_kernel_pkg_dir(kversion)
    manifest_file = get_kernel_pkg_dir(kversion) / "kernel.manifest"
    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    if "tap_name" in manifest:
        name = manifest["tap_name"]
        ctx.run(f"sudo ip link del {name}", warn=True)

    ctx.run(f"rm -rf {kernel_dir}")
