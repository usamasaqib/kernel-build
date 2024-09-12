import platform
import os
import glob
import json
import netifaces
from invoke import task
from invoke.exceptions import Exit
from invoke.context import Context as InvokeContext

from typing import Optional
from tasks.kernel import KernelVersion, KernelManifest

DEBIAN_SOURCE_LISTS = """
deb http://deb.debian.org/debian bullseye main
deb-src http://deb.debian.org/debian bullseye main

deb http://deb.debian.org/debian-security/ bullseye-security main
deb-src http://deb.debian.org/debian-security/ bullseye-security main

deb http://deb.debian.org/debian bullseye-updates main
deb-src http://deb.debian.org/debian bullseye-updates main
"""

DEFAULT_IMG_SIZE = "20G"
DEFAULT_DEBIAN = "bullseye"

IP_ADDR = "169.254.%s.1"
GUEST_ADDR = "169.254.%s.2"

# PACKAEGS TO ADD
# python
PREINSTALL_PKGS = (
    "curl,dpkg,lsb-release,net-tools,openssh-server,rsync,socat,vim,wget,xz-utils"
)


def add_repos(ctx: InvokeContext) -> None:
    chroot = os.path.join(".", "images", "chroot")
    sources_list = os.path.join(chroot, "etc", "apt", "sources.list")
    ctx.run(f"echo '{DEBIAN_SOURCE_LISTS}' | sudo tee {sources_list}")


# These are the debian packages created during kernel build
# These include the headers the debug build of the kernel, etc.
# Check the ./kernels/sources/kernel-[version] directory for all of them
def install_deb_packages(ctx: InvokeContext, kernel_version: KernelVersion) -> None:
    pkg_dir = os.path.join(f"kernels/sources/kernel-{kernel_version}")
    if not os.path.exists(pkg_dir):
        raise Exit(f"package dir for version {kernel_version} does not exist")

    deb_files = glob.glob(f"{pkg_dir}/linux-image*.deb")
    chroot = os.path.join(".", "images", "chroot")
    scratch = os.path.join(".", "images", "scratch")

    # We do not use dpkg-deb -x directly because the root filesystem has
    # some symlinks which do not correspond to the layout generated by the
    # kernel compilation.
    # Using tar -h allows us to respect the layout of the root filesystem
    for pkg in deb_files:
        ctx.run(f"mkdir {scratch}")
        ctx.run(f"cp {pkg} {scratch}")
        pkg_name = os.path.basename(pkg)
        ctx.run(f"dpkg-deb --fsys-tarfile {scratch}/{pkg_name} > {scratch}/pkg.tar")
        ctx.run(f"sudo tar -h -xvf {scratch}/pkg.tar -C {chroot}")
        ctx.run(f"rm -rf {scratch}")


def all_guest_gateways() -> list[str]:
    kernel_dir = os.path.join(".", "kernels", "sources")
    all_kernels = glob.glob(f"{kernel_dir}/kernel-*")
    tap_ips = list()
    for k in all_kernels:
        with open(os.path.join(k, "kernel.manifest"), "r") as f:
            manifest = json.load(f)
            if "gateway_ip" in manifest:
                tap_ips.append(manifest["gateway_ip"])

    return tap_ips


AF_INET = 2


def interface_ips() -> list[str]:
    interfaces = netifaces.interfaces()
    ips = list()
    for netif in interfaces:
        info = netifaces.ifaddresses(netif)
        if AF_INET not in info:
            continue

        ip = info[AF_INET][0]["addr"]
        ips.append(ip)

    return ips


def find_tap_ip() -> tuple[str, int]:
    taken_ips = all_guest_gateways()
    up_interfaces = interface_ips()

    for i in range(0, 256):
        tap_ip = IP_ADDR % i
        if tap_ip in taken_ips or tap_ip in up_interfaces:
            continue

        return tap_ip, i

    raise Exit(f"no IP available in range {IP_ADDR % 0}/24")


