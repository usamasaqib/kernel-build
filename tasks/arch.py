from __future__ import annotations

import platform
from typing import Literal

KbuildArchName = Literal['x86', 'arm64']


class Arch:
    def __init__(
        self,
        name: str,
        gcc_arch: str,
        kernel_arch: str,
        kbuild_arch: KbuildArchName | None,
        spellings: set[str],
    ):
        self.name = name
        self.spellings = spellings
        self.gcc_arch = gcc_arch
        self._kbuild_arch: KbuildArchName | None = kbuild_arch
        self.kernel_arch = kernel_arch

    @property
    def kbuild_arch(self) -> KbuildArchName:
        if self._kbuild_arch is None:
            raise ValueError(f"Kernel build arch not defined for {self.name}")
        return self._kbuild_arch

    def __eq__(self, other: Arch) -> bool:  # type: ignore
        if not isinstance(other, Arch):
            return False
        return self.name == other.name

    def __str__(self) -> str:
        return self.name

    def __hash__(self) -> int:
        return hash(self.name)

    def __repr__(self) -> str:
        return f"<Arch:{self.name}>"

    @staticmethod
    def from_str(arch: str | Literal["local"] | Arch) -> Arch:
        if isinstance(arch, Arch):
            return arch

        if arch == "local":
            arch = platform.machine().lower()

        for arch_obj in ALL_ARCHS:
            if arch.lower() in arch_obj.spellings:
                return arch_obj
        raise KeyError(f"Unknown architecture: {arch}")

    @staticmethod
    def local() -> Arch:
        return Arch.from_str("local")


ARCH_ARM64 = Arch(
    name="arm64",
    gcc_arch="aarch64",
    kernel_arch="arm64",
    kbuild_arch="arm64",
    spellings={"arm64", "aarch64"},
)
ARCH_AMD64 = Arch(
    name="amd64",
    gcc_arch="x86_64",
    kernel_arch="x86",
    kbuild_arch="x86",
    spellings={"amd64", "x86_64", "x64", "x86-64"},
)

ALL_ARCHS = [ARCH_AMD64, ARCH_ARM64]
