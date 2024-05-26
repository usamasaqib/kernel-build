import platform
import os
import glob
from invoke import task
from invoke.exceptions import UnexpectedExit

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

# PACKAEGS TO ADD
# python
PREINSTALL_PKGS = (
    "curl,lsb-release,net-tools,openssh-server,rsync,socat,vim,wget,xz-utils"
)


def install_linux_headers(ctx, kernel_version, arch):
    if arch == "x86_64":
        arch = "amd64"
    elif arch == "aarch64":
        arch = "arm64"

    if kernel_version == None:
        raise UnexpectedExit("no kernel version provided")

    chroot = os.path.join(".", "images", "chroot")
    usr_src = os.path.join(chroot, "usr", "src")
    sources_dir = os.path.join(".", "kernels", "sources")

    headers_packages = glob.glob(
        f"{sources_dir}/linux-headers-{kernel_version}*_{arch}.deb"
    )

    if len(headers_packages) == 0:
        raise UnexpectedExit()

    header_pkg = headers_packages[0]
    ctx.run("sudo rm -r /tmp/headers && mkdir /tmp/headers", warn=True)
    ctx.run(f"sudo dpkg-deb -R {header_pkg} /tmp/headers")

    ctx.run(f"sudo rm -r {usr_src} && sudo mkdir -p {usr_src}")
    ctx.run(f"sudo cp -R /tmp/headers/usr/src/* {usr_src}")


def add_repos(ctx):
    chroot = os.path.join(".", "images", "chroot")
    sources_list = os.path.join(chroot, "etc", "apt", "sources.list")
    ctx.run(f"echo '{DEBIAN_SOURCE_LISTS}' | sudo tee {sources_list}")


def setup_dev_env(ctx, arch, kernel_version):
    add_repos(ctx)


@task
def clean(ctx, release=DEFAULT_DEBIAN, full=False):
    images_dir = os.path.join(".", "images")
    chroot = os.path.join(images_dir, "chroot")
    release_img = os.path.join(images_dir, f"{release}.img")

    if os.path.exists(chroot):
        res = ctx.run(f"mountpoint {chroot}", warn=True)
        if "is a mountpoint" in res.stdout:
            ctx.run(f"sudo umount {chroot}")

    if full:
        ctx.run(f"sudo rm {release_img}")


@task
def build(
    ctx,
    kernel_version=None,
    arch=None,
    lean=False,
    img_size=DEFAULT_IMG_SIZE,
    extra_pkgs="",
    release=DEFAULT_DEBIAN,
    qcow2=False,
):
    if arch == None:
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

    if not lean:
        setup_dev_env(ctx, arch, kernel_version)

    # finish
    ctx.run(f"sudo umount {chroot}")

    # convert to qcow2
    if qcow2:
        qcow2_img = os.path.join(images_dir, f"{release}.qcow2")
        ctx.run(f"sudo qemu-img convert -f raw -O qcow2 {release_img} {qcow2_img}")
        ctx.run(f"sudo rm {release_img}")
        ctx.run(f"sudo chown 1000:1000 {qcow2_img}")
