from __future__ import annotations

import os
import sys

import invoke.exceptions as ie
from termcolor import colored

def _logprint(msg: str) -> None:
    print(msg, flush=True, file=sys.stderr)


def ask(question: str) -> str:
    return input(colored(question, "blue"))


def debug(msg: str) -> None:
    _logprint(colored(msg, "white"))


def info(msg: str) -> None:
    _logprint(colored(msg, "green"))


def warn(msg: str) -> None:
    _logprint(colored(msg, "yellow"))


def error(msg: str) -> None:
    _logprint(colored(msg, "red"))


def Exit(msg: str): # type: ignore
    return ie.Exit(colored(msg, "red"))


def is_root() -> bool:
    return os.getuid() == 0
