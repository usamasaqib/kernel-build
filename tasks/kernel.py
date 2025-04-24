from __future__ import annotations

from glob import glob
from invoke import task, runners
from invoke.context import Context as InvokeContext
import uuid
import json
from pathlib import Path
from typing import Callable, Optional

from tasks.arch import Arch
from tasks.tool import info, Exit
from tasks.compiler import get_compiler, CONTAINER_LINUX_BUILD_PATH, CompilerExec
from typing_extensions import TypedDict

DEFAULT_GIT_SOURCE = (
    "git://git.kernel.org/pub/scm/linux/kernel/git/stable/linux-stable.git"
)


class KernelManifest(TypedDict, total=False):
    kid: str
    kernel_source_dir: str
    gateway_ip: str
    guest_ip: str
    tap_name: str
    gdb_port: int


class KernelVersion:
    def __init__(self, major: int, minor: int, patch: int, branch: str = ""):
        self.major = major
        self.minor = minor
        self.patch = patch
        self.branch = branch
        self.worktree = f"{self}-build/{self}"

    def __str__(self) -> str:
        if self.branch == "":
            return f"v{self.major}.{self.minor}.{self.patch}"
        return self.branch

    def __eq__(self, other: KernelVersion) -> bool:  # type: ignore
        if isinstance(other, KernelVersion):
            return (
                self.major == other.major
                and self.minor == other.minor
                and self.patch == other.patch
            )

        raise NotImplementedError

    def __lt__(self, other: KernelVersion) -> bool:
        if not isinstance(other, KernelVersion):
            raise NotImplementedError

        if self.major < other.major:
            return True
        if self.major == other.major and self.minor < other.minor:
            return True

        return self.minor == other.minor and self.patch < other.patch

    def __lte__(self, other: KernelVersion) -> bool:
        return self.__lt__(other) or self.__eq__(other)

    def __gt__(self, other: KernelVersion) -> bool:
        return not self.__lte__(other)

    def _get_kernel_pkg_dir(self) -> str:
        suffix = f"{self}".replace("/", "-")
        return f"kernel-{suffix}"

    def worktree_base(self) -> str:
        return f"{self}-build"

    @staticmethod
    def from_str(ctx: Optional[InvokeContext], v: str) -> KernelVersion:
        broken = v.split(".")
        if len(broken) < 2 or len(broken) > 3 or "-rc" in v:
            info(f"Using branch name '{v}' instead of tag")
            return KernelVersion(0, 0, 0, v)

        if broken[0][0] == "v":
            major = int(broken[0][1:])
        else:
            major = int(broken[0])

        minor = int(broken[1])
        if len(broken) == 3:
            patch = int(broken[2])
        else:
            patch = -1

        if patch == -1:
            return KernelVersion(major, minor, discover_latest_patch(ctx, major, minor))

        return KernelVersion(major, minor, patch)


class KernelBuildPaths:
    kernel_dir = Path("./kernels")
    kernel_sources_dir = kernel_dir / "sources"
    linux_stable = kernel_sources_dir / "linux-stable"
    configs_dir = kernel_dir / "configs"


def bare_repository(ctx, repo):
    description = repo / "description"
    if not description.exists():
        return False

    with open(description, 'r') as f:
        desc = f.read().strip()

    if desc == "bare repository":
        return True

    return False


def clone_kernel_source(
    ctx: InvokeContext,
    repo_link: str,
    kernel_version: KernelVersion | None = None,
) -> None:
    KernelBuildPaths.linux_stable.mkdir(parents=True)

    git_cmd = "git clone --bare"

    if kernel_version is not None and kernel_version.branch != "":
        git_cmd += f" -b {kernel_version.branch} --single-branch"

    ctx.run(f"{git_cmd} {repo_link} {KernelBuildPaths.linux_stable}")
    ctx.run(f"cd {KernelBuildPaths.linux_stable} && git worktree add master")

    description = KernelBuildPaths.linux_stable / "description"
    if description.exists():
        with open(description, 'w') as f:
            f.write("bare repository")


def discover_latest_patch(ctx: InvokeContext, major: int, minor: int) -> int:
    if not KernelBuildPaths.linux_stable.exists():
        clone_kernel_source(ctx, DEFAULT_GIT_SOURCE)
    tag_res = ctx.run(
        f"cd {KernelBuildPaths.linux_stable} && git tag | grep 'v{major}.{minor}.*$' | sort -V | tail -1",
        hide=True,
    )
    tag = tag_res.stdout.split()[0]
    return KernelVersion.from_str(None, tag).patch


