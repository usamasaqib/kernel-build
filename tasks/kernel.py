from glob import glob
import os
from invoke import task

KERNEL_6_8 = "6.8"
ARCH = "x86"


def checkout_kernel(ctx, kernel_version, pull=False):
    if len(kernel_version.split(".")) != 2:
        print("Please provide kernel version in the form major.minor , example: 5.15")
        raise UnexpectedExit()

    linux_stable = os.path.join(".", "kernels", "sources", "linux-stable")
    if not os.path.exists(linux_stable):
        ctx.run(
            f"git clone git://git.kernel.org/pub/scm/linux/kernel/git/stable/linux-stable.git {linux_stable}"
        )

    if pull:
        ctx.run(f"cd {linux_stable} && git pull")

    tag_res = ctx.run(
        f"cd {linux_stable} && git tag | grep 'v{kernel_version}.*$' | sort | tail -1"
    )
    tag = tag_res.stdout.split()[0]

    print(f"Checking out tag {tag}")
    ctx.run(f"cd {linux_stable} && git checkout {tag}")


def parse_patch_target_file(patchfile):
    with open(patchfile, "r") as f:
        lines = f.read().split("\n")

    name = lines[0].split()[1]
    return name


def patch_target(ctx, version, patch):
    patch_target = parse_patch_target_file(patch)
    full_target = os.path.join(
        ".", "kernels", "sources", f"linux-{version}", patch_target
    )

    ctx.run(f"patch {full_target} {patch}")


def apply_patches(ctx, version):
    print("[*] Applying patches")
    kernel_dir = os.path.join(".", "kernels", "sources", f"linux-{version}")
    patch_dir = os.path.join(".", "kernels", "patches")
    patches = glob.glob(f"{patch_dir}/linux-{version}.patch*")

    for patch in patches:
        patch_target(ctx, version, patch)


def make_config(ctx):
    kernel_dir = os.path.join(".", "kernels", "sources", "linux-stable")
    config_dir = os.path.join(".", "kernels", "configs")
    dot_config = os.path.join(kernel_dir, ".config")
    extra_config = os.path.join(config_dir, "extra.config")

    ctx.run(f"make -C {kernel_dir} defconfig")
    ctx.run(f"make -C {kernel_dir} kvm_guest.config")
    ctx.run(f"tee -a < {extra_config} {dot_config}")
    ctx.run(f"make -C {kernel_dir} olddefconfig")


def make_kernel(ctx):
    kernel_dir = os.path.join(".", "kernels", "sources", "linux-stable")
    ctx.run(f"make -C {kernel_dir} -j$(nproc) deb-pkg")


@task
def checkout(ctx, kernel_version=KERNEL_6_8):
    checkout_kernel(ctx, kernel_version)


@task
def configure(ctx, kernel_version=KERNEL_6_8):
    make_config(ctx)


def build_package(ctx, version):
    sources_dir = os.path.join(".", "kernels", "sources")
    deb_files = glob(f"{sources_dir}/*.deb")

    kdir = os.path.join(sources_dir, f"kernel-{version}")
    ctx.run(f"mkdir {kdir}")
    for pkg in deb_files:
        ctx.run(f"mv {pkg} {kdir}")

    ctx.run("mv {sources_dir}/linux-stable/vmlinux {kdir}")
    ctx.run("mv {sources_dir)/linux-stable/arch/x86/boot/bzImage {kdir}")


@task
def build(ctx, kernel_version=KERNEL_6_8, skip_patch=True, arch=ARCH):
    checkout_kernel(ctx, kernel_version)
    if not skip_patch:
        apply_patches(ctx, kernel_version)

    make_config(ctx)
    make_kernel(ctx)
    build_package(ctx, version)
    # compile_headers(ctx, kernel_version, arch)


@task
def clean(ctx):
    sources_dir = os.path.join(".", "kernels", "sources")
    kernel_source = os.path.join(sources_dir, "linux-stable")
    ctx.run(f"make -C {kernel_source} clean")
    ctx.run(f"cd {kernel_source} && git checkout master")
    ctx.run(f"cd {kernel_source} && rm .config", warn=True)
    ctx.run(f"cd {kernel_source} && rm -r debian", warn=True)
    ctx.run(f"cd {sources_dir} && rm *", warn=True)
