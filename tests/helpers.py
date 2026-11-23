import asyncio
from collections.abc import Callable

TIMEOUT = 1.0


async def eventually(check: Callable[[], bool], timeout: float = 1.0) -> None:
    """Poll until check() is true. Server-side cleanup after a disconnect is async."""
    async with asyncio.timeout(timeout):
        while not check():
            await asyncio.sleep(0.01)