def setup_guest_network(
    ctx: InvokeContext, version: KernelVersion, kuuid: str
) -> tuple[str, str]:
    chroot_dir = os.path.join(".", "images", "chroot")
    kernel_dir = os.path.join(".", "kernels", "sources", f"kernel-{version}")

    tap_ip, subnet = find_tap_ip()
    guest_ip = GUEST_ADDR % subnet

    # setup guest network
    ctx.run(f"""
echo "auto eth0\niface eth0 inet static\n\taddress {guest_ip}/30\n\tgateway {tap_ip}\n" | sudo tee {chroot_dir}/etc/network/interfaces
    """)

    # generate ssh keys
    ctx.run(f"rm {kernel_dir}/vm-{kuuid}.id_rsa*", warn=True)
    ctx.run(f"ssh-keygen -f {kernel_dir}/vm-{kuuid}.id_rsa -t rsa -N ''")
    ctx.run(f"sudo mkdir -p {chroot_dir}/root/.ssh/")
    ctx.run(
        f"cat {kernel_dir}/vm-{kuuid}.id_rsa.pub | sudo tee -a {chroot_dir}/root/.ssh/authorized_keys"
    )

    kdir_abs = os.path.abspath(kernel_dir)
    # ServerAliveInterval=100000 is set so long debug sessions do not kill the ssh session due to keep alive issues
    ctx.run(
        f"echo 'ssh -o StrictHostKeyChecking=false -o ServerAliveInterval=100000 root@{guest_ip} -i {kdir_abs}/vm-{kuuid}.id_rsa' > {kernel_dir}/ssh_connect"
    )
    ctx.run(f"chmod +x {kernel_dir}/ssh_connect")

    ctx.run(
        f"echo 'ssh -o StrictHostKeyChecking=false root@{guest_ip} -i {kdir_abs}/vm-{kuuid}.id_rsa \"reboot\"' > {kernel_dir}/ssh_shutdown"
    )
    ctx.run(f"chmod +x {kernel_dir}/ssh_shutdown")

    return tap_ip, guest_ip


def setup_dev_env(
    ctx: InvokeContext, kernel_version: KernelVersion, manifest: KernelManifest
) -> KernelManifest:
    if not kernel_version:
        raise Exit("no kernel version provided")

    add_repos(ctx)

    install_deb_packages(ctx, kernel_version)
    tap, guest = setup_guest_network(ctx, kernel_version, manifest["kid"])
    manifest["gateway_ip"] = tap
    manifest["guest_ip"] = guest

    return manifest


@task  # type: ignore
def build(
    ctx: InvokeContext,
    kernel_version: str,
    arch: Optional[str] = None,
    lean: bool = False,
    img_size: str = DEFAULT_IMG_SIZE,
    extra_pkgs: str = "",
    release: str = DEFAULT_DEBIAN,
    qcow2: bool = False,
) -> None:
    rootfs_build(
        ctx,
        KernelVersion.from_str(ctx, kernel_version),
        arch,
        lean,
        img_size,
        extra_pkgs,
        release,
        qcow2,
    )


