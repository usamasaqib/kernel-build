from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import invoke.exceptions as ie
from invoke.context import Context

from tasks.libs.types.arch import Arch

if TYPE_CHECKING:
    from tasks.kernel_matrix_testing.types import KMTArchName, KMTArchNameOrLocal, PathOrStr

try:
    from termcolor import colored
except ImportError:

    def colored(text: str, color: str | None) -> str:  # noqa: U100
        return text


def _logprint(msg: str):
    print(msg, flush=True, file=sys.stderr)


def ask(question: str) -> str:
    return input(colored(question, "blue"))


def debug(msg: str):
    _logprint(colored(msg, "white"))


def info(msg: str):
    _logprint(colored(msg, "green"))


def warn(msg: str):
    _logprint(colored(msg, "yellow"))


def error(msg: str):
    _logprint(colored(msg, "red"))


def Exit(msg: str):
    return ie.Exit(colored(msg, "red"))


def is_root():
    return os.getuid() == 0
