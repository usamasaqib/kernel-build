from glob import glob
import os
from invoke import task
import uuid
import json
import platform

from tasks.arch import Arch
from tasks.types import KbuildArchOrLocal, PathOrStr
from tasks.tool import warn, Exit


class KernelVersion:
    def __init__(self, major: int, minor: int, patch: int = -1):
        self.major = major 
        self.minor = minor
        self.patch = patch

    def __str__(self) -> str:
        if self.patch == -1:
            return f"v{self.major}.{self.minor}"

        return f"v{self.major}.{self.minor}.{self.patch}"

    def __eq__(self, other: KernelVersion) -> bool:
        if isinstance(other, KernelVersion):
            return self.major == other.major and self.minor == other.minor and self.patch == other.patch
        
        raise NotImplemented

    def has_patch(self) -> bool:
        return self.patch != -1

    def major_minor_str(self) -> str:
        return f"v{major}.{minor}"

    def _get_kernel_pkg_dir(self):
        return f"kernel-{self}"

    @staticmethod
    def from_str(v: str) -> KernelVersion:
        if v[0] = 'v':
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
                patch = 0
        except ValueError:
            raise Exit("Invalid kernel version string {v}")

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
        if lockfile.exists():
            with open(str(lockfile), 'r') as lf:
                kv = KernelVersion(lf.read().split("\n")[0])
                if self.kernel_version != kv:
                    raise Exit(f"a build context is already active for kernel {self.kernel_version}")
        else:
            with open(str(lockfile), 'w') as lf:
                lf.write(str(self.kernel_version))

    def release(self):
        try:
            lockfile.unlink()
        except Exception as e:
            raise Exit("no active build context found {e}")

    @staticmethod
    def from_current() -> BuildContext:
        if lockfile.exists():
            with open(str(lockfile), 'r'): lf:
                kv = KernelVersion(lf.read().split('\n')[0])
                return BuildContext(kv)

        raise Exit("No active build context")

def checkout_kernel(ctx, kernel_version, pull=False) -> KernelVersion:
    KernelBuildPaths.linux_stable.mkdir(exit_ok=True)
    ctx.run(
        f"git clone git://git.kernel.org/pub/scm/linux/kernel/git/stable/linux-stable.git {KernelBuildPaths.linux_stable}"
    )

    if pull:
        ctx.run(f"cd {KernelBuildPaths.linux_stable} && git pull")

    if not kernel_version.has_patch:
        tag_res = ctx.run(
            f"cd {KernelBuildPaths.linux_stable} && git tag | grep 'v{kernel_version}.*$' | sort -V | tail -1"
        )
        tag = tag_res.stdout.split()[0]
        kernel_version = KernelVersion.from_str(tag)

    info(f"[+] Checking out tag {tag}")
    ctx.run(f"cd {KernelBuildPaths.linux_stable} && git checkout {tag}")

    return kernel_version

def make_config(ctx, extra_config: PathOrStr):
    dot_config = KernelBuildPaths.linux_stable / ".config"

    build_path = str(KernelBuildPaths.linux_stable)
    ctx.run(f"make -C {build_path} defconfig")
    ctx.run(f"make -C {build_path} kvm_guest.config")
    ctx.run(f"tee -a < {extra_config} {dot_config}")

    ctx.run(f"make -C {build_path} olddefconfig")


def make_kernel(run):
    run(f"make -C {KernelBuildPaths.linux_stable} -j$(nproc) deb-pkg KCFLAGS=-ggdb3")

@task
def checkout(ctx, kernel_version: str):
    _ = checkout_kernel(ctx, KernelVersion.from_str(kernel_version))


def get_kernel_pkg_dir(version: KernelVersion) -> Path:
    return KernelBuildPaths.kernel_sources_dir / version._get_kernel_pkg_dir()

def get_kernel_image_name(arch: KbuildArchOrLocal) -> str:
    if arch.kernel_arch == "x86":
        return "bzImage"
    if arch.kernel_arch == "arm64":
        return "Image.gz"

    raise Exit("unexpect architecture {arch}")

@task
def build_package(ctx, version: KernelVersion, arch_obj: KbuildArchOrLocal):
    sources_dir = os.path.join(".", "kernels", "sources")
    deb_files = glob(f"{KernelBuildPaths.kernel_sources_dir}/*.deb")

    kdir = get_kernel_pkg_dir(version)
    kdir.mkdir(exist_ok=True)

    for pkg in deb_files:
        ctx.run(f"mv {pkg} {kdir}")

    arch = arch_obj.kernel_arch
    ctx.run(f"mv {KernelBuildPaths.linux_stable}/vmlinux {kdir}")
    ctx.run(f"mv {KernelBuildPaths.linux_stable}/arch/{arch}/boot/{get_kernel_image_name(arch)} {kdir}")

    linux_source_dir = kdir / "linux-source"
    ctx.run(f"rm -rf {linux_source_dir}")
    linux_source_dir.mkdir()

    upstream = glob("./**/linux-*", recursive=True)
    found = False
    for f in upstream:
        if arch == "x86" and "upstream" in f and "orig.tar.gz" in f:
            ctx.run(f"mv {f} {kdir}/linux.tar.gz")
        elif arch == "arm64" and "orig.tar.gz" in f:
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

@task
def build(
    ctx,
    kernel_version: str,
    skip_patch: bool = True,
    arch: KbuildArchOrLocal | None = None,
    extra_config: PathOrStr | None = EXTRA_CONFIG,
    use_gcc8: bool = False
):
    if arch is None:
        arch = Arch.local()
    else:
        arch = Arch.from_str(arch)
    
    run_cmd = ctx.run
    if use_gcc8:
        cc = get_compiler(ctx)
        run_cmd = lambda x: cc.exec("cd {CONTAINER_LINUX_SRC_PATH} && {x}")

    kversion = KernelVersion.from_str(kernel_version)
    context = BuildContext(kversion)

    context.acquire()

    kversion = checkout_kernel(ctx, kversion)
    make_config(ctx, extra_config)
    make_kernel(run_cmd)
    build_package(ctx, kernel_version, arch)
    kuuid(ctx, kernel_version)


@task
def clean(ctx, kernel_version):
    kversion = KernelVersion.from_str(kernel_version)
    context = BuildContext(kversion)

    ctx.run(f"make -C {KernelBuildPaths.linux_stable} clean")
    ctx.run(f"cd {KernelBuildPaths.linux_stable} && git checkout master")
    ctx.run(f"cd {KernelBuildPaths.linux_stable} && rm .config", warn=True)
    ctx.run(f"cd {KernelBuildPaths.linux_stable} && rm -r debian", warn=True)
    ctx.run(f"cd {KernelBuildPaths.kernel_sources_dir} && rm *", warn=True)
    ctx.run("rm -f {KernelBuildPaths.linux_stable}/vmlinux-gdb.py")
    ctx.run("rm -f {KernelBuildPaths.linux_stable}/linux.tar.gz")
