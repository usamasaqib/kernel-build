from __future__ import annotations

from pathlib import Path

import sys
import os
from typing import Protocol, Optional
from invoke.context import Context
from tasks.arch import Arch
from tasks.tool import info, warn

CONTAINER_LINUX_BUILD_PATH = Path("/tmp/build")


class CompilerExec(Protocol):
    def __call__(
        self,
        cmd: str,
        user: str = "compiler",
        verbose: bool = True,
        run_dir: Optional[Path] = None,
        allow_fail: bool = False,
    ) -> None: ...


class CompilerImage:
    def __init__(self, ctx: Context, arch: Arch, mountpoint: Path):
        self.ctx = ctx
        self.arch: Arch = arch
        self.mountpoint = Path(mountpoint)

    @property
    def docker_cmd(self):
        with open("/etc/group", 'r') as f:
            groups = f.read().split()
        for group in groups:
            if group.split(':')[0] == "docker":
                if os.getlogin() in group:
                    return "docker"

        return "sudo docker"

    @property
    def name(self):
        return f"kernel-build-compiler-{self.arch.name}"

    @property
    def image(self):
        return f"kernel-build-compiler-image-{self.arch.name}"

    def _check_container_exists(self, allow_stopped: bool = False) -> bool:
        if self.ctx.config.run["dry"]:
            warn(f"[!] Dry run, not checking if compiler {self.name} is running")
            return True

        args = "a" if allow_stopped else ""
        res = self.ctx.run(
            f"{self.docker_cmd} ps -{args}qf \"name={self.name}\"", hide=True
        )
        if res is not None and res.ok:
            return bool(
                res.stdout.rstrip() != ""
            )  # typecasting for the benefit of mypy
        return False

    @property
    def is_running(self):
        return self._check_container_exists(allow_stopped=False)

    @property
    def is_loaded(self):
        return self._check_container_exists(allow_stopped=True)

    def ensure_running(self) -> None:
        if not self.is_running:
            info(f"[*] Compiler for {self.arch} not running, starting it...")
            try:
                self.start()
            except Exception as e:
                raise e

    def exec(
        self,
        cmd: str,
        user: str = "compiler",
        verbose: bool = True,
        run_dir: Optional[Path] = None,
        allow_fail: bool = False,
    ) -> None:
        if run_dir is not None:
            cmd = f"cd {run_dir} && {cmd}"

        self.ensure_running()

        # Set FORCE_COLOR=1 so that termcolor works in the container
        self.ctx.run(
            f"{self.docker_cmd} exec -u {user} -i -e FORCE_COLOR=1 {self.name} bash -c \"{cmd}\"",
            hide=(not verbose),
            warn=allow_fail,
        )

    def stop(self) -> None:
        self.ctx.run(
            f"{self.docker_cmd} rm -f $({self.docker_cmd} ps -aqf \"name={self.name}\")"
        )

    def start(self) -> None:
        if self.is_loaded:
            self.stop()

        # Check if the image exists
        res = self.ctx.run(
            f"{self.docker_cmd} image inspect {self.image}", hide=True, warn=True
        )
        if res is None or not res.ok:
            info(f"[!] Image {self.image} not found, building it...")
            self.ctx.run(f"cd scripts/ && {self.docker_cmd} build -t {self.image} .")

        if not self.mountpoint.exists():
            self.mountpoint.mkdir(parents=True)

        res = self.ctx.run(
            f"{self.docker_cmd} run -d --restart always --name {self.name} "
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
            raise ValueError(
                "Cannot start compiler as root, we need to run as a non-root user"
            )

        # Now create the compiler user with same UID and GID as the current user
        self.exec(f"getent group {gid} || groupadd -f -g {gid} compiler", user="root")
        self.exec(
            f"getent passwd {uid} || useradd -m -u {uid} -g {gid} compiler", user="root"
        )

        if sys.platform != "darwin":  # No need to change permissions in MacOS
            self.exec(
                f"chown {uid}:{gid} {CONTAINER_LINUX_BUILD_PATH} && chown -R {uid}:{gid} {CONTAINER_LINUX_BUILD_PATH}",
                user="root",
            )

        self.exec("apt install sudo", user="root")
        self.exec(
            "usermod -aG sudo compiler && echo 'compiler ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers",
            user="root",
        )


def get_compiler(ctx: Context, mountpoint: Path) -> CompilerImage:
    cc = CompilerImage(ctx, Arch.local(), mountpoint)
    cc.ensure_running()

    return cc