def checkout_kernel(
    ctx: InvokeContext,
    kernel_version: KernelVersion,
    git_source: str,
    pull: bool = False,
) -> bool:
    cloned = False
    if not KernelBuildPaths.linux_stable.exists():
        clone_kernel_source(
            ctx,
            kernel_version=kernel_version,
            repo_link=git_source,
        )
        cloned = True

    if pull:
        ctx.run(f"cd {KernelBuildPaths.linux_stable} && git pull")

    info(f"[+] Creating new worktree for tag {kernel_version}")
    worktree = KernelBuildPaths.linux_stable / kernel_version.worktree
    if not worktree.exists():
        ctx.run(
            f"cd {KernelBuildPaths.linux_stable} && git worktree add {kernel_version.worktree}"
        )

    ctx.run(f"cd {worktree} && git checkout tags/{kernel_version}")

    return cloned


@task  # type: ignore
def make_config(
    ctx: InvokeContext, source_dir: Path, extra_config: Optional[str]
) -> None:
    if extra_config is None:
        all_configs = set(EXTRA_CONFIG)
    else:
        all_configs = set()

    if extra_config is not None:
        all_configs = set([Path(p) for p in extra_config.split(',')] + EXTRA_CONFIG)

    build_path = str(source_dir)
    ctx.run(f"make -C {build_path} KCONFIG_CONFIG=start.config defconfig")

    start_config = source_dir / "start.config"
    for cfg in all_configs:
        ctx.run(f"tee -a < {cfg} {start_config}")

    ctx.run(f"make -C {build_path} allnoconfig KCONFIG_ALLCONFIG=start.config")

    ctx.run(f"make -C {build_path} kvm_guest.config")


Runner = Callable[[str], Optional[runners.Result]] | CompilerExec


def make_kernel(run: Runner, sources_dir: Path, compile_only: bool) -> None:
    if compile_only:
        run(f"make -C {sources_dir} -j$(nproc) bzImage KCFLAGS=-ggdb3")
    else:
        run(f"make -C {sources_dir} -j$(nproc) deb-pkg KCFLAGS=-ggdb3")


@task  # type: ignore
def checkout(
    ctx: InvokeContext,
    kernel_version: str,
) -> None:
    checkout_kernel(
        ctx,
        KernelVersion.from_str(ctx, kernel_version),
        DEFAULT_GIT_SOURCE,
    )


def get_kernel_pkg_dir(version: KernelVersion) -> Path:
    return KernelBuildPaths.kernel_sources_dir / version._get_kernel_pkg_dir()


def get_kernel_image_name(arch: Arch) -> str:
    if arch.kernel_arch == "x86":
        return "bzImage"
    if arch.kernel_arch == "arm64":
        return "Image.gz"

    raise Exit("unexpect architecture {arch}")


@task  # type: ignore
def build_package(
    ctx: InvokeContext,
    build_dir: Path,
    version: KernelVersion,
    arch: Arch,
    compile_only: bool,
) -> None:
    df = KernelBuildPaths.linux_stable / version.worktree
    deb_files = glob(f"{df}/../*.deb")

    kdir = get_kernel_pkg_dir(version)
    kdir.mkdir(exist_ok=True)
    for pkg in deb_files:
        ctx.run(f"mv {pkg} {kdir}")

    ctx.run(f"mv {build_dir}/vmlinux {kdir}")
    ctx.run(
        f"mv {build_dir}/arch/{arch.kernel_arch}/boot/{get_kernel_image_name(arch)} {kdir}"
    )

    if compile_only:
        return

    linux_source_dir = kdir / "linux-source"
    ctx.run(f"rm -rf {linux_source_dir}")
    linux_source_dir.mkdir()

    upstream = glob(f"{build_dir}/../**/linux-*", recursive=True)
    found = False
    for f in upstream:
        if "orig.tar.gz" in f:
            dst = f"{kdir}/linux.tar.gz"
            ctx.run(f"rm -f {dst} && mv {f} {dst}")
            found = True

    if not found:
        raise Exit("kernel-build: build_package: unable to find source package")

    ctx.run(f"tar -xvf {kdir}/linux.tar.gz -C {linux_source_dir} --strip-components=1")


def save_manifest(manifest: KernelManifest, kernel_version: KernelVersion) -> None:
    kernel_dir = get_kernel_pkg_dir(kernel_version)
    with open(f"{kernel_dir}/kernel.manifest", "w+") as f:
        json.dump(manifest, f)


def manifest_add_kernel_source_dir(
    manifest: KernelManifest,
    kernel_src_dir: Path,
) -> KernelManifest:
    manifest["kernel_source_dir"] = kernel_src_dir.absolute().as_posix()
    return manifest


def manifest_add_kuuid(
    manifest: KernelManifest, kernel_version: KernelVersion
) -> KernelManifest:
    kid = str(uuid.uuid4())
    manifest["kid"] = kid
    return manifest


