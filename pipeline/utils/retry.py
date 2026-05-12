import asyncio
import functools
from .logger import get_logger

logger = get_logger("retry")


def with_retry(max_attempts: int = 3, delay_seconds: float = 5.0, backoff: float = 2.0):
    """Exponential backoff retry decorator for async functions."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_attempts - 1:
                        raise
                    wait = delay_seconds * (backoff ** attempt)
                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt + 1}/{max_attempts}): "
                        f"{exc}. Retrying in {wait:.1f}s"
                    )
                    await asyncio.sleep(wait)
        return wrapper
    return decorator


def with_retry_sync(max_attempts: int = 3, delay_seconds: float = 5.0, backoff: float = 2.0):
    """Exponential backoff retry decorator for sync functions."""
    import time

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_attempts - 1:
                        raise
                    wait = delay_seconds * (backoff ** attempt)
                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt + 1}/{max_attempts}): "
                        f"{exc}. Retrying in {wait:.1f}s"
                    )
                    time.sleep(wait)
        return wrapper
    return decorator
