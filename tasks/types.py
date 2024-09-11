"""
File with type definitions that should be imported when typechecking
"""

from __future__ import annotations

import os
from typing import Literal, TypedDict

from tasks.arch import KbuildArchName

KbuildArchOrLocal = KbuildArchName | Literal['local']
PathOrStr = os.PathLike | str


