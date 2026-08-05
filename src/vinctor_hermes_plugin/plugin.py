from __future__ import annotations

import os
from typing import Any

from .boundary import VinctorHermesBoundary


def register(ctx: Any) -> None:
    boundary = VinctorHermesBoundary.from_env(env=dict(os.environ))
    ctx.register_hook("pre_tool_call", boundary.pre_tool_call)
