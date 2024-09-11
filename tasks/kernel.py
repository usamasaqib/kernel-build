from __future__ import annotations

from glob import glob
import os
from invoke import task
import uuid
import json
import platform
from pathlib import Path

from tasks.arch import Arch
from tasks.tool import info, Exit
from tasks.compiler import get_compiler, CONTAINER_LINUX_SRC_PATH


class KernelVersion:
    def __init__(self, major: int, minor: int, patch: int):
        self.major = major 
        self.minor = minor
        self.patch = patch

    def __str__(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}"

    def __eq__(self, other: KernelVersion) -> bool:
        if isinstance(other, KernelVersion):
            return self.major == other.major and self.minor == other.minor and self.patch == other.patch
        
        raise NotImplemented

    def __lt__(self, other: KernelVersion) -> bool:
        if not isinstance(other, KernelVersion):
            raise NotImplemented

        if self.major < other.major:
            return True
        if self.major == other.major and self.minor < other.minor:
            return True
            
        return self.minor == other.minor and self.patch < other.patch

    def __lte__(self, other: KernelVersion) -> bool:
        return self.__lt__(other) or self.__eq__(other)

    def __gt__(self, other: KernelVersion) -> bool:
        return not self.__lte__(other)


    def _get_kernel_pkg_dir(self):
        return f"kernel-{self}"

    @staticmethod
    def from_str(ctx, v: str) -> KernelVersion:
        if v[0] == 'v':
            v = v[1:]

        broken = v.split('.')
        if len(broken) < 2 or len(broken) > 3:
            raise Exit(f"Invalid kernel version string {v}")

        try:
            major = int(broken[0])
            minor = int(broken[1])
            if len(broken) == 3:
                patch = int(broken[2])
            else:
                patch = -1
        except ValueError as e:
            raise e

        if patch == -1:
            return KernelVersion(major, minor, discover_latest_patch(ctx, major, minor))

        return KernelVersion(major, minor, patch)

class KernelBuildPaths:
    kernel_dir = Path(f"./kernels")
    kernel_sources_dir = kernel_dir / "sources"
    linux_stable = kernel_sources_dir / "linux-stable"
    patch_dir = kernel_dir / "patches"
    configs_dir = kernel_dir / "configs"

class BuildContext:
    lockfile = KernelBuildPaths.kernel_dir / "build.context.lock"
    def __init__(self, kernel_version: KernelVersion):
        self.kernel_version = kernel_version

    def acquire(self):
        _lockfile = BuildContext.lockfile
        if _lockfile.exists():
            with open(_lockfile, 'r') as lf:
                kv = KernelVersion.from_str(None, lf.read().split('\n')[0])
                if self.kernel_version != kv:
                    raise Exit(f"a build context is already active for kernel {kv}")
        else:
            with open(_lockfile, 'w') as lf:
                lf.write(str(self.kernel_version))

    def release(self):
        try:
            BuildContext.lockfile.unlink()
        except Exception as e:
            raise e

    @staticmethod
    def from_current() -> BuildContext:
        _lockfile = BuildContext.lockfile
        if _lockfile.exists():
            with open(_lockfile, 'r') as lf:
                kv = KernelVersion.from_str(None, lf.read().split('\n')[0])
                return BuildContext(kv)

        raise Exit("No active build context")

def discover_latest_patch(ctx, major: int, minor: int) -> int:
    tag_res = ctx.run(
        f"cd {KernelBuildPaths.linux_stable} && git tag | grep 'v{major}.{minor}.*$' | sort -V | tail -1", hide=True,
    )
    tag = tag_res.stdout.split()[0]
    return KernelVersion.from_str(None, tag).patch


def checkout_kernel(ctx, kernel_version, pull=False):
    if not KernelBuildPaths.linux_stable.exists():
        KernelBuildPaths.linux_stable.mkdir(exist_ok=True)
        ctx.run(
            f"git clone git://git.kernel.org/pub/scm/linux/kernel/git/stable/linux-stable.git {KernelBuildPaths.linux_stable}"
        )

    if pull:
        ctx.run(f"cd {KernelBuildPaths.linux_stable} && git pull")

    info(f"[+] Checking out tag {kernel_version}")
    ctx.run(f"cd {KernelBuildPaths.linux_stable} && git checkout {kernel_version}")

def make_config(ctx, extra_config: str):
    dot_config = KernelBuildPaths.linux_stable / ".config"

    build_path = str(KernelBuildPaths.linux_stable)
    ctx.run(f"make -C {build_path} defconfig")
    ctx.run(f"make -C {build_path} kvm_guest.config")
    ctx.run(f"tee -a < {extra_config} {dot_config}")

    ctx.run(f"make -C {build_path} olddefconfig")


def make_kernel(run, sources_dir: str, compile_only: bool):
    if compile_only:
        run(f"make -C {sources_dir} -j$(nproc) bzImage KCFLAGS=-ggdb3")
    else:
        run(f"make -C {sources_dir} -j$(nproc) deb-pkg KCFLAGS=-ggdb3")

@task
def checkout(ctx, kernel_version: str):
    checkout_kernel(ctx, KernelVersion.from_str(ctx, kernel_version))


