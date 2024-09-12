from __future__ import annotations

import sys

import invoke.exceptions as ie
from termcolor import colored


def _logprint(msg: str) -> None:
    print(msg, flush=True, file=sys.stderr)


def info(msg: str) -> None:
    _logprint(colored(msg, "green"))


def warn(msg: str) -> None:
    _logprint(colored(msg, "yellow"))


def Exit(msg: str):  # type: ignore
    return ie.Exit(colored(msg, "red"))