def rootfs_build(
    ctx: InvokeContext,
    kernel_version: KernelVersion,
    arch: Optional[str] = None,
    lean: bool = False,
    img_size: str = DEFAULT_IMG_SIZE,
    extra_pkgs: str = "",
    release: str = DEFAULT_DEBIAN,
    qcow2: bool = False,
) -> None:
    if arch is None:
        arch = platform.machine()

    if arch == "aarch64":
        debarch = "arm64"
    elif arch == "x86_64":
        debarch = "amd64"
    else:
        debarch = arch

    images_dir = os.path.join(".", "images")
    chroot = os.path.join(images_dir, "chroot")
    release_img = os.path.join(images_dir, f"{release}.img")

    if not os.path.exists(images_dir):
        ctx.run(f"mkdir {images_dir}")

    # build image
    ctx.run(f"dd if=/dev/zero of={release_img} bs=1 count=0 seek={img_size}")
    ctx.run(f"mkfs.ext2 -F {release_img}")

    # mount image to directory
    ctx.run(f"sudo mkdir -p {chroot}", warn=True)
    ctx.run(f"sudo chmod 0755 {chroot}")
    ctx.run(f"sudo mount -o exec,loop {release_img} {chroot}")

    # build environment with debootstrap
    debootparams = f"--arch={debarch} --components=main,contrib,non-free "
    if PREINSTALL_PKGS != "":
        extra_pkgs += f",{PREINSTALL_PKGS}"

    if extra_pkgs != "":
        debootparams += f"--include={extra_pkgs} "

    # build cache archive for packages for faster subsequent builds
    cache_dir = os.path.abspath(os.path.join(images_dir, "cache.tar.gz"))
    if not os.path.exists(cache_dir):
        cacheparams = (
            debootparams + f"--make-tarball={cache_dir} {release} /tmp/nonexistent"
        )
        if os.path.exists("/tmp/nonexistent"):
            ctx.run("sudo rm -r /tmp/nonexistent")
        ctx.run(f"sudo debootstrap {cacheparams}")

    debootparams += f"--unpack-tarball={cache_dir} {release} {chroot}"
    ctx.run(f"sudo debootstrap {debootparams}")

    # set some defaults and enable promptless ssh to the machine for root
    ctx.run(f"sudo sed -i '/^root/ {{ s/:x:/::/ }}' {chroot}/etc/passwd")
    ctx.run(
        f"echo 'T0:23:respawn:/sbin/getty -L ttyS0 115200 vt100' | sudo tee -a {chroot}/etc/inittab"
    )
    ctx.run(f"'/dev/root / ext4 defaults 0 0' | sudo tee -a {chroot}/etc/fstab")
    ctx.run(
        f"echo 'debugfs /sys/kernel/debug debugfs defaults 0 0' | sudo tee -a {chroot}/etc/fstab"
    )
    ctx.run(
        f"echo 'mount -t tracefs nodev /sys/kernel/tracing' | sudo tee -a {chroot}/etc/fstab"
    )
    ctx.run(
        f"echo 'binfmt_misc /proc/sys/fs/binfmt_misc binfmt_misc defaults 0 0' | sudo tee -a {chroot}/etc/fstab"
    )
    ctx.run(f'echo -en "127.0.0.1\tlocalhost\n" | sudo tee {chroot}/etc/hosts')
    ctx.run(f'echo "nameserver 8.8.8.8" | sudo tee -a {chroot}/etc/resolv.conf')
    ctx.run(f'echo "ddvm" | sudo tee {chroot}/etc/hostname')
    ctx.run(f'echo -en "127.0.1.1\tddvm\n" | sudo tee -a {chroot}/etc/hosts')

    kernel_dir = os.path.join(".", "kernels", "sources", f"kernel-{kernel_version}")
    kernel_manifest = os.path.join(kernel_dir, "kernel.manifest")
    if not lean:
        with open(kernel_manifest, "r") as f:
            manifest = json.load(f)

        manifest = setup_dev_env(ctx, kernel_version, manifest)
        with open(kernel_manifest, "w") as f:
            json.dump(manifest, f)

    # finish
    ctx.run(f"sudo umount {chroot}")

    # convert to qcow2
    qcow2_img = os.path.join(images_dir, f"{release}.qcow2")
    ctx.run(f"sudo qemu-img convert -f raw -O qcow2 {release_img} {qcow2_img}")
    ctx.run(f"sudo rm {release_img}")
    ctx.run(f"sudo chown 1000:1000 {qcow2_img}")
    ctx.run(f"mv {qcow2_img} {kernel_dir}/rootfs.qcow2")