EXTRA_CONFIG = [
    KernelBuildPaths.configs_dir / "bpf.config",
    KernelBuildPaths.configs_dir / "virtio.config",
    KernelBuildPaths.configs_dir / "trace.config",
    KernelBuildPaths.configs_dir / "remove-drivers.config",
    KernelBuildPaths.configs_dir / "debug.config",
    KernelBuildPaths.configs_dir / "docker.config",
    KernelBuildPaths.configs_dir / "net.config",
    KernelBuildPaths.configs_dir / "netfilter.config",
    KernelBuildPaths.configs_dir / "net-drivers.config",
    # KernelBuildPaths.configs_dir / "lockdep.config",
]


@task(  # type: ignore
    help={
        "kernel_version": "kernel version string of the form v6.8 or v5.2.20",
        "arch": "architecture of the form x86 or aarch64, etc.",
        "extra_config": "path to file containing extra KConfig options",
        "compile_only": "only rebuild bzImage",
        "always_use_gcc8": "always compile in docker container with gcc-8",
    },
)
def build(
    ctx: InvokeContext,
    kernel_version: str,
    arch: Arch | None = None,
    extra_config: str | None = None,
    compile_only: bool = False,
    always_use_gcc8: bool = False,
    kernel_src_dir: str | None = None,
    git_source: str = DEFAULT_GIT_SOURCE,
) -> None:
    build_kernel(
        ctx,
        KernelVersion.from_str(ctx, kernel_version),
        arch=arch,
        extra_config=extra_config,
        compile_only=compile_only,
        kernel_src_dir=kernel_src_dir,
        git_source=git_source,
    )


def requires_gcc8(kernel_version: KernelVersion) -> bool:
    if kernel_version.branch != "" or kernel_version > KernelVersion(5, 5, 0):
        return False

    return True


def use_docker_compiler(kernel_version: KernelVersion, always_use_gcc8: bool) -> bool:
    return requires_gcc8(kernel_version) or always_use_gcc8


def build_kernel(
    ctx: InvokeContext,
    kversion: KernelVersion,
    git_source: str,
    extra_config: Optional[str] = None,
    arch: Optional[Arch] = None,
    compile_only: bool = False,
    always_use_gcc8: bool = False,
    kernel_src_dir: str | None = None,
) -> None:
    if arch is None:
        arch = Arch.local()
    else:
        arch = Arch.from_str(arch)

    if kernel_src_dir is not None:
        KernelBuildPaths.linux_stable = Path(kernel_src_dir)

    cloned = checkout_kernel(ctx, kversion, git_source)
    if cloned and use_docker_compiler(kversion, always_use_gcc8):
        # restart compiler if we had to clone the kernel sources again
        cc = get_compiler(ctx, KernelBuildPaths.kernel_sources_dir)
        cc.stop()

    run_cmd = ctx.run
    source_dir = KernelBuildPaths.linux_stable / f"{kversion.worktree}"
    if use_docker_compiler(kversion, always_use_gcc8):
        cc = get_compiler(ctx, KernelBuildPaths.kernel_sources_dir)
        run_cmd = cc.exec
        source_dir = (
            CONTAINER_LINUX_BUILD_PATH / "linux-stable" / f"{kversion.worktree}"
        )

    make_config(ctx, source_dir, extra_config)
    make_kernel(run_cmd, source_dir, compile_only)
    build_package(ctx, source_dir, kversion, arch, compile_only)

    manifest: KernelManifest = {}
    manifest = manifest_add_kuuid(manifest, kversion)
    manifest = manifest_add_kernel_source_dir(manifest, source_dir)
    save_manifest(manifest, kversion)

    info(f"[+] Kernel {kversion} build complete")


@task  # type: ignore
def clean(
    ctx: InvokeContext,
    kernel_version: str,
    full: bool = False,
) -> None:
    kversion = KernelVersion.from_str(ctx, kernel_version)

    if full:
        ctx.run(
            f"cd {KernelBuildPaths.linux_stable} && git worktree remove {kversion.worktree} --force"
        )
        ctx.run(
            f"cd {KernelBuildPaths.linux_stable} && rm -rf {kversion.worktree_base()}"
        )
        return

    build_dir = KernelBuildPaths.linux_stable / f"{kversion.worktree}"
    ctx.run(f"make -C {build_dir} clean")
    ctx.run(f"make -C {build_dir}/tools clean", warn=True)
    # TODO: remove after snapshotting feature added
    ctx.run(f"cd {KernelBuildPaths.linux_stable} && rm -f linux-*")

    if kversion < KernelVersion(5, 5, 0):
        cc = get_compiler(ctx, KernelBuildPaths.linux_stable)
        cc.exec("rm -f /tmp/*", allow_fail=True)
