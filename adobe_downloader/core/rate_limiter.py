"""Async sliding-window rate limiter with global pause on 429."""

import asyncio
import logging
import time
from collections import deque
from typing import Any, Callable, Coroutine, TypeVar

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

T = TypeVar("T")

_RETRYABLE_STATUS = {429, 500, 502, 503}


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _RETRYABLE_STATUS


class SlidingWindowRateLimiter:
    """12 requests per 6-second sliding window with global pause on 429."""

    def __init__(
        self,
        max_requests: int = 12,
        window_seconds: float = 6.0,
        max_concurrent: int = 12,
    ) -> None:
        self._max_requests = max_requests
        self._window = window_seconds
        self._timestamps: deque[float] = deque()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()
        self._pause_until: float = 0.0

    def set_pause(self, duration: float = 10.0) -> None:
        """Signal a global pause (called on 429 receipt)."""
        self._pause_until = time.monotonic() + duration
        log.warning("Rate limiter: global pause set for %.1fs", duration)

    async def acquire(self) -> None:
        """Block until a request slot is available within the sliding window."""
        await self._semaphore.acquire()
        while True:
            now = time.monotonic()

            # Honour any global pause first.
            pause_remaining = self._pause_until - now
            if pause_remaining > 0:
                log.debug("Rate limiter: global pause — waiting %.2fs", pause_remaining)
                await asyncio.sleep(pause_remaining)
                now = time.monotonic()

            async with self._lock:
                # Evict timestamps outside the window.
                while self._timestamps and self._timestamps[0] <= now - self._window:
                    self._timestamps.popleft()

                if len(self._timestamps) < self._max_requests:
                    self._timestamps.append(now)
                    return  # Slot acquired; semaphore already held.

                # Window is full — calculate how long until the oldest slot expires.
                wait_for = self._timestamps[0] - (now - self._window)

            log.debug("Rate limiter: window full — sleeping %.3fs", wait_for)
            await asyncio.sleep(wait_for)

    def release(self) -> None:
        self._semaphore.release()

    async def execute(
        self,
        coro_func: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        request_id: str = "unknown",
        **kwargs: Any,
    ) -> T:
        """Acquire a slot, run coro_func, release on completion."""
        await self.acquire()
        try:
            log.debug("Rate limiter: executing request %s", request_id)
            return await asyncio.wait_for(coro_func(*args, **kwargs), timeout=120)
        finally:
            self.release()


def make_retry(limiter: SlidingWindowRateLimiter) -> Any:
    """Return a tenacity retry decorator wired to the limiter's global pause."""

    def before_retry(retry_state: Any) -> None:
        exc = retry_state.outcome.exception()
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
            limiter.set_pause(10.0)

    return retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        before_sleep=before_retry,
        reraise=True,
    )