def get_kernel_pkg_dir(version: KernelVersion) -> Path:
    return KernelBuildPaths.kernel_sources_dir / version._get_kernel_pkg_dir()

def get_kernel_image_name(arch: Arch) -> str:
    if arch.kernel_arch == "x86":
        return "bzImage"
    if arch.kernel_arch == "arm64":
        return "Image.gz"

    raise Exit("unexpect architecture {arch}")

@task
def build_package(ctx, version: KernelVersion, arch: Arch):
    deb_files = glob(f"{KernelBuildPaths.kernel_sources_dir}/*.deb")

    kdir = get_kernel_pkg_dir(version)
    kdir.mkdir(exist_ok=True)

    for pkg in deb_files:
        ctx.run(f"mv {pkg} {kdir}")

    ctx.run(f"mv {KernelBuildPaths.linux_stable}/vmlinux {kdir}")
    ctx.run(f"mv {KernelBuildPaths.linux_stable}/arch/{arch.kernel_arch}/boot/{get_kernel_image_name(arch)} {kdir}")

    linux_source_dir = kdir / "linux-source"
    ctx.run(f"rm -rf {linux_source_dir}")
    linux_source_dir.mkdir()

    upstream = glob("./**/linux-*", recursive=True)
    found = False
    karch = arch.kernel_arch
    for f in upstream:
        if karch == "x86" and "upstream" in f and "orig.tar.gz" in f:
            ctx.run(f"mv {f} {kdir}/linux.tar.gz")
        elif karch == "arm64" and "orig.tar.gz" in f:
            ctx.run(f"mv {f} {kdir}/linux.tar.gz")
        else:
            continue
        
        found = True

    if not found:
        raise Exit("unable to find source package")

    ctx.run(f"tar -xvf {kdir}/linux.tar.gz -C {linux_source_dir} --strip-components=1")


def kuuid(ctx, kernel_version):
    kid = str(uuid.uuid4())
    kernel_dir = get_kernel_pkg_dir(kernel_version)
    manifest = {"kid": kid}
    with open(f"{kernel_dir}/kernel.manifest", "w+") as f:
        json.dump(manifest, f)


EXTRA_CONFIG = "./kernels/configs/extra.config"

@task(
    help={
        "kernel_version": "kernel version string of the form v6.8 or v5.2.20",
        "arch": "architecture of the form x86 or aarch64, etc.",
        "extra_config": "path to file containing extra KConfig options",
        "compile_only": "only rebuild bzImage",
        "always_use_gcc8": "always compile in docker container with gcc-8",
    }
)
def build(
    ctx,
    kernel_version: str,
    arch: Arch | None = None,
    extra_config: str | None = EXTRA_CONFIG,
    compile_only: bool = False,
    always_use_gcc8: bool = False,
):
    build_kernel(ctx, KernelVersion.from_str(kernel_version), arch=arch, extra_config=extra_config, compile_only=compile_only)

def build_kernel(
    ctx,
    kversion: KernelVersion,
    arch: Arch | None = None,
    extra_config: str | None = EXTRA_CONFIG,
    compile_only: bool = False,
    always_use_gcc8: bool = False,
):

    if arch is None:
        arch = Arch.local()
    else:
        arch = Arch.from_str(arch)

    use_gcc8 = False
    if kversion < KernelVersion(5,5,0):
        use_gcc8 = True
    
    run_cmd = ctx.run
    source_dir = KernelBuildPaths.linux_stable
    if use_gcc8 || always_use_gcc8:
        cc = get_compiler(ctx, KernelBuildPaths.linux_stable)
        run_cmd = cc.exec
        source_dir = CONTAINER_LINUX_SRC_PATH

    context = BuildContext(kversion)

    context.acquire()

    checkout_kernel(ctx, kversion)
    make_config(ctx, extra_config)
    make_kernel(run_cmd, source_dir, compile_only)
    build_package(ctx, kversion, arch)
    kuuid(ctx, kversion)

    info("[+] Kernel {kernel_version} build complete")


@task
def clean(ctx, kernel_version: str | None = None):
    if kernel_version is None:
        context = BuildContext.from_current()
        kversion = context.kernel_version
    else:
        kversion = KernelVersion.from_str(ctx, kernel_version)
        context = BuildContext(kversion)

    ctx.run(f"make -C {KernelBuildPaths.linux_stable} clean")
    ctx.run(f"make -C {KernelBuildPaths.linux_stable}/tools clean")
    ctx.run(f"cd {KernelBuildPaths.linux_stable} && git checkout master")
    ctx.run(f"cd {KernelBuildPaths.linux_stable} && rm .config", warn=True)
    ctx.run(f"cd {KernelBuildPaths.linux_stable} && rm -r debian", warn=True)
    ctx.run(f"cd {KernelBuildPaths.kernel_sources_dir} && rm *", warn=True)
    ctx.run(f"rm -f {KernelBuildPaths.linux_stable}/vmlinux-gdb.py")
    ctx.run(f"rm -f {KernelBuildPaths.linux_stable}/linux.tar.gz")

    if kversion < KernelVersion(5,5,0):
        cc = get_compiler(ctx, KernelBuildPaths.linux_stable)
        cc.exec("rm -f /tmp/*")

    context.release()
