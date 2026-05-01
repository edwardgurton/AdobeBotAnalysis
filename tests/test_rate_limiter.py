"""Tests for core/rate_limiter.py."""

import asyncio
import time

import httpx
import pytest

from adobe_downloader.core.rate_limiter import SlidingWindowRateLimiter, _is_retryable


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _noop() -> str:
    return "ok"


# ---------------------------------------------------------------------------
# _is_retryable
# ---------------------------------------------------------------------------

def _make_status_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://example.com")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError("err", request=req, response=resp)


def test_retryable_on_429():
    assert _is_retryable(_make_status_error(429))


def test_retryable_on_500():
    assert _is_retryable(_make_status_error(500))


def test_not_retryable_on_400():
    assert not _is_retryable(_make_status_error(400))


def test_not_retryable_on_non_http():
    assert not _is_retryable(ValueError("nope"))


# ---------------------------------------------------------------------------
# SlidingWindowRateLimiter.execute — basic correctness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_returns_result():
    limiter = SlidingWindowRateLimiter(max_requests=12, window_seconds=6.0)
    result = await limiter.execute(_noop)
    assert result == "ok"


@pytest.mark.asyncio
async def test_execute_passes_args():
    async def add(a: int, b: int) -> int:
        return a + b

    limiter = SlidingWindowRateLimiter(max_requests=12, window_seconds=6.0)
    result = await limiter.execute(add, 3, 4)
    assert result == 7


# ---------------------------------------------------------------------------
# Sliding-window enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_window_not_exceeded():
    """50 rapid requests must never violate the 12/6s window."""
    limiter = SlidingWindowRateLimiter(max_requests=12, window_seconds=6.0, max_concurrent=12)
    timestamps: list[float] = []

    async def record_time() -> None:
        timestamps.append(time.monotonic())

    tasks = [limiter.execute(record_time) for _ in range(50)]
    await asyncio.gather(*tasks)

    # Verify no 6-second window contains more than 12 timestamps.
    for i, ts in enumerate(timestamps):
        window_end = ts + 6.0
        count = sum(1 for t in timestamps if ts <= t < window_end)
        assert count <= 12, f"Window violation: {count} requests in 6s window starting at index {i}"


# ---------------------------------------------------------------------------
# Global pause
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_global_pause_delays_next_request():
    """set_pause(0.1) should delay the next acquire by ~0.1s."""
    limiter = SlidingWindowRateLimiter(max_requests=12, window_seconds=6.0)
    limiter.set_pause(0.1)

    start = time.monotonic()
    await limiter.execute(_noop)
    elapsed = time.monotonic() - start

    assert elapsed >= 0.09, f"Expected >=0.09s pause, got {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_global_pause_expires():
    """After the pause window, subsequent requests are not delayed."""
    limiter = SlidingWindowRateLimiter(max_requests=12, window_seconds=6.0)
    limiter.set_pause(0.05)

    # First request waits for the pause.
    await limiter.execute(_noop)

    # Second request should not be delayed by the (already-expired) pause.
    start = time.monotonic()
    await limiter.execute(_noop)
    elapsed = time.monotonic() - start

    assert elapsed < 0.05, f"Expected <0.05s, got {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# Semaphore concurrency cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrency_cap():
    """Never more than max_concurrent requests execute simultaneously."""
    max_concurrent = 3
    limiter = SlidingWindowRateLimiter(
        max_requests=100, window_seconds=1.0, max_concurrent=max_concurrent
    )
    in_flight: list[int] = []
    peak: list[int] = []

    async def slow() -> None:
        in_flight.append(1)
        peak.append(len(in_flight))
        await asyncio.sleep(0.02)
        in_flight.pop()

    tasks = [limiter.execute(slow) for _ in range(10)]
    await asyncio.gather(*tasks)

    assert max(peak) <= max_concurrent, f"Peak concurrency {max(peak)} exceeded {max_concurrent}"
