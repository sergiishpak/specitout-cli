from __future__ import annotations

from typing import TypedDict


class CommandEnvelope(TypedDict):
    status: str
    command: str
    scope: dict[str, str | None]
    data: dict[str, object]
    warnings: list[str]
    degraded: bool
    next_actions: list[str]
