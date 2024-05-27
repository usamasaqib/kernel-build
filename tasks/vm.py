import os
import netifaces
import json
from invoke import task
from invoke.exceptions import Exit
from tasks.kernel import build as kbuild
from tasks.rootfs import build as rootfs_build

IP_ADDR = "169.254.0.%s"
GUEST_ADDR = "169.254.0.%s"


def tap_interface_name():
    interfaces = netifaces.interfaces()
    for i in range(1, 100):
        name = f"qemu_tap-{i}"
        if name in interfaces:
            continue

        return name


def setup_tap_interface(ctx, kernel_version):
    manifest_file = os.path.join(
        ".", "kernels", "sources", f"kernel-{kernel_version}", "kernel.manifest"
    )
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
    tap_name = tap_interface_name()
    ctx.run(f"sudo ip link del {tap_name}", warn=True)
    ctx.run(f"sudo ip tuntap add {tap_name} mode tap")
    ctx.run(f"sudo ip addr add {tap_ip}/30 dev {tap_name}")
    ctx.run(f"sudo ip link set dev {tap_name} up")
    ctx.run("sudo sh -c 'echo 1 > /proc/sys/net/ipv4/ip_forward'")
    ctx.run(f"sudo iptables -t nat -A POSTROUTING -o {default_interface} -j MASQUERADE")
    ctx.run(
        "sudo iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT"
    )

    ctx.run(f"sudo iptables -A FORWARD -i {tap_name} -o {default_interface} -j ACCEPT")

    return tap_name


def setup_kernel_package(ctx, kernel_version):
    kbuild(ctx, kernel_version)
    rootfs_build(ctx, kernel_version)


@task
def init(ctx, kernel_version):
    kernel_dir = os.path.join(".", "kernels", "sources", f"kernel-{kernel_version}")
    if not os.path.exists(kernel_dir):
        setup_kernel_package(ctx, kernel_version)

    scripts_dir = os.path.join(".", "scripts")
    qemu_script = os.path.abspath(os.path.join(scripts_dir, "qemu-launch.sh"))

    tap = setup_tap_interface(ctx, kernel_version)

    kabspath = os.path.abspath(kernel_dir)
    ctx.run(
        f"echo 'sudo {qemu_script} {kabspath}/rootfs.qcow2 {kabspath}/bzImage {tap}' > {kernel_dir}/run.sh"
    )
    ctx.run(f"chmod +x {kabspath}/run.sh")

    with open(os.path.join(kernel_dir, "kernel.manifest"), "r") as f:
        manifest = json.load(f)

    manifest["tap_name"] = tap
    with open(os.path.join(kernel_dir, "kernel.manifest"), "w") as f:
        json.dump(manifest, f)

    kernel_source = os.path.join(".", "kernels", "sources")
    ctx.run(f"rm -f {kernel_source}/linux-*")


# @task
# def run(ctx, count=1):
#   password = getpass("password: ")
#   vms_dir = os.path.join(".", "vms")
#   for i in range(0, count):
#       vm_num = 1000 + i
#       vm_dir = os.path.join(vms_dir, f"vm-{vm_num}")
#       img = os.path.join(vm_dir, "rootfs.img")
#       kernel = os.path.join(vm_dir, "bzImage")
#       launch = os.path.join(vm_dir, "qemu-launch.sh")
#
#       ctx.sudo(f"{launch} {img} {kernel} qemu_tap-{vm_num}", password=password, disown=True)
#       ctx.run(f"cat {vm_dir}/ssh_cmd")


@task
def cleanup_taps(ctx):
    interfaces = netifaces.interfaces()
    for tap in interfaces:
        if "qemu_tap" in tap:
            ctx.run(f"sudo ip link del {tap}", warn=True)


@task
def clean(ctx, kernel_version, all_vms=False):
    kernel_dir = os.path.join(".", "kernels", "sources", f"kernel-{kernel_version}")
    manifest_file = os.path.join(kernel_dir, "kernel.manifest")
    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    if "tap_name" in manifest:
        name = manifest["tap_name"]
        ctx.run(f"sudo ip link del {name}", warn=True)

    ctx.run(f"rm -rf {kernel_dir}")


# @task
# def shutdown(ctx, count=1):
#    vms_dir = os.path.join(".", "vms")
#    for i in range(0, count):
#        vm_num = 1000 + i
#        vm_dir = os.path.join(vms_dir, f"vm-{vm_num}")
#        res = ctx.run(f"cat {vm_dir}/ssh_cmd").stdout.split('\n')[0]
#        shutdown = f"{res} reboot"
#        ctx.run(shutdown)
#        time.sleep(0.5)
#
#        pid = ctx.run(f"cat {vm_dir}/vm.pid").stdout.split('\n')[0]
#        print(f"vm pid: {pid}")
#
#        if psutil.pid_exists(pid):
#            print(f"Could not shutdown pid: {pid}")
#            raise UnexpectedExit()
