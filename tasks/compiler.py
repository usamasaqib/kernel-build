from __future__ import annotations

from pathlib import Path

import sys
from invoke.context import Context
from tasks.arch import ARCH_AMD64, ARCH_ARM64, Arch
from tasks.tool import info, warn, Exit

CONTAINER_LINUX_BUILD_PATH = Path("/tmp/build")

class CompilerImage:
    def __init__(self, ctx: Context, arch: Arch, mountpoint: PathOrStr):
        self.ctx = ctx
        self.arch: Arch = arch
        self.mountpoint = Path(mountpoint)

    @property
    def name(self):
        return f"kernel-build-compiler-{self.arch.name}"

    @property
    def image(self):
        return f"kernel-build-compiler-image-{self.arch.name}"

    def _check_container_exists(self, allow_stopped=False):
        if self.ctx.config.run["dry"]:
            warn(f"[!] Dry run, not checking if compiler {self.name} is running")
            return True

        args = "a" if allow_stopped else ""
        res = self.ctx.run(f"docker ps -{args}qf \"name={self.name}\"", hide=True)
        if res is not None and res.ok:
            return res.stdout.rstrip() != ""
        return False

    @property
    def is_running(self):
        return self._check_container_exists(allow_stopped=False)

    @property
    def is_loaded(self):
        return self._check_container_exists(allow_stopped=True)

    def ensure_running(self):
        if not self.is_running:
            info(f"[*] Compiler for {self.arch} not running, starting it...")
            try:
                self.start()
            except Exception as e:
                raise e

    def exec(self, cmd: str, user="compiler", verbose=True, run_dir: PathOrStr | None = None, allow_fail=False):
        if run_dir:
            cmd = f"cd {run_dir} && {cmd}"

        self.ensure_running()

        # Set FORCE_COLOR=1 so that termcolor works in the container
        self.ctx.run(
            f"docker exec -u {user} -i -e FORCE_COLOR=1 {self.name} bash -c \"{cmd}\"",
            hide=(not verbose),
            warn=allow_fail,
        )

    def stop(self):
        res = self.ctx.run(f"docker rm -f $(docker ps -aqf \"name={self.name}\")")
        return res

    def start(self) -> None:
        if self.is_loaded:
            self.stop()

        # Check if the image exists
        res = self.ctx.run(f"docker image inspect {self.image}", hide=True, warn=True)
        if res is None or not res.ok:
            info(f"[!] Image {self.image} not found, building it...")
            self.ctx.run(f"cd scripts/ && docker build -t {self.image} .")
            
        if not self.mountpoint.exists():
            self.mountpoint.mkdir(parents=True)

        res = self.ctx.run(
            f"docker run -d --restart always --name {self.name} "
            f"--mount type=bind,source={self.mountpoint.absolute()},target={CONTAINER_LINUX_BUILD_PATH} "
            f"{self.image} sleep \"infinity\"",
        )

        # Due to permissions issues, we do not want to compile with the root user in the Docker image. We create a user
        # inside there with the same UID and GID as the current user
        uid = self.ctx.run("id -u").stdout.rstrip()
        gid = self.ctx.run("id -g").stdout.rstrip()

        if uid == 0:
            # If we're starting the compiler as root, we won't be able to create the compiler user
            # and we will get weird failures later on, as the user 'compiler' won't exist in the container
            raise ValueError("Cannot start compiler as root, we need to run as a non-root user")

        # Now create the compiler user with same UID and GID as the current user
        self.exec(f"getent group {gid} || groupadd -f -g {gid} compiler", user="root")
        self.exec(f"getent passwd {uid} || useradd -m -u {uid} -g {gid} compiler", user="root")

        if sys.platform != "darwin":  # No need to change permissions in MacOS
            self.exec(
                f"chown {uid}:{gid} {CONTAINER_LINUX_BUILD_PATH} && chown -R {uid}:{gid} {CONTAINER_LINUX_BUILD_PATH}", user="root"
            )

        self.exec("apt install sudo", user="root")
        self.exec("usermod -aG sudo compiler && echo 'compiler ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers", user="root")

def get_compiler(ctx: Context, mountpoint: str):
    cc = CompilerImage(ctx, Arch.local(), mountpoint)
    cc.ensure_running()

    return cc
