import os
from invoke import task

IP_ADDR = "169.254.%s.%s"
GUEST_ADDR = "169.254.%s.%s"


def setup_tap_interface(ctx, i):
    tap_ip = IP_ADDR % (((4 * i + 1) // 256), ((4 * i + 1) % 256))
    vm_num = 1000 + i
    tap_name = f"qemu_tap-{vm_num}"
    ctx.run(f"sudo ip link del {tap_name}", warn=True)
    ctx.run(f"sudo ip tuntap add {tap_name} mode tap")
    ctx.run(f"sudo ip addr add {tap_ip}/30 dev {tap_name}")
    ctx.run(f"sudo ip link set dev {tap_name} up")
    ctx.run("sudo sh -c 'echo 1 > /proc/sys/net/ipv4/ip_forward'")
    ctx.run("sudo iptables -t nat -A POSTROUTING -o wlp0s20f3 -j MASQUERADE")
    ctx.run(
        "sudo iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT"
    )

    default_interface = ctx.run(
        "ip route get $(getent ahosts google.com | awk '{print $1; exit}') | grep -Po '(?<=(dev ))(\S+)'"
    ).stdout.split()[0]
    ctx.run(f"sudo iptables -A FORWARD -i {tap_name} -o {default_interface} -j ACCEPT")


def setup_guest_network(ctx, i):
    vm_num = 1000 + i
    vms_dir = os.path.join(".", "vms")
    vm_dir = os.path.join(vms_dir, f"vm-{vm_num}")
    chroot_dir = os.path.join(vm_dir, "chroot")
    img = os.path.join(vm_dir, "rootfs.img")

    tap_ip = IP_ADDR % (((4 * i + 1) // 256), ((4 * i + 1) % 256))
    guest_ip = GUEST_ADDR % (((4 * i + 2) // 256), ((4 * i + 2) % 256))

    ctx.run(f"mkdir {chroot_dir}")
    ctx.run(f"sudo chmod 0755 {chroot_dir}")
    ctx.run(f"sudo mount -o loop {img} {chroot_dir}")
    # setup guest network
    ctx.run(f"""
echo "auto eth0\niface eth0 inet static\n\taddress {guest_ip}/30\n\tgateway {tap_ip}\n" | sudo tee {chroot_dir}/etc/network/interfaces
    """)

    # generate ssh keys
    ctx.run(f"rm {vm_dir}/vm-{vm_num}.id_rsa*", warn=True)
    ctx.run(f"ssh-keygen -f {vm_dir}/vm-{vm_num}.id_rsa -t rsa -N ''")
    ctx.run(f"sudo mkdir -p {chroot_dir}/root/.ssh/")
    ctx.run(
        f"cat {vm_dir}/vm-{vm_num}.id_rsa.pub | sudo tee -a {chroot_dir}/root/.ssh/authorized_keys"
    )

    vm_dir_abs = os.path.abspath(vm_dir)
    ctx.run(
        f"echo 'ssh -o StrictHostKeyChecking=false root@{guest_ip} -i {vm_dir_abs}/vm-{vm_num}.id_rsa' > {vm_dir}/ssh_connect"
    )
    ctx.run(f"chmod +x {vm_dir}/ssh_connect")

    ctx.run(
        f"echo 'ssh -o StrictHostKeyChecking=false root@{guest_ip} -i {vm_dir_abs}/vm-{vm_num}.id_rsa \"reboot\"' > {vm_dir}/ssh_shutdown"
    )
    ctx.run(f"chmod +x {vm_dir}/ssh_shutdown")

    ctx.run(f"sudo umount {chroot_dir}")
    ctx.run(f"rm -r {chroot_dir}")


@task
def init(ctx, count=1, img=None, kernel_img=None):
    if img == None:
        print("No rootfs image provided")
        return
    if kernel_img == None:
        print("No kernel image provided")

    vms_dir = os.path.join(".", "vms")
    scripts_dir = os.path.join(".", "scripts")
    qemu_script = os.path.join(scripts_dir, "qemu-launch.sh")
    for i in range(0, count):
        vm_num = 1000 + i
        vm_dir = os.path.join(vms_dir, f"vm-{vm_num}")
        ctx.run(f"mkdir -p {vm_dir}")
        ctx.run(f"cp {img} {vm_dir}/rootfs.img")
        ctx.run(f"cp {qemu_script} {vm_dir}")
        ctx.run(f"cp {kernel_img} {vm_dir}/bzImage")

        setup_tap_interface(ctx, i)
        setup_guest_network(ctx, i)

        vm_dir_abs = os.path.abspath(vm_dir)
        launch = os.path.join(vm_dir_abs, "qemu-launch.sh")
        ctx.run(
            f"echo 'sudo {launch} {vm_dir_abs}/rootfs.img {vm_dir_abs}/bzImage qemu_tap-{vm_num}' > {vm_dir_abs}/run.sh"
        )
        ctx.run(f"chmod +x {vm_dir_abs}/run.sh")


#@task
#def run(ctx, count=1):
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
def cleanup_taps(ctx, count=1):
    for i in range(0, count):
        num = 1000 + i
        tap_name = f"qemu_tap-{num}"
        ctx.run(f"sudo ip link del {tap_name}", warn=True)


@task
def clean(ctx, all_vms=False, vm=0):
    vms_dir = os.path.join(".", "vms")
    if all_vms:
        ctx.run(f"sudo rm -r {vms_dir}")
        return

    if vm > 0:
        vm_dir = os.path.join(vms_dir, f"vm-{vm}")
        ctx.run(f"sudo rm -r {vm_dir}")


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
