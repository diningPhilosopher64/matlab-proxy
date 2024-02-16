# Copyright 2020-2024 The MathWorks, Inc.

from typing import Dict
from contextlib import suppress

import asyncio

from matlab_proxy.util import mwi, system, windows

logger = mwi.logger.get()


def get_event_loop():
    """Returns an asyncio event loop by checking the Operating System and
    uses the appropriate asyncio API

    Returns:
        asyncio.loop: asyncio event loop.
    """
    try:
        # Try to get an existing event loop.
        # If there's no running event loop, raises RuntimeError.
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # If execution reached this except block, it implies that there
        # was no running event loop. So, create one.
        if system.is_posix():
            loop = asyncio.get_event_loop()
        else:
            loop = windows.get_event_loop()

    return loop


async def cancel_tasks(tasks: Dict[str, asyncio.Task]):
    """Cancels asyncio tasks.

    Args:
        tasks (Dict[str, asyncio.Task]): Contains (task_name, task) as entries in the Dict.
    """
    for name, task in list(tasks.items()):
        if task:
            with suppress(asyncio.CancelledError):
                task.cancel()
                await task
                logger.debug(f"{name} task stopped successfully")
