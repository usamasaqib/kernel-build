"""
Standardized management of architecture values
"""

from __future__ import annotations

import platform
from typing import Literal

KbuildArchName = Literal['x86', 'arm64']


class Arch:
    """A class representing an architecture. Contains all the names that this arch
    might have depending on where it is used.

    For example, the AMD64 architecture is known as "amd64" in Go, "x86_64" in GCC,
    "x64" in Windows, etc. With this class we just pass around a single object, enabling
    easy comparisons (Arch objects implement __eq__ and __hash__) and easy access to the
    different names.

    Use Arch.from_str to convert from a string to an Arch object.
    Use Arch.local() to get the Arch object for the current machine's architecture.
    """

    def __init__(
        self,
        name: str,
        gcc_arch: str,
        kernel_arch: str,
        kbuild_arch: KbuildArchName | None,
        spellings: set[str],
    ):
        self.name = name  #: Unique name for this architecture within this file.
        self.spellings = spellings  #: All the possible names for this architecture. Will be used when parsing user input.
        self.gcc_arch = gcc_arch  #: Architecture used for GCC
        self._kbuild_arch: KbuildArchName | None = (
            kbuild_arch  #: Architecture used for build, if supported
        )
        self.kernel_arch = kernel_arch  #: Name for the architecture in the Linux kernel

    @property
    def kbuild_arch(self) -> KbuildArchName:
        """
        Return the kernel build arch name for this architecture. Raises ValueError if not defined.

        Useful to avoid constant None checks
        """
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
        """Parse a string into an Arch object. If the input is already an Arch object, it is returned as is.

        If the input is "local", the current machine's architecture is used, can be used as a shorthand
        instead of Arch.from_str(platform.machine()).

        Will raise KeyError if the architecture is not recognized.
        """
        if isinstance(arch, Arch):
            return arch

        if arch == "local":
            arch = platform.machine().lower()

        # Not the most efficient way to do this, but the list is small
        # enough and this way we avoid having to maintain a dictionary
        for arch_obj in ALL_ARCHS:
            if arch.lower() in arch_obj.spellings:
                return arch_obj
        raise KeyError(f"Unknown architecture: {arch}")

    @staticmethod
    def local() -> Arch:
        """Shorthand to return the Arch object for the current machine's architecture."""
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
