"""Time in the server tests: the real asyncio.sleep, a wall clock frozen at a
local time of day, and waits on the automation engine's safety-ceiling tasks.

Not collected (no ``test_`` prefix). The fixtures that replace the engine's
sleep (fast_sleep, frozen_sleep, gated_sleep) live in tests/_fixtures.py.
"""

import asyncio
import time
from unittest.mock import patch

import app.automation.engine as engine

# The real sleep, captured before any fixture patches asyncio.sleep (the
# engine's sleep IS asyncio.sleep: patching it patches it for everyone).
REAL_SLEEP = asyncio.sleep
_REAL_LOCALTIME = time.localtime


def local(hour: int, minute: int = 0, second: float = 0.0) -> float:
    """Epoch seconds for a fixed Monday (2026-07-13) at a LOCAL clock time."""
    return time.mktime((2026, 7, 13, hour, minute, 0, 0, 0, -1)) + second


def clock(ts: float):
    """Freeze time.time and time.localtime at `ts` (a context manager)."""
    return patch.multiple(
        time, time=lambda: ts,
        localtime=lambda t=None: _REAL_LOCALTIME(ts if t is None else t),
    )


async def drain(key: str, timeout: float = 2.0) -> None:
    """Wait for the ceiling armed under `key` to finish its trip."""
    task = engine._safety_tasks.get(key)
    assert task is not None, f"no safety ceiling armed for {key}"
    await asyncio.wait_for(asyncio.shield(task), timeout=timeout)


def ended(task: asyncio.Task) -> bool:
    return task.cancelled() or task.done()
